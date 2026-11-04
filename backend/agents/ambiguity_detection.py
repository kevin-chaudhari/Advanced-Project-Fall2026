"""
Ambiguity Detection Agent — Dr. Sofia Nakamura  (primary uncertainty evaluator)

Evaluates, from measurable signals only:
  insufficient evidence · conflicting evidence · low-quality / inconsistent data ·
  weak retrieval · multiple plausible diagnoses · missing sensor information ·
  unsupported / untraceable claims made by earlier agents · synthetic reliance

and computes the factor-based confidence breakdown (no LLM-reported %).
"""

from __future__ import annotations

from typing import List

from agents.base_agent import AgentContext, BaseAgent
from harness.analysis import critical_sensors, key_sensors
from harness.confidence import compute_confidence
from harness.rules import check_consistency
from harness.schema import AgentReport, DiagnosticState, EvidenceStatement

PERSONA_NAME = "Dr. Sofia Nakamura"
PERSONA_EMOJI = "🎯"


class AmbiguityDetectionAgent(BaseAgent):
    key = "ambiguity"

    @property
    def role(self) -> str:
        return "Ambiguity Detection Agent"

    @property
    def goal(self) -> str:
        return "Identify every measurable source of uncertainty and quantify confidence from explicit factors."

    def deterministic(self, state: DiagnosticState, ctx: AgentContext, **_) -> AgentReport:
        ver = state.verification_output
        prof = state.profile
        stats = state.retrieval_stats
        scored = state.analysis.get("hypotheses", [])
        top = scored[0]["score"] if scored else 0.0
        second = scored[1]["score"] if len(scored) > 1 else 0.0
        if state.collab.get("score_delta"):        # evidence confidence uses evidence scores; the council enters via the blend
            from harness.collaboration import evidence_scores
            ev = evidence_scores(state)
            lead = ver.finding_label if ver and ver.finding_label in ev else (scored[0]["label"] if scored else None)
            if lead:
                top = ev[lead]
                second = max([v for l, v in ev.items() if l != lead] or [0.0])
        label = ver.finding_label if ver else (scored[0]["label"] if scored else None)
        extras = ver.extras if ver else {}

        violations = check_consistency(prof.sensors) if prof else []
        alt = extras.get("alternative")
        ks = critical_sensors(label, alt, ctx.ref) if label else []
        present = sum(1 for s in ks if prof and (s in prof.sensors or s in prof.qualitative))
        missing_key = [s for s in ks if prof and s not in prof.sensors and s not in prof.qualitative]
        synth = [e for e in state.evidence if e.source_type == "synthetic"]
        synth_share = len(synth) / len(state.evidence) if state.evidence else 0.0
        hist = stats.get("historical_support") or {}

        breakdown = compute_confidence(
            top_score=top, second_score=second, agreement_ratio=float(extras.get("agreement_ratio", 0.0)),
            retrieval_mean=float(stats.get("mean_top5_fused", 0.0)), key_present=present, key_total=len(ks),
            has_sensor_data=bool(prof and prof.sensors), n_contradicting=len(state.contradictions),
            n_consistency_violations=len(violations), best_distance=stats.get("best_numeric_distance"),
            typical_distance=stats.get("typical_nn_distance"), no_match_distance=stats.get("no_match_threshold"),
            historical_vote=hist.get(label) if hist and label else None, synthetic_share=synth_share,
            data_mode=state.data_mode)
        self._blend_council(state, breakdown)
        state.confidence = breakdown

        flags: List[EvidenceStatement] = []

        def flag(kind: str, text: str, ids=None):
            flags.append(EvidenceStatement(statement=f"{kind}: {text}", evidence_ids=ids or []))

        if not prof or (not prof.sensors and not prof.qualitative):
            flag("INSUFFICIENT_EVIDENCE", "no sensor readings were provided for the asset")
        elif not prof.sensors:
            flag("INSUFFICIENT_EVIDENCE", "only directional cues (no numeric readings) were provided")
        if top - second < 0.15 and len(scored) > 1:
            flag("MULTIPLE_PLAUSIBLE_DIAGNOSES", f"{scored[0]['label']} vs {scored[1]['label']} are separated by only {top - second:.2f}")
        if state.contradictions:
            flag("CONFLICTING_EVIDENCE", f"{len(state.contradictions)} signal(s) contradict the leading hypothesis",
                 [i for c in state.contradictions for i in c.evidence_ids][:4])
        if violations:
            flag("LOW_QUALITY_DATA", "; ".join(f"{v['rule_id']} {v['description']}" for v in violations))
        if missing_key:
            flag("MISSING_SENSOR_INFORMATION", ", ".join(missing_key) + f" not reported (channels needed to confirm {label}"
                 + (f" vs {alt})" if alt else ")"))
        if stats.get("no_historical_match"):
            flag("WEAK_RETRIEVAL", "no strong historical match — closest case beyond calibrated threshold")
        elif float(stats.get("mean_top5_fused", 0)) < 0.3:
            flag("WEAK_RETRIEVAL", f"low mean retrieval score {float(stats.get('mean_top5_fused', 0)):.2f}")
        if extras.get("unsupported_agent_claims"):
            flag("UNSUPPORTED_CLAIMS", f"{extras['unsupported_agent_claims']} earlier-agent claim(s) could not be traced to evidence")
        if extras.get("agreement_without_evidence"):
            flag("AGREEMENT_WITHOUT_EVIDENCE", "agents agree but the evidence score is low")
        if state.data_mode == "combined" and synth_share > 0.7:
            flag("SYNTHETIC_RELIANCE", f"{synth_share:.0%} of evidence records are SYNTHETIC")

        n = len(flags)
        level = "HIGH" if (n >= 3 or breakdown.confidence < 0.45) else ("MODERATE" if n >= 1 or breakdown.confidence < 0.65 else "LOW")
        narrative = (f"Ambiguity level {level}; measured confidence {breakdown.confidence:.2f}. "
                     + ("Uncertainty sources: " + "; ".join(f.statement.split(':')[0] for f in flags) + "."
                        if flags else "No material uncertainty source detected."))
        return AgentReport(agent=self.key, display_name=self.role, finding=f"Ambiguity {level}",
                           finding_label=label, supporting_evidence=flags,
                           missing_information=[f"{s} not reported" for s in missing_key],
                           confidence=breakdown.confidence, narrative=narrative,
                           recommendation=("Route to human review." if level != "LOW" else "Uncertainty acceptable."),
                           extras={"ambiguity_level": level, "flags": [f.statement for f in flags],
                                   "missing_key_sensors": missing_key, "consistency_violations": violations,
                                   "synthetic_share": round(synth_share, 3)})

    # ── collaborative council: blend the agents' confidence, capped by the evidence ──
    @staticmethod
    def _blend_council(state: DiagnosticState, breakdown) -> None:
        """final = min(evidence, (1−β)·evidence + β·council). The council can lower confidence when the
        agents remain split or unsure; it can never lift it above what the evidence factors support."""
        from harness.collaboration import collab_enabled, conf_weight
        from harness.schema import ConfidenceFactor
        c = state.collab.get("council_confidence")
        e = breakdown.confidence
        breakdown.evidence_confidence = e
        if c is None or not collab_enabled():
            return
        b = conf_weight()
        final = round(min(e, (1 - b) * e + b * c), 3)
        from harness.agent_trace.trace_manager import record_score_change
        record_score_change(state, "council_confidence_blend", {"confidence": e}, {"confidence": final},
                            actor="ambiguity", quantity="confidence", parameters={
                                "evidence_confidence": e, "council_confidence": c, "beta": b,
                                "uncapped": round((1 - b) * e + b * c, 6), "capped_by_evidence": final < round((1 - b) * e + b * c, 3),
                                "formula": "final = min(evidence, (1−β)·evidence + β·council)",
                                "joint_label": state.collab.get("joint_label")})
        breakdown.council_confidence = c
        breakdown.factors.append(ConfidenceFactor(
            name="council_agreement", value=round(c, 3), weight=b,
            explanation=(f"agents' agreed confidence in {state.collab.get('joint_label')} after "
                         f"{state.collab.get('rounds', 0)} collaboration round(s)"
                         + (f"; dissent: {', '.join(state.collab.get('dissent') or [])}" if state.collab.get('dissent') else "")
                         + f"; blended with the evidence confidence {e:.2f} and capped by it")))
        breakdown.formula += (f"  then  final = min(evidence, (1−{b:g})·evidence + {b:g}·council)  "
                              "(the council can lower, never raise, the evidence confidence)")
        breakdown.confidence = final

    # ── uncertainty flags to the coordinator ────────────────────────────────
    def exchange_flags(self, state: DiagnosticState, ctx: AgentContext, round_no: int):
        """Post each measured uncertainty source once (re-runs only add new ones). The flag text and IDs are
        the statements this agent already produced; nothing is re-measured here."""
        rep = state.ambiguity_output
        if not rep:
            return []
        done = {m.payload.get("flag") for m in state.messages if m.sender == self.key and m.kind == "UNCERTAINTY_FLAG"}
        posted = []
        for st in rep.supporting_evidence:
            kind = st.statement.split(":")[0].strip()
            if not kind or kind in done:
                continue
            done.add(kind)
            posted.append(state.post(round=round_no, sender=self.key, kind="UNCERTAINTY_FLAG",
                                     recipients=["human_review_coordinator", "verification"], topic=kind,
                                     text=st.statement, evidence_ids=st.evidence_ids,
                                     payload={"flag": kind, "ambiguity_level": rep.extras.get("ambiguity_level"),
                                              "confidence": rep.confidence}))
        return posted

    # ── council: open the agenda ──────────────────────────────────────────
    def deliberate(self, state: DiagnosticState, ctx: AgentContext, round_no: int, tools=None):
        """Turn each measured uncertainty source into a question for the agent that owns it.

        Persona: the uncertainty specialist does not answer the questions herself;
        she routes them, and anything agents cannot resolve goes to a person.
        """
        from harness.council import contested_pair
        rep = state.ambiguity_output
        if not rep:
            return []
        kinds = {f.split(":")[0] for f in rep.extras.get("flags", [])}
        pair = contested_pair(state)
        posted = []
        asked = {(m.payload.get("need"), tuple(m.payload.get("pair") or ())) for m in state.messages
                 if m.sender == self.key and m.phase == "council"}      # collaboration questions do not count here

        def new_q(need, p=None):
            return (need, tuple(p or ())) not in asked
        if "MULTIPLE_PLAUSIBLE_DIAGNOSES" in kinds and pair and new_q("separate", pair):
            a, b = pair
            posted.append(state.post(round=round_no, sender=self.key, kind="QUESTION",
                                     recipients=["diagnostic_expert", "pattern_agent"], topic=f"{a} vs {b}",
                                     text=f"{a} and {b} are too close to call. Which reported channels separate them, "
                                          f"and what does precedent on those channels say?",
                                     payload={"need": "separate", "pair": [a, b]}))
        elif pair and state.confidence and state.confidence.confidence < 0.65 and new_q("separate", pair):
            a, b = pair
            weakest = min(state.confidence.factors, key=lambda f: f.value) if state.confidence.factors else None
            posted.append(state.post(round=round_no, sender=self.key, kind="QUESTION",
                                     recipients=["diagnostic_expert", "pattern_agent"], topic=f"{a} vs {b}",
                                     text=(f"Confidence is only {state.confidence.confidence:.2f}"
                                           + (f" (weakest factor: {weakest.name.replace('_', ' ')})" if weakest else "")
                                           + f". Does the evidence on the separating channels confirm {a} over {b}?"),
                                     payload={"need": "separate", "pair": [a, b]}))
        if "CONFLICTING_EVIDENCE" in kinds and new_q("contradiction_review"):
            ids = [i for c in state.contradictions for i in c.evidence_ids][:4]
            posted.append(state.post(round=round_no, sender=self.key, kind="QUESTION", recipients=["verification"],
                                     topic="contradicting signals", evidence_ids=ids,
                                     text=f"{len(state.contradictions)} signal(s) contradict the leading hypothesis. "
                                          f"Do they count against the runner-up as well?",
                                     payload={"need": "contradiction_review"}))
        if "SYNTHETIC_RELIANCE" in kinds and pair and new_q("real_precedent", pair):
            posted.append(state.post(round=round_no, sender=self.key, kind="QUESTION", recipients=["pattern_agent"],
                                     topic="REAL precedent", text="Most evidence is SYNTHETIC. What do REAL cases alone say?",
                                     payload={"need": "real_precedent", "pair": list(pair)}))
        if "LOW_QUALITY_DATA" in kinds and new_q("instrumentation"):
            posted.append(state.post(round=round_no, sender=self.key, kind="QUESTION", recipients=["aggressive_agent"],
                                     topic="instrumentation", text="Readings break a consistency rule. Is the instrumentation trustworthy?",
                                     payload={"need": "instrumentation"}))
        if "AGREEMENT_WITHOUT_EVIDENCE" in kinds and new_q("agreement_check"):
            posted.append(state.post(round=round_no, sender=self.key, kind="QUESTION", recipients=["verification"],
                                     topic="agreement", text="The agents agree but the evidence score is low. Is the agreement backed by evidence?",
                                     payload={"need": "agreement_check"}))
        missing = rep.extras.get("missing_key_sensors", [])
        first = state.council.get("first_round", 1)
        if missing and round_no == first:
            posted.append(state.post(round=round_no, sender=self.key, kind="HUMAN_INPUT_REQUEST",
                                     recipients=["human_review_coordinator"], topic="missing channels",
                                     text="No agent can recover unmeasured channels: " + ", ".join(missing)
                                          + " must be measured on the asset.",
                                     payload={"channels": missing}))
        if "INSUFFICIENT_EVIDENCE" in kinds and round_no == first:
            posted.append(state.post(round=round_no, sender=self.key, kind="HUMAN_INPUT_REQUEST",
                                     recipients=["human_review_coordinator"], topic="readings",
                                     text="The question carries too few numeric readings for the agents to settle this.",
                                     payload={"channels": []}))
        return posted

    def llm_task(self, state, ctx, report, **_):
        return ("Summarise the uncertainty for an operator in 2-3 sentences. Return JSON {\"narrative\": str}. "
                "Do not introduce new numbers; refer to evidence IDs where relevant.")
