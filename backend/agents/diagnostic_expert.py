"""
Diagnostic Expert Agent — Dr. Elena Vasquez

Generates multiple failure hypotheses, cites the evidence for and against each,
lists missing evidence and deliberately keeps runner-up hypotheses alive
instead of accepting the first idea.

Pass 1 : hypotheses from the evidence engine (kNN vote + signature fit).
Pass 2 : (only when the orchestrator detects conflicting hypotheses) re-scores
         the two leading hypotheses on the sensors that actually discriminate
         between them, using targeted evidence retrieved for that conflict.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from agents.base_agent import AgentContext, BaseAgent
from harness.analysis import discriminating_sensors
from harness.canonical import fmt_sensor
from harness.claims import ClaimValidator
from harness.schema import AgentReport, DiagnosticState, EvidenceStatement
from harness.statements import build_hypothesis, sensor_name, signature_median_id

PERSONA_NAME = "Dr. Elena Vasquez"
PERSONA_EMOJI = "🧠"


class DiagnosticExpertAgent(BaseAgent):
    key = "diagnostic_expert"

    @property
    def role(self) -> str:
        return "Diagnostic Expert"

    @property
    def goal(self) -> str:
        return ("Generate several competing failure hypotheses, cite supporting and contradicting evidence "
                "for each, and name the evidence that is missing.")

    def deterministic(self, state: DiagnosticState, ctx: AgentContext, conflict: Dict | None = None, **_) -> AgentReport:
        scored = list(state.analysis.get("hypotheses", []))
        if not scored:
            return AgentReport(agent=self.key, display_name=self.role, finding="No hypothesis could be formed",
                               missing_information=["No usable evidence was retrieved"], confidence=0.0,
                               narrative="No evidence was available to form hypotheses.")
        pass_no = 1
        notes: List[str] = []
        if conflict and len(scored) >= 2:
            scored, notes = self._resolve_conflict(state, ctx, scored, conflict)
            pass_no = 2
        top = scored[:3] if len(scored) >= 3 else scored
        hyps = [build_hypothesis(state, ctx.ref, h["label"], h["score"]) for h in top]
        lead = hyps[0]
        missing = [m for h in hyps[:2] for m in h.missing]
        runner = hyps[1] if len(hyps) > 1 else None
        narrative = [f"Evaluated {len(hyps)} competing hypotheses."]
        narrative.append(f"Leading hypothesis: {lead.label} (evidence score {lead.score:.2f}; "
                         f"{len(lead.supporting)} supporting, {len(lead.contradicting)} contradicting items).")
        if runner:
            narrative.append(f"{runner.label} is kept as an alternative (score {runner.score:.2f}) rather than discarded.")
        narrative.extend(notes)
        if missing:
            narrative.append(f"Missing evidence: {len(missing)} signature channel(s) not reported.")
        return AgentReport(
            agent=self.key, display_name=self.role, finding=lead.label, finding_label=lead.label,
            hypotheses=hyps, evidence_ids=lead.evidence_ids,
            supporting_evidence=lead.supporting[:6], contradicting_evidence=lead.contradicting[:6],
            missing_information=missing[:6], confidence=lead.score,
            narrative=" ".join(narrative), recommendation="Validate the leading hypothesis against the channels listed as missing or contradicting.",
            pass_number=pass_no, extras={"scores": [{"label": h["label"], "score": h["score"]} for h in scored[:5]]})

    def _resolve_conflict(self, state: DiagnosticState, ctx: AgentContext, scored: List[Dict], conflict: Dict):
        a, b = scored[0]["label"], scored[1]["label"]
        disc = discriminating_sensors(a, b, ctx.ref, top=3)
        prof = state.profile
        notes, fa, fb = [], 0.0, 0.0
        for d in disc:
            s = d["sensor"]
            if s not in prof.sensors:
                notes.append(f"Discriminating channel {sensor_name(s)} is not reported, so {a} vs {b} cannot be separated on it.")
                continue
            v = prof.sensors[s]
            sa, sb = ctx.ref.signatures[a], ctx.ref.signatures[b]
            za = abs(v - sa["median"][s]) / sa["scale"][s]
            zb = abs(v - sb["median"][s]) / sb["scale"][s]
            fa += math.exp(-0.5 * za * za)
            fb += math.exp(-0.5 * zb * zb)
            ida = signature_median_id(state, a, s, sa["median"][s])
            idb = signature_median_id(state, b, s, sb["median"][s])
            closer = a if za < zb else b
            notes.append(f"Discriminating channel {sensor_name(s)}: reported {fmt_sensor(s, v)} is closer to {closer} "
                         f"({a} median {fmt_sensor(s, sa['median'][s])} [{ida}], {b} median {fmt_sensor(s, sb['median'][s])} [{idb}]).")
        targeted = conflict.get("evidence_ids", [])
        if targeted:
            notes.append(f"Targeted conflict evidence reviewed: {', '.join(targeted[:6])}.")
        if fa + fb > 0:
            pair_total = scored[0]["score"] + scored[1]["score"]
            share_a = fa / (fa + fb)
            new_a = 0.5 * scored[0]["score"] + 0.5 * pair_total * share_a
            new_b = 0.5 * scored[1]["score"] + 0.5 * pair_total * (1 - share_a)
            rescored = [dict(scored[0], score=round(new_a, 4)), dict(scored[1], score=round(new_b, 4))] + scored[2:]
            rescored.sort(key=lambda r: -r["score"])
            state.analysis["hypotheses"] = rescored
            state.analysis["conflict_resolution"] = {"pair": [a, b], "discriminating": disc,
                                                     "pairwise_share": {a: round(share_a, 3), b: round(1 - share_a, 3)}}
            return rescored, notes
        return scored, notes

    def llm_task(self, state, ctx, report, **_):
        return ("Review the draft. Return JSON {\"hypotheses\": [{\"label\": str, \"supporting\": [{\"statement\": str, "
                "\"evidence_ids\": [..]}], \"contradicting\": [...], \"missing\": [str]}], \"narrative\": str}. "
                "Keep at least two hypotheses. Do not invent readings.")

    def merge_llm(self, state, ctx, report, data: Dict[str, Any]) -> AgentReport:
        report = super().merge_llm(state, ctx, report, data)
        validator = ClaimValidator(state, ctx.known_labels)
        by_label = {h.label: h for h in report.hypotheses}
        for h in data.get("hypotheses") or []:
            if not isinstance(h, dict):
                continue
            lab = str(h.get("label", ""))
            if lab not in by_label:
                if not validator.label_supported(lab):
                    report.claims_removed += 1
                continue
            for kind in ("supporting", "contradicting"):
                for st in self._statements(h.get(kind), state):
                    chk = validator.check_sentence(st.statement, f"{self.key}:llm")
                    state.claim_checks.extend(chk)
                    if st.evidence_ids and not any(c.status == "UNSUPPORTED" for c in chk):
                        getattr(by_label[lab], kind).append(st)
                    else:
                        report.claims_removed += 1
        return report
