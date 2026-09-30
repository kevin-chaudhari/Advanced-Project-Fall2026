"""
System-agnostic benchmark metrics.

The same functions score the ORIGINAL pipeline (baseline) and the improved
harness, using only the public response payload + the records each system
reports as retrieved.  Nothing here trusts a system's self-reported quality
scores.
"""

from __future__ import annotations

import json
import re
from statistics import mean
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

LABEL_PATTERNS: List[Tuple[str, str]] = [
    ("Insufficient Evidence", r"insufficient evidence|inconclusive|cannot be determined|cannot determine|no strong historical match|no reliable diagnosis"),
    ("Normal Operation", r"normal operation|no fault|operating normally|within (?:the )?normal|healthy"),
    ("Sensor Malfunction", r"sensor malfunction|sensor fault|sensor anomaly|instrumentation fault|faulty sensor"),
    ("Pump Cavitation", r"cavitation"),
    ("Seal Failure", r"seal failure|seal leak|mechanical seal"),
    ("Gearbox Degradation", r"gearbox degradation|gear(?:box)? wear|gear train degradation"),
    ("Lubrication Degradation", r"lubrication"),
    ("Cooling System Failure", r"cooling system|cooling failure|coolant"),
    ("Electrical Overload", r"electrical overload|electrical fault|overload"),
    ("Valve Blockage", r"valve blockage|blockage|blocked valve"),
    ("Bearing Wear", r"bearing"),
    ("Rotor Imbalance", r"rotor imbalance|shaft imbalance|imbalance|unbalance"),
]

SENSOR_CONTEXT = {
    "temperature": r"temperature|temp\b|°c|deg(?:rees)?\b",
    "vibration": r"vibration|mm/s",
    "pressure": r"pressure|psi|bar\b",
    "rpm": r"rpm|speed",
    "current": r"current|amp",
    "voltage": r"voltage|volt",
    "flow": r"flow|l/min|lpm",
    "hours": r"hours|hrs",
}

_NUM_UNIT = re.compile(
    r"(?<![A-Za-z\-#])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(°\s?c|°|mm/s|psi|bar\b|rpm|a\b|amps?\b|v\b|volts?\b|l/min|lpm|hrs|hours|db\b|ppm|cst|mω)",
    re.IGNORECASE,
)
_NUM = re.compile(r"(?<![A-Za-z\-#\[])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w\]])")


def predicted_label(text: str) -> Optional[str]:
    """Earliest failure-mode phrase occurring in the text."""
    if not text:
        return None
    t = text.lower()
    best: Tuple[int, Optional[str]] = (10 ** 9, None)
    for label, pat in LABEL_PATTERNS:
        m = re.search(pat, t)
        if m and m.start() < best[0]:
            best = (m.start(), label)
    return best[1]


def numbers_in(text: str) -> List[float]:
    out = []
    for m in _NUM.finditer(text or ""):
        try:
            out.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return out


def sensor_claims(text: str) -> List[Tuple[float, str]]:
    """Numbers stated as physical sensor/asset quantities.

    A number counts as a claim when it carries a physical unit, or when a sensor
    keyword appears within the 30 characters before it.  Percentages,
    step numbers, evidence IDs and counts are ignored.
    """
    claims: List[Tuple[float, str]] = []
    if not text:
        return claims
    seen_spans = set()
    for m in _NUM_UNIT.finditer(text):
        val = float(m.group(1).replace(",", ""))
        claims.append((val, text[max(0, m.start() - 30): m.end()]))
        seen_spans.add(m.start(1))
    low = text.lower()
    for m in _NUM.finditer(text):
        if m.start(1) in seen_spans:
            continue
        after = text[m.end(): m.end() + 2]
        if after.startswith("%"):
            continue
        window = low[max(0, m.start() - 30): m.start()]
        if re.search(r"(ev-|step|rank|top-|\[|#)\s*$", window[-8:]):
            continue
        if any(re.search(p, window) for p in SENSOR_CONTEXT.values()):
            val = float(m.group(1).replace(",", ""))
            if val.is_integer() and val < 10 and "vibration" not in window:
                continue  # small integers are almost always counts
            claims.append((val, text[max(0, m.start() - 30): m.end()]))
    return claims


