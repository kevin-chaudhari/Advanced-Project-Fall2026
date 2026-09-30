"""
Human Review Coordinator — Director Sarah Mitchell

Two responsibilities (still one agent):

1. Final coordinator — composes the operator-facing answer strictly from the
   verified state: the verified label, cited evidence (EV/D IDs), measured
   confidence and the ambiguity flags.  Optional LLM wording is claim-validated.
2. Human review gate — applies the explicit criteria in harness.review_gate and
   returns AUTO_RESOLVE or REQUIRES_HUMAN_REVIEW.  It is not an LLM opinion.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agents.base_agent import AgentContext, BaseAgent
from harness.claims import ClaimValidator
from harness.review_gate import evaluate_gate
from harness.rules import guidance_for
from harness.schema import AgentReport, DiagnosticState, EvidenceStatement

PERSONA_NAME = "Director Sarah Mitchell"
PERSONA_EMOJI = "🏁"


class HumanReviewCoordinatorAgent(BaseAgent):
    key = "human_review_coordinator"

    @property
    def role(self) -> str:
        return "Human Review Coordinator"

    @property
    def goal(self) -> str:
        return "Compose the evidence-grounded final answer and apply the explicit human-review gate."

    def deterministic(self, state: DiagnosticState, ctx: AgentContext, **_) -> AgentReport:
        ver, amb = state.verification_output, state.ambiguity_output
        prof = state.profile
        stats = state.retrieval_stats
        scored = state.analysis.get("hypotheses", [])
        label: Optional[str] = ver.finding_label if ver else None
        alt = (ver.extras.get("alternative") if ver else None)
        margin = float(ver.extras.get("margin", 0.0)) if ver else 0.0
        conf = state.confidence.confidence if state.confidence else 0.0
        top_score = scored[0]["score"] if scored else 0.0
        has_sensor = bool(prof and prof.sensors)
        numeric_kb = ctx.kb.has_numeric()
        violations = (amb.extras.get("consistency_violations") if amb else []) or []

        reasons_insufficient: List[str] = []
        if numeric_kb and not has_sensor and not (prof and prof.qualitative):
            reasons_insufficient.append("no sensor readings for the asset were provided")
        if stats.get("no_historical_match"):
            reasons_insufficient.append("no strong historical match exists in the knowledge base")
        relevance_kb = state.dataset_type == "failure_iq"
        if not label or (top_score < 0.2 and not relevance_kb):
            reasons_insufficient.append("no hypothesis has meaningful evidence support")
        insufficient = bool(reasons_insufficient)
        final_label = "Insufficient Evidence" if insufficient else label

        # ── compose text (deterministic, citation-bearing) ───────────────────
        best_ids = (ver.evidence_ids[:3] if ver else [])
        cite = f" [{', '.join(best_ids)}]" if best_ids else ""
        if insufficient:
            diag = f"Insufficient evidence for a reliable diagnosis: {'; '.join(reasons_insufficient)}."
            if label and top_score >= 0.2:
                diag += f" Leading hypothesis, for reference only: {label} (evidence score {top_score:.2f})."
            direct = diag
        elif relevance_kb:
            top3 = scored[:3]
            parts = []
            for h in top3:
                ids = [e.evidence_id for e in state.evidence
                       if h["label"] == e.content.get("anchor") or h["label"] in (e.content.get("relevant_items") or [])][:2]
                parts.append(f"{h['label']} ({h['score']:.0%}{', ' + ', '.join(ids) if ids else ''})")
            diag = ("Failure events most associated with the described symptom in the sensor-relevance knowledge base: "
                    + "; ".join(parts) + ". This ranks candidate events; it is not a diagnosis of a specific asset.")
            direct = f"The most associated failure event is {label}."
        elif label == "Normal Operation":
            diag = f"Normal Operation — the reported readings match healthy operating records{cite} (confidence {conf:.0%})."
            direct = "No fault is indicated by the reported readings."
        elif ver and ver.extras.get("verified_label") and margin < 0.15 and alt:
            diag = (f"Most likely {label}{cite}, but {alt} remains plausible (evidence margin {margin:.2f}); "
                    f"confidence {conf:.0%}.")
            direct = f"The readings are most consistent with {label}, with {alt} as a close alternative."
        else:
            diag = f"{label} — the diagnosis best supported by the retrieved evidence{cite} (confidence {conf:.0%})."
            direct = f"The readings are most consistent with {label}."
        if violations and label != "Sensor Malfunction" and not insufficient:
            diag += " Note: some readings violate sensor-consistency rules; verify instrumentation."

        reasoning = self._reasoning(state)
        support = [s for s in (ver.supporting_evidence if ver else []) if s.evidence_ids][:5]
        contra = (ver.contradicting_evidence if ver else [])[:4]
        if insufficient and not support:
            support = [s for s in (state.pattern_output.contradicting_evidence if state.pattern_output else []) if s.evidence_ids][:3]

        # ── claim validation of the final text ───────────────────────────────
        validator = ClaimValidator(state, ctx.known_labels)
        before = sum(1 for c in state.claim_checks if c.action == "removed")
        diag, _ = validator.clean_text(diag, "final:diagnosis")
        direct, _ = validator.clean_text(direct, "final:direct_answer")
        reasoning, _ = validator.clean_list(reasoning, "final:reasoning")
        kept_support, _ = validator.clean_list([s.statement for s in support], "final:supporting_evidence")
        support = [s for s in support if s.statement in kept_support]
        removed_final = sum(1 for c in state.claim_checks if c.action == "removed") - before

        # ── explicit gate ────────────────────────────────────────────────────
        severity = state.rapid_triage_output.extras.get("severity") if state.rapid_triage_output else None
        gate = evaluate_gate(
            confidence=conf, margin=margin, consistency_violations=len(violations),
            no_historical_match=bool(stats.get("no_historical_match")),
            missing_key_sensors=len(amb.extras.get("missing_key_sensors", [])) if amb else 0,
            has_sensor_data=has_sensor or not numeric_kb, final_label_supported=validator.label_supported(final_label),
            unsupported_in_final=removed_final, severity=severity, insufficient_evidence=insufficient)
        state.review = gate
        state.final_label = final_label
        state.final_diagnosis = diag

        recommendation = guidance_for(label if not insufficient else None)
        if gate.decision == "REQUIRES_HUMAN_REVIEW":
            recommendation = "Human review required before acting. " + recommendation
        return AgentReport(agent=self.key, display_name=self.role, finding=diag, finding_label=final_label,
                           evidence_ids=[i for s in support for i in s.evidence_ids],
                           supporting_evidence=support, contradicting_evidence=contra,
                           missing_information=(amb.missing_information if amb else []),
                           confidence=conf, narrative=direct, recommendation=recommendation,
                           claims_removed=removed_final,
                           extras={"direct_answer": direct, "reasoning": reasoning, "decision": gate.decision,
                                   "insufficient_evidence": insufficient, "insufficient_reasons": reasons_insufficient})

    def _reasoning(self, state: DiagnosticState) -> List[str]:
        prof = state.profile
        steps: List[str] = []
        ch = ", ".join(sorted(prof.sensors)) if prof and prof.sensors else "none"
        steps.append(f"Query preparation — numeric channels reported: {ch}"
                     + (f"; explicitly unavailable: {', '.join(prof.missing_sensors)}" if prof and prof.missing_sensors else "")
                     + (f"; directional cues: {', '.join(f'{k} {v}' for k, v in prof.qualitative.items())}" if prof and prof.qualitative else "") + ".")
        comp = state.retrieval_stats.get("source_composition", {})
        steps.append(f"Multi-stage retrieval ({state.retrieval_stats.get('scheme', 'text')} scheme) produced "
                     f"{len(state.evidence)} evidence records ({comp.get('real', 0)} REAL, {comp.get('synthetic', 0)} SYNTHETIC).")
        for rep, name in ((state.diagnostic_expert_output, "Diagnostic Expert"), (state.pattern_output, "Pattern Recognition"),
                          (state.rapid_triage_output, "Rapid Triage")):
            if rep:
                ids = f" [{', '.join(rep.evidence_ids[:3])}]" if rep.evidence_ids else ""
                steps.append(f"{name} (pass {rep.pass_number}) — {rep.finding}{ids}.")
        if state.feedback_rounds:
            codes = sorted({d.code for ds in state.deficiencies_history for d in ds if d.action != "none"})
            steps.append(f"Feedback loop — {state.feedback_rounds} targeted round(s) addressing {', '.join(codes)}.")
        if state.verification_output:
            steps.append(f"Verification — {state.verification_output.narrative}")
        if state.ambiguity_output:
            steps.append(f"Ambiguity — {state.ambiguity_output.narrative}")
        return [f"Step {i + 1}: {s}" for i, s in enumerate(steps)]

    def llm_task(self, state, ctx, report, **_):
        return ("Rewrite the direct answer for a plant operator in <= 2 sentences, keeping the verified label, "
                "the confidence and the review decision unchanged. Return JSON {\"direct_answer\": str}. "
                f"Verified label: {report.finding_label}. Decision: {state.review.decision if state.review else ''}.")

    def merge_llm(self, state, ctx, report, data: Dict[str, Any]) -> AgentReport:
        text = str(data.get("direct_answer") or "")
        if not text:
            return report
        validator = ClaimValidator(state, ctx.known_labels)
        clean, checks = validator.clean_text(text, "final:direct_answer:llm")
        removed = sum(1 for c in checks if c.action == "removed")
        if removed == 0 and report.finding_label and (report.finding_label.lower() in clean.lower()
                                                      or report.finding_label == "Insufficient Evidence"):
            report.narrative = clean
            report.extras["direct_answer"] = clean
            report.mode = "llm+deterministic"
        else:
            report.claims_removed += removed
        return report
