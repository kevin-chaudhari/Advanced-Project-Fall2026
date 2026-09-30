"""Helpers that turn deterministic analysis into evidence-cited statements."""

from __future__ import annotations

from typing import Dict, List, Optional

from harness.analysis import signature_comparison
from harness.canonical import SENSOR_SPECS, fmt_sensor
from harness.knowledge_base import ReferenceStats
from harness.schema import DiagnosticState, EvidenceStatement, Hypothesis


def derived_id(state: DiagnosticState, key: str, description: str, value: Optional[float] = None,
               text: Optional[str] = None, inputs: Optional[List[str]] = None) -> str:
    """Idempotent registration of a derived value (same key → same D-id)."""
    reg: Dict[str, str] = state.analysis.setdefault("_derived_keys", {})
    if key not in reg:
        reg[key] = state.add_derived(description, value=value, text=text, inputs=inputs)
    return reg[key]


def sensor_name(s: str) -> str:
    return SENSOR_SPECS[s]["label"].lower()


def signature_median_id(state: DiagnosticState, label: str, sensor: str, median: float) -> str:
    return derived_id(state, f"sig:{label}:{sensor}",
                      f"Median {sensor_name(sensor)} of '{label}' records in the active knowledge base",
                      value=round(median, 3), inputs=[f"knowledge-base:{state.data_mode}"])


def band_id(state: DiagnosticState, ref: ReferenceStats, sensor: str) -> str:
    lo, hi = ref.band_low[sensor], ref.band_high[sensor]
    return derived_id(state, f"band:{sensor}",
                      f"Reference band for {sensor_name(sensor)}: {fmt_sensor(sensor, lo)} – {fmt_sensor(sensor, hi)} ({ref.band_source})",
                      value=round(hi, 3), text=f"{lo:.3f}–{hi:.3f}")


def band_low_id(state: DiagnosticState, ref: ReferenceStats, sensor: str) -> str:
    return derived_id(state, f"bandlow:{sensor}", f"Lower reference band limit for {sensor_name(sensor)}",
                      value=round(ref.band_low[sensor], 3))


def build_hypothesis(state: DiagnosticState, ref: ReferenceStats, label: str, score: float,
                     max_records: int = 3) -> Hypothesis:
    prof = state.profile
    cmp = signature_comparison(label, prof, ref) if prof else {"supporting": [], "contradicting": [], "missing": []}
    support, contra, missing = [], [], []
    for it in cmp["supporting"]:
        s = it["sensor"]
        if it.get("value") is not None:
            did = signature_median_id(state, label, s, it["signature_median"])
            support.append(EvidenceStatement(
                statement=(f"Reported {sensor_name(s)} {fmt_sensor(s, it['value'])} is consistent with the {label} "
                           f"signature (median {fmt_sensor(s, it['signature_median'])}) [{did}]"),
                evidence_ids=[did]))
        else:
            support.append(EvidenceStatement(
                statement=f"Reported {it['reported']} {sensor_name(s)} matches the {it['expected']} {sensor_name(s)} expected for {label}",
                evidence_ids=[]))
    for it in cmp["contradicting"]:
        s = it["sensor"]
        if it.get("value") is not None:
            did = signature_median_id(state, label, s, it["signature_median"])
            rel = "below" if it["value"] < it["signature_median"] else "above"
            contra.append(EvidenceStatement(
                statement=(f"Reported {sensor_name(s)} {fmt_sensor(s, it['value'])} is well {rel} the {label} "
                           f"signature (median {fmt_sensor(s, it['signature_median'])}) [{did}]"),
                evidence_ids=[did]))
        else:
            contra.append(EvidenceStatement(
                statement=f"Reported {it['reported']} {sensor_name(s)} conflicts with the {it['expected']} {sensor_name(s)} expected for {label}",
                evidence_ids=[]))
    for it in cmp["missing"]:
        missing.append(f"{SENSOR_SPECS[it['sensor']]['label']} not reported — {label} is characterised by "
                       f"{it['expected']} {sensor_name(it['sensor'])}")

    recs = [e for e in state.evidence if e.label == label][:max_records]
    for e in recs:
        support.append(EvidenceStatement(
            statement=f"{e.evidence_id} ({e.source_type.upper()}) is a historical {label} case retrieved by "
                      f"{e.retrieval_method} similarity (score {e.retrieval_score:.2f})",
            evidence_ids=[e.evidence_id]))
    return Hypothesis(label=label, score=round(score, 4), evidence_ids=[e.evidence_id for e in recs],
                      supporting=support, contradicting=contra, missing=missing)