def is_supported(value: float, allowed: Sequence[float]) -> bool:
    for a in allowed:
        tol = max(abs(a) * 0.006, 0.051 if abs(a) < 5 else 0.11)
        if abs(value - a) <= tol:
            return True
    return False


def output_texts(resp: Dict) -> Dict[str, List[str]]:
    """Collect all user-facing text fields of a response."""
    final = [str(resp.get("final_diagnosis", "")), str(resp.get("direct_answer", ""))]
    reasoning = [str(x) for x in resp.get("reasoning", []) or []]
    evidence = [str(x) for x in resp.get("supporting_evidence", []) or []]
    agents: List[str] = []
    for a in resp.get("agent_outputs", []) or []:
        agents.append(str(a.get("diagnosis", "")))
        agents.append(str(a.get("reasoning", "")))
        agents.extend(str(k) for k in a.get("key_findings", []) or [])
        agents.append(str(a.get("recommendation", "")))
    return {"final": final, "reasoning": reasoning, "evidence": evidence, "agents": agents}


def allowed_values(question: str, retrieved_texts: Iterable[str], extra: Iterable[float] = ()) -> List[float]:
    vals = numbers_in(question)
    per_doc: List[List[float]] = []
    for t in retrieved_texts:
        nums = numbers_in(t)
        vals.extend(nums)
        per_doc.append(nums)
    vals.extend(extra)
    return vals


def score_case(case: Dict, resp: Dict, retrieved: List[Dict], latency_ms: float,
               extra_allowed: Iterable[float] = (), structured_label: Optional[str] = None,
               declared_rules: Iterable[float] = ()) -> Dict:
    """declared_rules: thresholds of explicitly declared domain rules (e.g. the
    harness's R-C* consistency rules).  Numbers matching them are counted
    separately as rule-threshold claims instead of as unsupported."""
    declared_rules = list(declared_rules)
    acceptable = json.loads(case["acceptable_labels"])
    expected_amb = str(case["expected_ambiguity"]).lower() == "true"
    missing = json.loads(case.get("missing_sensors") or "[]")

    final_text = " ".join(output_texts(resp)["final"])
    pred = predicted_label(final_text)
    correct = pred in acceptable
    flagged = bool(resp.get("ambiguity", False))

    texts = output_texts(resp)
    allowed = allowed_values(case["question"], [r.get("content", "") for r in retrieved], extra_allowed)
    total = unsup = rule_claims = 0
    unsupported_examples: List[str] = []
    fabricated_missing = False
    for group in ("final", "reasoning", "evidence", "agents"):
        for t in texts[group]:
            for val, ctx in sensor_claims(t):
                total += 1
                if not is_supported(val, allowed) and declared_rules and is_supported(val, declared_rules):
                    rule_claims += 1
                    continue
                if not is_supported(val, allowed):
                    unsup += 1
                    if len(unsupported_examples) < 4:
                        unsupported_examples.append(ctx.strip())
                    for m in missing:
                        key = {"Flow_Rate": "flow", "RPM": "rpm"}.get(m, m.lower())
                        if re.search(SENSOR_CONTEXT.get(key, key), ctx.lower()):
                            fabricated_missing = True

    # evidence grounding of supporting_evidence items
    ev_items = texts["evidence"]
    valid_ids = {str(r.get("evidence_id")) for r in retrieved if r.get("evidence_id")}
    grounded = 0
    for item in ev_items:
        ids = set(re.findall(r"EV-\d{3,}", item))
        claims = sensor_claims(item)
        if ids and ids <= valid_ids:
            grounded += 1
        elif claims and all(is_supported(v, allowed) for v, _ in claims):
            grounded += 1
    grounding = grounded / len(ev_items) if ev_items else 0.0

    # retrieval accuracy (top-5)
    top = retrieved[:5]
    labels = [r.get("label") for r in top]
    exp = case["expected_failure_mode"]
    precision = (sum(1 for l in labels if l in acceptable) / len(top)) if top else 0.0
    hit = any(l in acceptable for l in labels)

    return {
        "case_id": case["case_id"], "category": case["category"], "source_type": case["source_type"],
        "expected": exp, "acceptable": acceptable, "predicted_text_label": pred,
        "structured_label": structured_label, "correct": bool(correct),
        "expected_ambiguity": expected_amb, "flagged_review": flagged,
        "numeric_claims": total, "unsupported_numeric_claims": unsup, "rule_threshold_claims": rule_claims,
        "unsupported_examples": unsupported_examples,
        "fabricated_missing_sensor": fabricated_missing, "has_missing_sensors": bool(missing),
        "evidence_items": len(ev_items), "evidence_grounding": grounding,
        "retrieval_precision_at5": precision, "retrieval_hit_at5": hit,
        "retrieved_labels": labels, "latency_ms": latency_ms,
    }


