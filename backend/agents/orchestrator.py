"""
Agent orchestrator — the diagnostic *harness* around the six existing agents.

                    USER QUERY
                         │
                 QUERY PREPARATION  (deterministic)
                         │
                  MULTI-STAGE RAG   (semantic · metadata · numeric · historical → rerank)
                         │
      ┌──────────────────┼──────────────────┐
 Diagnostic Expert   Pattern Agent     Rapid Triage       (parallel, independent)
      └──────────────────┼──────────────────┘
                   VERIFICATION      (adversarial, evidence-first)
                         │
                  EVIDENCE CHECK ──weak──► TARGETED RAG ──► re-run ONLY the affected agent
                         │                      │              └► re-verify
                       strong ◄─────────────────┘   (max 2 rounds, each deficiency once)
                         │
                     AMBIGUITY       (measured uncertainty + confidence factors)
                         │
                 FINAL COORDINATOR   (claim-validated, evidence-cited answer)
                         │
                 HUMAN REVIEW GATE   (explicit criteria)

No new LLM agents were added: evidence checking, targeted retrieval, claim
validation, confidence and the review gate are deterministic harness modules.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence

from agents.aggressive_decision import AggressiveDecisionAgent
from agents.ambiguity_detection import AmbiguityDetectionAgent
from agents.base_agent import AgentContext
from agents.diagnostic_expert import DiagnosticExpertAgent
from agents.human_review_coordinator import HumanReviewCoordinatorAgent
from agents.pattern_recognition import PatternRecognitionAgent
from agents.system_analysis_agent import SystemAnalysisAgent
from agents.verification_analyst import VerificationAnalystAgent
from harness.analysis import critical_sensors, failure_iq_candidates, score_hypotheses, sensor_assessment
from harness.audit import AuditRecorder
from harness.canonical import SENSOR_SPECS, fmt_sensor
from harness.claims import ClaimValidator
from harness.knowledge_base import KnowledgeBase
from harness.query_prep import prepare_query
from harness.retrieval import MultiStageRetriever, RetrievalResult
from harness.rules import RULE_THRESHOLDS
from harness.schema import AgentReport, Deficiency, DiagnosticState, Evidence
from utils.llm_client import llm_client
from utils.logger import setup_logger

logger = setup_logger(__name__)

MAX_FEEDBACK_ROUNDS = int(os.getenv("MAX_FEEDBACK_ROUNDS", "2"))
MARGIN_CONFLICT = 0.15
HIST_WEAK = 0.40
WEAK_RETRIEVAL = 0.30

PERSONA_CATALOG = {
    "diagnostic_expert": {
        "agent_name": "Diagnostic Expert", "agent_persona": "Dr. Elena Vasquez", "agent_emoji": "🧠",
        "persona_title": "Senior Reliability Engineer",
        "persona_description": "Generates competing hypotheses and cites supporting, contradicting and missing evidence for each.",
        "specialty": "Hypothesis-driven reliability diagnosis", "decision_style": "Evidence ranking and structured elimination",
        "execution_mode": "parallel",
    },
    "pattern_agent": {
        "agent_name": "Pattern Recognition Agent", "agent_persona": "Dr. Aisha Patel", "agent_emoji": "🔍",
        "persona_title": "Predictive Maintenance Data Scientist",
        "persona_description": "Analyses nearest historical cases, anomalous channels and whether any strong precedent exists.",
        "specialty": "Historical signature matching", "decision_style": "Similarity analysis", "execution_mode": "parallel",
    },
    "aggressive_agent": {
        "agent_name": "Rapid Triage Agent", "agent_persona": "Commander Marcus Chen", "agent_emoji": "⚡",
        "persona_title": "Rapid Failure Triage Officer",
        "persona_description": "Fast deterministic rules (consistency, bands, signature direction) producing a rapid_signal to be challenged.",
        "specialty": "Rule-based triage and severity", "decision_style": "Deterministic rules", "execution_mode": "parallel",
    },
    "verification": {
        "agent_name": "Verification Analyst", "agent_persona": "Priya Raman", "agent_emoji": "✅",
        "persona_title": "Reliability Assurance Lead",
        "persona_description": "Adversarially checks every candidate against evidence; agreement never substitutes for evidence.",
        "specialty": "Adversarial verification", "decision_style": "Evidence reconciliation", "execution_mode": "review",
    },
    "ambiguity": {
        "agent_name": "Ambiguity Detection Agent", "agent_persona": "Dr. Sofia Nakamura", "agent_emoji": "🎯",
        "persona_title": "Uncertainty Quantification Specialist",
        "persona_description": "Primary uncertainty evaluator: measures missing data, conflicts, weak retrieval and computes factor-based confidence.",
        "specialty": "Uncertainty quantification", "decision_style": "Measured risk factors", "execution_mode": "calibration",
    },
    "human_review_coordinator": {
        "agent_name": "Human Review Coordinator", "agent_persona": "Director Sarah Mitchell", "agent_emoji": "🏁",
        "persona_title": "Plant Operations Director",
        "persona_description": "Composes the claim-validated final answer and applies the explicit human-review gate.",
        "specialty": "Final synthesis & safety gate", "decision_style": "Explicit criteria", "execution_mode": "synthesis",
    },
}

STATE_SLOT = {
    "diagnostic_expert": "diagnostic_expert_output",
    "pattern_agent": "pattern_output",
    "aggressive_agent": "rapid_triage_output",
    "verification": "verification_output",
    "ambiguity": "ambiguity_output",
    "human_review_coordinator": "coordinator_output",
}


class AgentOrchestrator:
    """Coordinates the six agents through the shared DiagnosticState."""

    def __init__(self):
        self.diagnostic_expert = DiagnosticExpertAgent()
        self.aggressive_decision = AggressiveDecisionAgent()
        self.pattern_recognition = PatternRecognitionAgent()
        self.verification_analyst = VerificationAnalystAgent()
        self.ambiguity_detection = AmbiguityDetectionAgent()
        self.human_review_coordinator = HumanReviewCoordinatorAgent()
        self.system_analysis = SystemAnalysisAgent()
        self._retrievers: Dict[int, MultiStageRetriever] = {}
        self.agents = {
            "diagnostic_expert": self.diagnostic_expert, "pattern_agent": self.pattern_recognition,
            "aggressive_agent": self.aggressive_decision, "verification": self.verification_analyst,
            "ambiguity": self.ambiguity_detection, "human_review_coordinator": self.human_review_coordinator,
        }

    # ─────────────────────────────────────────────────────────────────────────
    async def run_harness(self, question: str, dataset_type: str, data_mode: str, kb: KnowledgeBase,
                          embedder=None, store=None, top_k: int = 8,
                          exclude_record_ids: Sequence[str] = ()) -> Dict[str, Any]:
        t_start = time.perf_counter()
        state = DiagnosticState(run_id=uuid.uuid4().hex[:12], query=question, dataset_type=dataset_type,
                                data_mode=data_mode)
        audit = AuditRecorder(state)
        retriever = self._retrievers.setdefault(id(kb), MultiStageRetriever(kb, embedder, store))
        ref = kb.reference(data_mode)
        self._excl = list(exclude_record_ids)
        self._top_k = top_k

        # 1 ── query preparation
        with audit.step("query_prep", "prepare_query") as ev:
            state.profile = prepare_query(question)
            p = state.profile
            ev.reason = (f"{len(p.sensors)} numeric channel(s), {len(p.missing_sensors)} explicitly missing, "
                         f"{len(p.qualitative)} directional cue(s), equipment={p.equipment_type or 'unknown'}")
            if p.notes:
                ev.reason += " | " + "; ".join(p.notes)

        # 2 ── initial multi-stage RAG
        with audit.step("initial_rag", "multi_stage_retrieval") as ev:
            rr = retriever.retrieve(state.profile, data_mode, top_k=top_k, exclude_ids=self._excl)
            self._ingest(state, rr, round_no=0, replace=True)
            ev.retrieval_count = len(state.evidence)
            ev.evidence_used = [e.evidence_id for e in state.evidence]
            ev.reason = (f"scheme={rr.stats['scheme']}; {rr.stats['candidates_total']} candidates → "
                         f"{len(state.evidence)} evidence; composition {rr.stats['source_composition']}")

        known_labels = self._known_labels(kb, ref, state)
        ctx = AgentContext(kb=kb, ref=ref, mode=data_mode, llm_enabled=llm_client.is_available(),
                           known_labels=known_labels)

        with audit.step("numerical_analysis", "score_hypotheses") as ev:
            self._analyse(state, ctx)
            hs = state.analysis.get("hypotheses", [])[:3]
            ev.reason = ", ".join(f"{h['label']} {h['score']:.2f}" for h in hs) or "no hypotheses"

        # 3 ── three independent perspectives (parallel)
        await asyncio.gather(
            self._run_agent("diagnostic_expert", state, ctx, audit, stage="phase1"),
            self._run_agent("pattern_agent", state, ctx, audit, stage="phase1"),
            self._run_agent("aggressive_agent", state, ctx, audit, stage="phase1"),
        )

        # 4 ── verification
        await self._run_agent("verification", state, ctx, audit, stage="verification")

        # 5 ── controlled feedback loop
        handled: set = set()
        for _ in range(MAX_FEEDBACK_ROUNDS + 1):
            with audit.step("evidence_check", "assess_evidence_sufficiency") as ev:
                defs = self._evidence_check(state, ctx)
                state.deficiencies_history.append(defs)
                actionable = [d for d in defs if d.action != "none" and d.code not in handled]
                ev.reason = ("sufficient" if not defs else "; ".join(f"{d.code}: {d.detail}" for d in defs))
                ev.status = "warning" if actionable else "ok"
            if not actionable or state.feedback_rounds >= MAX_FEEDBACK_ROUNDS:
                break
            state.feedback_rounds += 1
            rerun: List[str] = []
            conflict: Optional[Dict] = None
            for d in actionable:
                handled.add(d.code)
                result = self._execute_action(d, state, ctx, retriever, audit)
                if d.code == "CONFLICTING_HYPOTHESES":
                    conflict = result
                rerun.extend(r for r in d.rerun if r not in rerun)
            if any(d.action in ("historical_retrieval", "expanded_rerank", "metadata_filtered_retrieval",
                                "expanded_historical_search") for d in actionable):
                with audit.step("numerical_analysis", "rescore_with_targeted_evidence", reason="re-run numerical analysis") as ev:
                    self._analyse(state, ctx)
                    ev.status = "loop"
            for key in rerun:
                kwargs = {"conflict": conflict} if key == "diagnostic_expert" and conflict else {}
                await self._run_agent(key, state, ctx, audit, stage="targeted_rerun", status="loop", **kwargs)
            await self._run_agent("verification", state, ctx, audit, stage="verification", status="loop")

        # 6 ── ambiguity, final coordinator + gate
        await self._run_agent("ambiguity", state, ctx, audit, stage="ambiguity")
        await self._run_agent("human_review_coordinator", state, ctx, audit, stage="final_coordinator")
        audit.note("claim_validation", "validate_final_claims",
                   reason=f"{ClaimValidator(state, known_labels).summary()}")
        audit.note("review_gate", state.review.decision if state.review else "n/a",
                   reason="; ".join(state.review.reasons) if state.review and state.review.reasons else "all criteria passed",
                   status="warning" if state.review and state.review.decision != "AUTO_RESOLVE" else "ok",
                   agent="human_review_coordinator")

        latency_ms = (time.perf_counter() - t_start) * 1000
        return self._build_response(state, ctx, kb, latency_ms)

    # ─────────────────────────────────────────────────────────────────────────
    async def _run_agent(self, key: str, state: DiagnosticState, ctx: AgentContext, audit: AuditRecorder,
                         stage: str, status: str = "ok", **kwargs) -> AgentReport:
        agent = self.agents[key]
        t0 = time.perf_counter()
        try:
            report = await agent.analyze(state, ctx, **kwargs)
            ev_status = status
            reason = report.finding
        except Exception as exc:          # partial failure: keep the pipeline alive
            logger.exception("Agent %s failed", key)
            report = AgentReport(agent=key, display_name=PERSONA_CATALOG[key]["agent_name"],
                                 finding="Agent failed", narrative=f"Agent error: {exc}", confidence=0.0)
            ev_status, reason = "error", str(exc)
        setattr(state, STATE_SLOT[key], report)
        audit.note(stage, f"{key}.analyze (pass {report.pass_number})", reason=reason[:200], status=ev_status,
                   agent=key, evidence_used=list(dict.fromkeys(report.evidence_ids))[:12])
        state.audit_trail[-1].duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        state.audit_trail[-1].retrieval_count = len(state.evidence)
        return report

    # ── evidence handling ────────────────────────────────────────────────────
    def _ingest(self, state: DiagnosticState, rr: RetrievalResult, round_no: int, replace: bool = False,
                limit: Optional[int] = None) -> List[str]:
        if replace:
            state.evidence = []
            state.retrieval_stats = dict(rr.stats)
            state.retrieval_stats["rounds"] = [{"round": 0, "action": "initial", "added": 0}]
        existing = {(e.dataset, e.record_id) for e in state.evidence}
        added = []
        for c in rr.bundle:
            if limit is not None and len(added) >= limit:
                break
            key = (c.record.dataset, c.record.record_id)
            if key in existing:
                continue
            existing.add(key)
            eid = f"EV-{len(state.evidence) + 1:03d}"
            state.evidence.append(Evidence(
                evidence_id=eid, dataset=c.record.dataset, record_id=c.record.record_id,
                source_type=c.record.source_type, retrieval_score=round(c.fused, 4), retrieval_method=c.method,
                method_scores={k: round(v, 4) for k, v in c.scores.items()}, label=c.record.label,
                content=c.record.evidence_content(), content_text=c.record.text[:1600],
                selection_reason="; ".join(c.reasons) or "retrieved", retrieval_round=round_no))
            added.append(eid)
        if replace:
            state.retrieval_stats["rounds"][0]["added"] = len(added)
        state.retrieval_quality = float(state.retrieval_stats.get("mean_top5_fused", 0.0))
        return added

    def _merge_stats(self, state: DiagnosticState, rr: RetrievalResult, action: str, added: List[str],
                     round_no: int, update_historical: bool) -> None:
        s = state.retrieval_stats
        if update_historical and rr.stats.get("historical_support"):
            s["historical_support"] = rr.stats["historical_support"]
        if rr.stats.get("best_numeric_distance") is not None:
            prev = s.get("best_numeric_distance")
            s["best_numeric_distance"] = min(prev, rr.stats["best_numeric_distance"]) if prev is not None else rr.stats["best_numeric_distance"]
            if s.get("no_match_threshold"):
                s["no_historical_match"] = s["best_numeric_distance"] > s["no_match_threshold"]
        comp: Dict[str, int] = {}
        for e in state.evidence:
            comp[e.source_type] = comp.get(e.source_type, 0) + 1
        s["source_composition"] = comp
        s.setdefault("rounds", []).append({"round": round_no, "action": action, "added": len(added),
                                           "evidence_ids": added, "label_filter": rr.stats.get("label_filter")})

    def _analyse(self, state: DiagnosticState, ctx: AgentContext) -> None:
        prof = state.profile
        if state.dataset_type == "failure_iq" or not ctx.kb.has_numeric():
            votes = failure_iq_candidates(state.evidence, prof) if state.dataset_type == "failure_iq" else \
                [(e.label, e.retrieval_score) for e in state.evidence]
            hyps = score_hypotheses(prof, ctx.ref.__class__(**{**ctx.ref.__dict__, "signatures": {}, "labels": []}),
                                    {}, votes)
        else:
            hyps = score_hypotheses(prof, ctx.ref, state.retrieval_stats.get("historical_support") or {},
                                    [(e.label, e.retrieval_score) for e in state.evidence])
        state.analysis["hypotheses"] = hyps
        if prof and prof.sensors and ctx.kb.has_numeric():
            state.analysis["sensor_assessment"] = sensor_assessment(prof, ctx.ref)
        for lab in [h["label"] for h in hyps if h["label"] not in ctx.known_labels]:
            ctx.known_labels.append(lab)

    # ── evidence sufficiency & targeted actions ──────────────────────────────
    def _evidence_check(self, state: DiagnosticState, ctx: AgentContext) -> List[Deficiency]:
        ver = state.verification_output
        stats = state.retrieval_stats
        prof = state.profile
        defs: List[Deficiency] = []
        if not ver:
            return defs
        ex = ver.extras
        label = ex.get("verified_label")
        numeric = stats.get("scheme") == "numeric"
        hist = stats.get("historical_support") or {}
        if numeric and stats.get("no_historical_match"):
            defs.append(Deficiency(code="NO_HISTORICAL_MATCH", detail="closest case beyond calibrated threshold",
                                   action="expanded_historical_search", rerun=["pattern_agent"]))
        elif numeric and label and hist.get(label, 0.0) < HIST_WEAK:
            defs.append(Deficiency(code="HISTORICAL_EVIDENCE_WEAK",
                                   detail=f"only {hist.get(label, 0.0):.0%} of nearest cases support {label}",
                                   action="historical_retrieval", rerun=["pattern_agent"]))
        if label and (ex.get("margin", 1.0) < MARGIN_CONFLICT or ex.get("agents_disagree")):
            defs.append(Deficiency(code="CONFLICTING_HYPOTHESES",
                                   detail=f"margin {ex.get('margin', 0):.2f}" + ("; first-pass agents disagree" if ex.get("agents_disagree") else ""),
                                   action="hypothesis_targeted_retrieval", rerun=["diagnostic_expert"]))
        if float(stats.get("mean_top5_fused", 1.0)) < WEAK_RETRIEVAL and not stats.get("no_historical_match"):
            defs.append(Deficiency(code="WEAK_RETRIEVAL", detail=f"mean top-5 score {stats.get('mean_top5_fused', 0):.2f}",
                                   action="expanded_rerank", rerun=["pattern_agent"]))
        if prof and prof.equipment_type:
            same = sum(1 for e in state.evidence if e.content.get("equipment_type") == prof.equipment_type)
            if same < 2:
                defs.append(Deficiency(code="METADATA_EVIDENCE_MISSING",
                                       detail=f"only {same} evidence record(s) for equipment type '{prof.equipment_type}'",
                                       action="metadata_filtered_retrieval", rerun=["pattern_agent"]))
        if label and ctx.kb.has_numeric():
            miss = [s for s in critical_sensors(label, ex.get("alternative"), ctx.ref)
                    if prof and s not in prof.sensors and s not in prof.qualitative]
            if miss:
                defs.append(Deficiency(code="SENSOR_EVIDENCE_MISSING",
                                       detail=", ".join(miss) + " not reported",
                                       action="none"))   # readings that were not measured cannot be retrieved
        if ex.get("unsupported_agent_claims"):
            defs.append(Deficiency(code="UNSUPPORTED_CLAIMS", detail=f"{ex['unsupported_agent_claims']} claim(s)",
                                   action="strip_unsupported_claims"))
        return defs

    def _execute_action(self, d: Deficiency, state: DiagnosticState, ctx: AgentContext,
                        retriever: MultiStageRetriever, audit: AuditRecorder) -> Optional[Dict]:
        r = state.feedback_rounds
        prof = state.profile
        with audit.step("targeted_rag" if d.action != "strip_unsupported_claims" else "claim_validation",
                        d.action, reason=f"{d.code}: {d.detail}") as ev:
            ev.status = "loop"
            if d.action in ("historical_retrieval", "expanded_historical_search"):
                expand = 3.0 if d.action == "expanded_historical_search" else 2.5
                rr = retriever.retrieve(prof, state.data_mode, top_k=self._top_k, exclude_ids=self._excl,
                                        expand=expand, historical_k=60)
                added = self._ingest(state, rr, round_no=r, limit=4)
                self._merge_stats(state, rr, d.action, added, r, update_historical=True)
                ev.evidence_used, ev.retrieval_count = added, len(added)
                return {"evidence_ids": added}
            if d.action == "hypothesis_targeted_retrieval":
                hyps = state.analysis.get("hypotheses", [])[:2]
                added_all: List[str] = []
                for h in hyps:
                    rr = retriever.retrieve(prof, state.data_mode, top_k=3, exclude_ids=self._excl,
                                            label_filter=[h["label"]])
                    added = self._ingest(state, rr, round_no=r, limit=3)
                    self._merge_stats(state, rr, f"{d.action}:{h['label']}", added, r, update_historical=False)
                    added_all += added
                ev.evidence_used, ev.retrieval_count = added_all, len(added_all)
                return {"evidence_ids": added_all, "pair": [h["label"] for h in hyps]}
            if d.action == "expanded_rerank":
                rr = retriever.retrieve(prof, state.data_mode, top_k=self._top_k, exclude_ids=self._excl,
                                        expand=3.0, k_sem=120)
                added = self._ingest(state, rr, round_no=r, limit=4)
                self._merge_stats(state, rr, d.action, added, r, update_historical=True)
                ev.evidence_used, ev.retrieval_count = added, len(added)
                return {"evidence_ids": added}
            if d.action == "metadata_filtered_retrieval":
                rr = retriever.retrieve(prof, state.data_mode, top_k=self._top_k * 3, exclude_ids=self._excl, expand=2.0)
                rr.bundle = [c for c in rr.bundle if c.record.equipment_type == prof.equipment_type][:4]
                added = self._ingest(state, rr, round_no=r, limit=4)
                self._merge_stats(state, rr, d.action, added, r, update_historical=False)
                ev.evidence_used, ev.retrieval_count = added, len(added)
                return {"evidence_ids": added}
            if d.action == "strip_unsupported_claims":
                validator = ClaimValidator(state, ctx.known_labels)
                removed = 0
                for slot in ("diagnostic_expert_output", "pattern_output", "rapid_triage_output"):
                    rep = getattr(state, slot)
                    if not rep:
                        continue
                    rep.narrative, checks = validator.clean_text(rep.narrative, f"strip:{rep.agent}")
                    kept = []
                    for st in rep.supporting_evidence:
                        chk = validator.check_sentence(st.statement, f"strip:{rep.agent}")
                        if any(c.status == "UNSUPPORTED" for c in chk):
                            removed += 1
                        else:
                            kept.append(st)
                    rep.supporting_evidence = kept
                    removed += sum(1 for c in checks if c.action == "removed")
                    rep.claims_removed += removed
                ev.reason += f" → removed {removed}"
                return None
        return None

    # ── labels ───────────────────────────────────────────────────────────────
    @staticmethod
    def _known_labels(kb: KnowledgeBase, ref, state: DiagnosticState) -> List[str]:
        labels = list(ref.labels) if kb.has_numeric() else []
        for e in state.evidence:
            if e.label and e.label not in labels:
                labels.append(e.label)
            for it in e.content.get("relevant_items", []) or []:
                if it not in labels:
                    labels.append(it)
        return labels

    # ── response ─────────────────────────────────────────────────────────────
    def _build_response(self, state: DiagnosticState, ctx: AgentContext, kb: KnowledgeBase,
                        latency_ms: float) -> Dict[str, Any]:
        coord = state.coordinator_output
        reports = {k: getattr(state, STATE_SLOT[k]) for k in STATE_SLOT}
        conf = state.confidence.confidence if state.confidence else 0.0
        review = state.review
        requires_review = bool(review and review.decision == "REQUIRES_HUMAN_REVIEW")

        def legacy_output(key: str) -> Dict:
            rep = reports.get(key)
            meta = PERSONA_CATALOG[key]
            if not rep:
                return {**meta, "agent_confidence": 0.0, "diagnosis": "Not run", "key_findings": [], "reasoning": "",
                        "recommendation": ""}
            findings = [s.statement for s in rep.supporting_evidence[:3]] + \
                       [f"Contradicts: {s.statement}" for s in rep.contradicting_evidence[:1]] + \
                       [f"Missing: {m}" for m in rep.missing_information[:1]]
            return {**meta, "agent_confidence": max(0.0, min(1.0, float(rep.confidence))),
                    "diagnosis": rep.finding, "key_findings": findings[:5] or [rep.finding],
                    "reasoning": rep.narrative, "recommendation": rep.recommendation}

        contributions = {
            "diagnostic_expert": (reports["diagnostic_expert"].narrative if reports["diagnostic_expert"] else "N/A")[:300],
            "pattern_agent": (reports["pattern_agent"].narrative if reports["pattern_agent"] else "N/A")[:300],
            "aggressive_agent": (reports["aggressive_agent"].narrative if reports["aggressive_agent"] else "N/A")[:300],
            "verification": (reports["verification"].narrative if reports["verification"] else "N/A")[:300],
            "ambiguity": (reports["ambiguity"].narrative if reports["ambiguity"] else "N/A")[:300],
            "final_decision": state.final_diagnosis,
        }
        verification_hyps = reports["verification"].hypotheses if reports["verification"] else []
        prof = state.profile
        sensor_view = []
        if prof and ctx.kb.has_numeric():
            assess = state.analysis.get("sensor_assessment", {})
            for s, spec in SENSOR_SPECS.items():
                sensor_view.append({
                    "sensor": s, "label": spec["label"], "unit": spec["unit"],
                    "value": prof.sensors.get(s),
                    "status": ("missing" if s in prof.missing_sensors else
                               (assess.get(s, {}).get("band") if s in prof.sensors else
                                (f"reported {prof.qualitative[s]}" if s in prof.qualitative else "not reported"))),
                    "band_low": ctx.ref.band_low.get(s), "band_high": ctx.ref.band_high.get(s),
                })
        validator = ClaimValidator(state, ctx.known_labels)
        claim_summary = validator.summary()
        harness = {
            "run_id": state.run_id,
            "dataset_type": state.dataset_type,
            "data_mode": state.data_mode,
            "llm_mode": "llm+deterministic" if ctx.llm_enabled else "deterministic (no LLM configured)",
            "predicted_label": state.final_label,
            "review_decision": review.decision if review else None,
            "query_profile": prof.model_dump() if prof else {},
            "sensor_view": sensor_view,
            "evidence": [e.model_dump() for e in state.evidence],
            "evidence_composition": {"real": sum(1 for e in state.evidence if e.source_type == "real"),
                                     "synthetic": sum(1 for e in state.evidence if e.source_type == "synthetic")},
            "derived_values": [d.model_dump() for d in state.derived],
            "retrieval": {k: v for k, v in state.retrieval_stats.items()},
            "hypotheses": [{"label": h.label, "score": h.score, "evidence_ids": h.evidence_ids,
                            "supporting": [s.model_dump() for s in h.supporting],
                            "contradicting": [s.model_dump() for s in h.contradicting],
                            "missing": h.missing} for h in verification_hyps],
            "hypothesis_scores": state.analysis.get("hypotheses", [])[:8],
            "conflict_resolution": state.analysis.get("conflict_resolution"),
            "agents": {k: (r.model_dump() if r else None) for k, r in reports.items()},
            "verification": reports["verification"].extras if reports["verification"] else {},
            "ambiguity": reports["ambiguity"].extras if reports["ambiguity"] else {},
            "deficiencies_history": [[d.model_dump() for d in ds] for ds in state.deficiencies_history],
            "feedback_rounds": state.feedback_rounds,
            "confidence": state.confidence.model_dump() if state.confidence else None,
            "review": review.model_dump() if review else None,
            "claim_validation": {**claim_summary,
                                 "checks": [c.model_dump() for c in state.claim_checks
                                            if c.status == "UNSUPPORTED"][:40]},
            "timeline": [a.model_dump() for a in state.audit_trail],
            "latency_ms": round(latency_ms, 1),
            "declared_rule_thresholds": RULE_THRESHOLDS,
            "knowledge_base": {st: len(p.records) for st, p in kb.partitions.items()},
        }
        supporting = [s.statement for s in (coord.supporting_evidence if coord else [])]
        reasoning = coord.extras.get("reasoning", []) if coord else []
        result = {
            "final_diagnosis": state.final_diagnosis,
            "direct_answer": coord.extras.get("direct_answer", "") if coord else "",
            "confidence": conf,
            "reasoning": reasoning,
            "supporting_evidence": supporting,
            "agent_contributions": contributions,
            "ambiguity": requires_review,
            "review_decision": review.decision if review else "REQUIRES_HUMAN_REVIEW",
            "recommendation": coord.recommendation if coord else "",
            "dataset_used": state.dataset_type,
            "data_mode": state.data_mode,
            "retrieved_context_count": len(state.evidence),
            "agent_outputs": [legacy_output(k) for k in PERSONA_CATALOG],
            "harness": harness,
            "phase_test_results": None,
        }
        result["analysis_report"] = self._system_analysis(state, result, latency_ms)
        return result

    def _system_analysis(self, state: DiagnosticState, result: Dict, latency_ms: float) -> Dict:
        """Legacy deterministic meta-evaluation (kept for the stored-analysis dashboard)."""
        try:
            docs = [{"content": e.content_text, "score": e.retrieval_score, "metadata": {"source": e.dataset}}
                    for e in state.evidence]
            rep = lambda k: getattr(state, STATE_SLOT[k])  # noqa: E731

            def legacy(k: str) -> Dict:
                r = rep(k)
                if not r:
                    return {}
                return {"diagnosis": r.finding, "reasoning": r.narrative, "key_findings": [s.statement for s in r.supporting_evidence[:5]],
                        "confidence": r.confidence, "recommendation": r.recommendation}
            return self.system_analysis.deterministic_report(
                state.query, docs, {
                    "diagnostic_expert": legacy("diagnostic_expert"), "pattern_agent": legacy("pattern_agent"),
                    "aggressive_agent": legacy("aggressive_agent"), "verification": legacy("verification"),
                    "ambiguity": legacy("ambiguity"), "final_result": result, "latency_ms": latency_ms,
                    "retrieved_docs": docs})
        except Exception as exc:
            logger.warning("System analysis failed: %s", exc)
            return {}

    # legacy entry point -------------------------------------------------------
    async def run(self, question: str, dataset_type: str, retrieved_docs: List[Dict]) -> Dict[str, Any]:
        raise RuntimeError("AgentOrchestrator.run() was replaced by run_harness(); use services.runtime.Runtime.diagnose().")
