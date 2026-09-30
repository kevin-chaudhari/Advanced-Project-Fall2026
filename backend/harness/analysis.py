"""
Deterministic numerical analysis used by the agents (no LLM).

These functions are the "numerical analysis instead of another LLM agent"
part of the harness: hypothesis scoring, signature comparison, discriminating
sensors and anomaly flags are all computed from the knowledge-base statistics
and the user's actual readings.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from harness.canonical import SENSORS, SENSOR_SPECS, fmt_sensor
from harness.knowledge_base import ReferenceStats
from harness.rules import band_flags
from harness.schema import QueryProfile

KEY_SENSOR_THRESHOLD = 0.75     # |signature median − population median| / scale


def sensor_assessment(profile: QueryProfile, ref: ReferenceStats) -> Dict[str, Dict]:
    flags = band_flags(profile.sensors, ref.band_low, ref.band_high)
    out = {}
    for s, v in profile.sensors.items():
        z = (v - ref.center[s]) / ref.scale[s]
        out[s] = {"value": v, "z": round(float(z), 2), "band": flags.get(s, "unknown"),
                  "band_low": ref.band_low.get(s), "band_high": ref.band_high.get(s),
                  "weight": ref.weights.get(s, 0.0)}
    return out


def key_sensors(label: str, ref: ReferenceStats) -> List[Tuple[str, float]]:
    """Sensors that characterise a label's signature (direction-signed deviation)."""
    sig = ref.signatures.get(label)
    if not sig:
        return []
    out = []
    for s in SENSORS:
        med = sig["median"].get(s)
        if med is None or med != med:
            continue
        dev = (med - ref.center[s]) / ref.scale[s]
        if abs(dev) >= KEY_SENSOR_THRESHOLD and ref.weights.get(s, 0) >= 0.05:
            out.append((s, float(dev)))
    return sorted(out, key=lambda t: -abs(t[1]) * ref.weights.get(t[0], 0))


def centroid_fit(label: str, profile: QueryProfile, ref: ReferenceStats) -> Optional[float]:
    sig = ref.signatures.get(label)
    if not sig or not profile.sensors:
        return None
    num = den = 0.0
    for s, v in profile.sensors.items():
        med, sc = sig["median"].get(s), sig["scale"].get(s)
        if med is None or med != med or not sc:
            continue
        w = ref.weights.get(s, 0.0)
        num += w * ((v - med) / sc) ** 2
        den += w
    if den == 0:
        return None
    return float(math.exp(-0.5 * num / den))


def qualitative_fit(label: str, profile: QueryProfile, ref: ReferenceStats) -> Optional[float]:
    sig = ref.signatures.get(label)
    if not sig or not profile.qualitative:
        return None
    scores = []
    for s, d in profile.qualitative.items():
        med = sig["median"].get(s)
        if med is None or med != med:
            continue
        dev = (med - ref.center[s]) / ref.scale[s]
        sign = 1 if d == "high" else -1
        scores.append(1 / (1 + math.exp(-2.0 * sign * dev)))
    return float(np.mean(scores)) if scores else None


def score_hypotheses(profile: QueryProfile, ref: ReferenceStats, hist_support: Dict[str, float],
                     evidence_labels: Sequence[Tuple[str, float]] = ()) -> List[Dict]:
    """Posterior-like score per candidate label.

    numeric   : 0.6 · historical kNN vote + 0.4 · normalised signature fit
    qualitative: 0.5 · direction fit + 0.5 · evidence vote
    text only : evidence vote weighted by retrieval score
    """
    labels = list(ref.labels) if ref.labels else sorted({l for l, _ in evidence_labels if l})
    rows = []
    if profile.sensors and ref.signatures:
        fits = {l: centroid_fit(l, profile, ref) or 0.0 for l in labels}
        tot_fit = sum(fits.values()) or 1e-9
        for l in labels:
            vote = hist_support.get(l, 0.0)
            fitn = fits[l] / tot_fit
            rows.append({"label": l, "score": 0.6 * vote + 0.4 * fitn,
                         "components": {"historical_vote": round(vote, 3), "signature_fit": round(fits[l], 3),
                                        "signature_fit_share": round(fitn, 3)}})
    elif profile.qualitative and ref.signatures:
        ev_vote = _evidence_vote(evidence_labels)
        fits = {l: qualitative_fit(l, profile, ref) or 0.0 for l in labels}
        tot = sum(fits.values()) or 1e-9
        for l in labels:
            rows.append({"label": l, "score": 0.5 * fits[l] / tot + 0.5 * ev_vote.get(l, 0.0),
                         "components": {"direction_fit": round(fits[l], 3), "evidence_vote": round(ev_vote.get(l, 0.0), 3)}})
    else:
        ev_vote = _evidence_vote(evidence_labels)
        for l, v in ev_vote.items():
            rows.append({"label": l, "score": v, "components": {"evidence_vote": round(v, 3)}})
    if profile.equipment_type and ref.equipment_label_counts:
        for r in rows:
            lift = ref.metadata_lift(r["label"], profile.equipment_type)
            r["score"] *= lift
            r["components"]["metadata_lift"] = round(lift, 3)
    tot = sum(r["score"] for r in rows) or 1.0
    for r in rows:
        r["score"] = round(r["score"] / tot, 4)
    rows.sort(key=lambda r: -r["score"])
    return rows


