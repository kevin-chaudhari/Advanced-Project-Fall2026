"""
Measurable confidence (no LLM-reported percentages).

    confidence = Π factor_i ^ (w_i / 2)

Each factor lies in (0, 1] where 1 means "no reason for doubt".  Agent
agreement can only *raise* confidence when the evidence itself supports the
hypothesis — three agents agreeing on weakly supported information stays low.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from harness.schema import ConfidenceBreakdown, ConfidenceFactor

WEIGHTS = {
    "evidence_quality": 1.0,
    "hypothesis_separation": 1.0,
    "historical_similarity": 1.0,
    "data_completeness": 1.0,
    "contradictions": 1.0,
    "retrieval_quality": 0.5,
    "agent_agreement": 0.5,
}


CONFIDENCE_CEILING = 0.95


def _clip(x: float, lo: float = 0.05, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def compute_confidence(*, top_score: float, second_score: float, agreement_ratio: float,
                       retrieval_mean: float, key_present: int, key_total: int, has_sensor_data: bool,
                       n_contradicting: int, n_consistency_violations: int,
                       best_distance: Optional[float], typical_distance: Optional[float],
                       no_match_distance: Optional[float], historical_vote: Optional[float],
                       synthetic_share: float, data_mode: str) -> ConfidenceBreakdown:
    f: Dict[str, ConfidenceFactor] = {}

    ev = _clip(top_score / 0.85)
    f["evidence_quality"] = ConfidenceFactor(name="evidence_quality", value=round(ev, 3), weight=WEIGHTS["evidence_quality"],
        explanation=f"top hypothesis evidence score {top_score:.2f} (full credit at ≥ 0.85)")

    sep = _clip((top_score - second_score) / 0.30, 0.1)
    f["hypothesis_separation"] = ConfidenceFactor(name="hypothesis_separation", value=round(sep, 3),
        weight=WEIGHTS["hypothesis_separation"],
        explanation=f"margin to runner-up {top_score - second_score:.2f} (full credit at ≥ 0.30)")

    if best_distance is not None and typical_distance is not None and no_match_distance:
        span = max(no_match_distance - typical_distance, 1e-6)
        sim = _clip(1.0 - max(best_distance - typical_distance, 0.0) / span, 0.05)
        vote = historical_vote if historical_vote is not None else 0.5
        hist = _clip(sim * (0.5 + 0.5 * vote))
        expl = (f"nearest case distance {best_distance:.2f} (typical {typical_distance:.2f}, "
                f"no-match ≥ {no_match_distance:.2f}); {vote:.0%} of nearest cases share the label")
    else:
        hist = 0.5
        expl = "no numeric readings — historical similarity could not be measured"
    f["historical_similarity"] = ConfidenceFactor(name="historical_similarity", value=round(hist, 3),
                                                  weight=WEIGHTS["historical_similarity"], explanation=expl)

    if not has_sensor_data:
        comp, expl = 0.3, "no numeric sensor readings in the query"
    elif key_total:
        comp = _clip(0.3 + 0.7 * key_present / key_total, 0.3)
        expl = f"{key_present}/{key_total} signature channels of the leading hypothesis were reported"
    else:
        comp, expl = 0.8, "leading hypothesis has no distinctive signature channels"
    f["data_completeness"] = ConfidenceFactor(name="data_completeness", value=round(comp, 3),
                                              weight=WEIGHTS["data_completeness"], explanation=expl)

    con = _clip(1.0 - 0.15 * n_contradicting - 0.35 * n_consistency_violations, 0.2)
    f["contradictions"] = ConfidenceFactor(name="contradictions", value=round(con, 3), weight=WEIGHTS["contradictions"],
        explanation=f"{n_contradicting} contradicting signal(s), {n_consistency_violations} consistency-rule violation(s)")

    rq = _clip(retrieval_mean / 0.55, 0.1)
    f["retrieval_quality"] = ConfidenceFactor(name="retrieval_quality", value=round(rq, 3), weight=WEIGHTS["retrieval_quality"],
        explanation=f"mean fused score of top-5 evidence {retrieval_mean:.2f} (full credit at ≥ 0.55)")

    if ev >= 0.6:
        ag = 0.8 + 0.2 * agreement_ratio
        expl = f"{agreement_ratio:.0%} of first-pass agents agree with the verified hypothesis"
    else:
        ag = 0.8
        expl = "agreement ignored: evidence for the hypothesis is weak (agreement ≠ truth)"
    f["agent_agreement"] = ConfidenceFactor(name="agent_agreement", value=round(ag, 3), weight=WEIGHTS["agent_agreement"],
                                            explanation=expl)

    conf = 1.0
    for fac in f.values():
        conf *= fac.value ** (fac.weight / 2.0)

    factors: List[ConfidenceFactor] = list(f.values())
    if data_mode == "combined" and synthetic_share > 0.7:
        pen = 0.9
        conf *= pen
        factors.append(ConfidenceFactor(name="synthetic_reliance", value=pen, weight=2.0,
            explanation=f"{synthetic_share:.0%} of supporting evidence is SYNTHETIC — synthetic data never increases confidence"))
    conf = round(max(0.0, min(CONFIDENCE_CEILING, conf)), 3)
    return ConfidenceBreakdown(confidence=conf, factors=factors,
                               formula=(f"confidence = min({CONFIDENCE_CEILING}, Π factorᵢ^(wᵢ/2))  "
                                        "(each factor ∈ (0,1], 1 = no reason for doubt; the ceiling reflects that "
                                        "a remote, data-only diagnosis is never certain)"))
