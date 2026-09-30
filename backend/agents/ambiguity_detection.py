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

    def llm_task(self, state, ctx, report, **_):
        return ("Summarise the uncertainty for an operator in 2-3 sentences. Return JSON {\"narrative\": str}. "
                "Do not introduce new numbers; refer to evidence IDs where relevant.")