def _evidence_vote(evidence_labels: Sequence[Tuple[str, float]]) -> Dict[str, float]:
    v: Dict[str, float] = defaultdict(float)
    for l, w in evidence_labels:
        if l:
            v[l] += max(w, 0.0)
    tot = sum(v.values()) or 1.0
    return {k: x / tot for k, x in v.items()}


def signature_comparison(label: str, profile: QueryProfile, ref: ReferenceStats) -> Dict[str, List[Dict]]:
    """Per-sensor support / contradiction / missing for one hypothesis."""
    sig = ref.signatures.get(label)
    res = {"supporting": [], "contradicting": [], "missing": []}
    if not sig:
        return res
    for s, dev in key_sensors(label, ref):
        med, sc = sig["median"][s], sig["scale"][s]
        direction = "elevated" if dev > 0 else "reduced"
        if s in profile.sensors:
            v = profile.sensors[s]
            d = (v - med) / sc
            item = {"sensor": s, "value": v, "signature_median": round(med, 3), "deviation": round(d, 2),
                    "expected": direction}
            if abs(d) <= 1.5:
                res["supporting"].append(item)
            elif abs(d) >= 2.5 or (dev > 0 and v < ref.center[s]) or (dev < 0 and v > ref.center[s]):
                res["contradicting"].append(item)
        elif s in profile.qualitative:
            q = profile.qualitative[s]
            ok = (q == "high") == (dev > 0)
            item = {"sensor": s, "value": None, "reported": q, "expected": direction}
            (res["supporting"] if ok else res["contradicting"]).append(item)
        else:
            res["missing"].append({"sensor": s, "expected": direction})
    return res


def discriminating_sensors(a: str, b: str, ref: ReferenceStats, top: int = 3) -> List[Dict]:
    sa, sb = ref.signatures.get(a), ref.signatures.get(b)
    if not sa or not sb:
        return []
    out = []
    for s in SENSORS:
        ma, mb = sa["median"].get(s), sb["median"].get(s)
        if ma is None or mb is None or ma != ma or mb != mb:
            continue
        pooled = math.sqrt((sa["scale"][s] ** 2 + sb["scale"][s] ** 2) / 2) or 1.0
        sep = abs(ma - mb) / pooled * max(ref.weights.get(s, 0.0), 0.05) ** 0.5
        out.append({"sensor": s, "separation": round(sep, 3), a: round(ma, 3), b: round(mb, 3)})
    out.sort(key=lambda r: -r["separation"])
    return out[:top]


def describe_sensor(s: str, v: Optional[float]) -> str:
    return f"{SENSOR_SPECS[s]['label'].lower()} {fmt_sensor(s, v)}"


def failure_iq_candidates(evidence, profile: QueryProfile) -> List[Tuple[str, float]]:
    """Map FailureSensorIQ relevance records to (failure event, weight) votes
    for the sensors / equipment the user mentioned."""
    q = profile.normalized_query.lower()
    q_sensors = set(profile.qualitative) | set(profile.sensors)
    words = {s.replace("_", " ") for s in q_sensors} | ({"temperature"} if "temp" in q else set())
    votes: List[Tuple[str, float]] = []
    for e in evidence:
        rec_extra = e.content
        anchor = str(rec_extra.get("anchor") or "")
        rel = rec_extra.get("relevant_items") or []
        w = e.retrieval_score
        if rec_extra.get("anchor_type") == "failure_event" and anchor:
            if any(any(wd in str(item).lower() for wd in words) for item in rel) or not words:
                votes.append((anchor, w))
        elif rec_extra.get("anchor_type") == "sensor":
            if not words or any(wd in anchor for wd in words):
                for item in rel:
                    votes.append((str(item), w / max(len(rel), 1)))
    return votes


def critical_sensors(label: Optional[str], alternative: Optional[str], ref: ReferenceStats) -> List[str]:
    """Channels needed to confirm `label`: its own signature channels plus the
    channels that best separate it from the runner-up hypothesis."""
    if not label:
        return []
    out = [s for s, _ in key_sensors(label, ref)]
    if alternative and alternative != label:
        for d in discriminating_sensors(label, alternative, ref, top=2):
            if d["separation"] >= 0.5 and d["sensor"] not in out:
                out.append(d["sensor"])
    return out
