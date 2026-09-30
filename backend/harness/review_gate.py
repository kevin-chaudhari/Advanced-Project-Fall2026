"""
Human review gate — explicit criteria, not an LLM opinion.

AUTO_RESOLVE only when every criterion passes; otherwise
REQUIRES_HUMAN_REVIEW with the failed criteria listed as reasons.
"""

from __future__ import annotations

from typing import Optional

from harness.schema import GateCriterion, ReviewGateResult

CONFIDENCE_MIN = 0.65
MARGIN_MIN = 0.15
CRITICAL_CONFIDENCE_MIN = 0.80


def evaluate_gate(*, confidence: float, margin: float, consistency_violations: int,
                  no_historical_match: bool, missing_key_sensors: int, has_sensor_data: bool,
                  final_label_supported: bool, unsupported_in_final: int,
                  severity: Optional[str], insufficient_evidence: bool) -> ReviewGateResult:
    crit = [
        GateCriterion(criterion_id="G1", description=f"Confidence ≥ {CONFIDENCE_MIN:.2f}",
                      passed=confidence >= CONFIDENCE_MIN, observed=f"{confidence:.2f}"),
        GateCriterion(criterion_id="G2", description=f"Leading hypothesis separated from runner-up by ≥ {MARGIN_MIN:.2f}",
                      passed=margin >= MARGIN_MIN, observed=f"{margin:.2f}"),
        GateCriterion(criterion_id="G3", description="No sensor consistency-rule violations",
                      passed=consistency_violations == 0, observed=str(consistency_violations)),
        GateCriterion(criterion_id="G4", description="A strong historical match exists",
                      passed=not no_historical_match, observed="no match" if no_historical_match else "match found"),
        GateCriterion(criterion_id="G5", description="No signature channel of the diagnosis is missing",
                      passed=missing_key_sensors == 0, observed=f"{missing_key_sensors} missing"),
        GateCriterion(criterion_id="G6", description="Query contains numeric sensor readings",
                      passed=has_sensor_data, observed="yes" if has_sensor_data else "no"),
        GateCriterion(criterion_id="G7", description="Final diagnosis and all final claims are evidence-backed",
                      passed=final_label_supported and unsupported_in_final == 0 and not insufficient_evidence,
                      observed=("insufficient evidence" if insufficient_evidence else
                                f"{unsupported_in_final} unsupported claim(s) removed")),
        GateCriterion(criterion_id="G8", description=f"HIGH/CRITICAL severity requires confidence ≥ {CRITICAL_CONFIDENCE_MIN:.2f}",
                      passed=not (severity in ("CRITICAL",) and confidence < CRITICAL_CONFIDENCE_MIN),
                      observed=f"severity {severity or 'n/a'}"),
    ]
    reasons = [f"{c.criterion_id}: {c.description} (observed: {c.observed})" for c in crit if not c.passed]
    return ReviewGateResult(decision="AUTO_RESOLVE" if not reasons else "REQUIRES_HUMAN_REVIEW",
                            criteria=crit, reasons=reasons)