def summarise(rows: List[Dict]) -> Dict:
    def rate(pred) -> float:
        sel = [r for r in rows if pred(r)]
        return len(sel)

    n = len(rows)
    amb_pos = [r for r in rows if r["expected_ambiguity"]]
    amb_neg = [r for r in rows if not r["expected_ambiguity"]]
    claims = sum(r["numeric_claims"] for r in rows)
    unsup = sum(r["unsupported_numeric_claims"] for r in rows)
    miss = [r for r in rows if r["has_missing_sensors"]]
    retr = [r for r in rows if r["category"] in ("clear_fault", "real_afrb_holdout", "normal_equipment")]
    by_cat: Dict[str, Dict] = {}
    for r in rows:
        c = by_cat.setdefault(r["category"], {"n": 0, "correct": 0, "flagged": 0})
        c["n"] += 1
        c["correct"] += int(r["correct"])
        c["flagged"] += int(r["flagged_review"])
    for c in by_cat.values():
        c["accuracy"] = round(c["correct"] / c["n"], 3)
        c["review_rate"] = round(c["flagged"] / c["n"], 3)
    lat = sorted(r["latency_ms"] for r in rows)
    return {
        "cases": n,
        "diagnostic_accuracy": round(sum(r["correct"] for r in rows) / n, 3) if n else 0,
        "accuracy_real_holdout": _acc([r for r in rows if r["source_type"] == "real"]),
        "accuracy_synthetic": _acc([r for r in rows if r["source_type"] == "synthetic"]),
        "ambiguity_recall": round(sum(r["flagged_review"] for r in amb_pos) / len(amb_pos), 3) if amb_pos else None,
        "false_review_rate": round(sum(r["flagged_review"] for r in amb_neg) / len(amb_neg), 3) if amb_neg else None,
        "numeric_claims_total": claims,
        "unsupported_numeric_claims": unsup,
        "declared_rule_threshold_claims": sum(r.get("rule_threshold_claims", 0) for r in rows),
        "hallucination_rate": round(unsup / claims, 3) if claims else 0.0,
        "cases_with_any_unsupported_claim": round(sum(1 for r in rows if r["unsupported_numeric_claims"]) / n, 3) if n else 0,
        "missing_sensor_fabrication_rate": round(sum(r["fabricated_missing_sensor"] for r in miss) / len(miss), 3) if miss else None,
        "evidence_grounding": round(mean(r["evidence_grounding"] for r in rows), 3) if rows else 0,
        "retrieval_precision_at5": round(mean(r["retrieval_precision_at5"] for r in retr), 3) if retr else None,
        "retrieval_hit_at5": round(mean(float(r["retrieval_hit_at5"]) for r in retr), 3) if retr else None,
        "latency_ms_median": round(lat[len(lat) // 2], 1) if lat else 0,
        "latency_ms_p95": round(lat[int(len(lat) * 0.95) - 1], 1) if lat else 0,
        "auto_resolve_rate": round(sum(1 for r in rows if not r["flagged_review"]) / n, 3) if n else 0,
        "accuracy_when_auto_resolved": _acc([r for r in rows if not r["flagged_review"]]),
        "errors_caught_by_review": (round(sum(1 for r in rows if not r["correct"] and r["flagged_review"])
                                          / max(1, sum(1 for r in rows if not r["correct"])), 3)),
        "by_category": by_cat,
    }


def _acc(rows: List[Dict]):
    return round(sum(r["correct"] for r in rows) / len(rows), 3) if rows else None
