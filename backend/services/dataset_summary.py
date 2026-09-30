"""Dataset composition / data-quality summaries for the dashboard (computed, never hard-coded)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Dict, List

import numpy as np

from harness.canonical import SENSORS, SENSOR_SPECS
from harness.knowledge_base import KnowledgeBase

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _hist(values: np.ndarray, lo: float, hi: float, bins: int = 20) -> List[int]:
    v = values[np.isfinite(values)]
    if not v.size:
        return [0] * bins
    h, _ = np.histogram(np.clip(v, lo, hi), bins=bins, range=(lo, hi))
    return h.tolist()


def summarise_kb(kb: KnowledgeBase) -> Dict:
    out: Dict = {"name": kb.name, "modes": kb.available_modes(), "partitions": {}, "totals": {}}
    all_mats = [p.matrix for p in kb.partitions.values() if p.matrix.size]
    numeric = bool(all_mats) and kb.has_numeric()
    ranges = {}
    if numeric:
        stacked = np.vstack(all_mats)
        for j, s in enumerate(SENSORS):
            col = stacked[:, j][np.isfinite(stacked[:, j])]
            ranges[s] = (float(np.percentile(col, 0.5)), float(np.percentile(col, 99.5))) if col.size else (0.0, 1.0)
    for st, p in kb.partitions.items():
        recs = p.records
        labels = Counter(r.label or "(none)" for r in recs)
        part = {
            "records": len(recs),
            "index": p.index_name,
            "semantic_search": p.semantic_ok,
            "label_distribution": dict(labels.most_common()),
            "failure_classes": len([l for l in labels if l != "(none)"]),
            "equipment_types": dict(Counter(r.equipment_type or "unknown" for r in recs).most_common()),
            "components": dict(Counter(r.component for r in recs if r.component).most_common()),
            "severity": dict(Counter(r.severity for r in recs if r.severity).most_common()),
            "difficulty": dict(Counter(r.difficulty for r in recs if r.difficulty).most_common()),
            "human_review_rate": (round(sum(1 for r in recs if r.human_review) / len(recs), 3)
                                  if recs and any(r.human_review is not None for r in recs) else None),
            "scenarios": dict(Counter(r.synthetic_scenario.split("_")[0] for r in recs if r.synthetic_scenario).most_common()),
        }
        if numeric and p.matrix.size:
            m = p.matrix
            part["missing_values"] = int(np.isnan(m).sum())
            part["sensor_coverage"] = {s: round(float(np.isfinite(m[:, j]).mean()), 4) for j, s in enumerate(SENSORS)}
            keys = [tuple(np.round(np.nan_to_num(row, nan=-1), 3)) + (r.system_context,) for row, r in zip(m, recs)]
            part["duplicate_records"] = int(len(keys) - len(set(keys)))
            part["histograms"] = {s: _hist(m[:, j], *ranges[s]) for j, s in enumerate(SENSORS)}
            by_label = {}
            for lab in labels:
                mask = p.labels == lab
                if mask.sum() >= 5:
                    by_label[lab] = {s: (None if not np.isfinite(m[mask, j]).any()
                                         else round(float(np.nanmedian(m[mask, j])), 3)) for j, s in enumerate(SENSORS)}
            part["sensor_medians_by_label"] = by_label
        else:
            part["missing_values"] = 0
            part["duplicate_records"] = int(len(recs) - len({r.text for r in recs}))
        out["partitions"][st] = part
    out["totals"] = {
        "records": sum(len(p.records) for p in kb.partitions.values()),
        "real": len(kb.partitions["real"].records) if "real" in kb.partitions else 0,
        "synthetic": len(kb.partitions["synthetic"].records) if "synthetic" in kb.partitions else 0,
    }
    if numeric:
        out["sensors"] = [{"sensor": s, "label": SENSOR_SPECS[s]["label"], "unit": SENSOR_SPECS[s]["unit"],
                           "range": ranges[s]} for s in SENSORS]
        ref = kb.reference("combined" if "combined" in kb.available_modes() else kb.available_modes()[0])
        out["reference"] = {"weights": ref.weights, "band_low": ref.band_low, "band_high": ref.band_high,
                            "band_source": ref.band_source, "no_match_distance": ref.no_match_distance,
                            "typical_nn_distance": ref.typical_nn_distance}
    report = BACKEND_DIR / "data" / "synthetic" / "validation_report.json"
    if kb.name == "afrb" and report.exists():
        try:
            out["synthetic_validation"] = json.loads(report.read_text())
        except Exception:
            pass
    return out


def evaluation_results() -> Dict:
    res_dir = BACKEND_DIR / "evaluation" / "results"
    out = {}
    for f in sorted(res_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        out[f.stem] = {"system": data.get("system"), "data_mode": data.get("data_mode"),
                       "llm_available": data.get("llm_available"), "summary": data.get("summary")}
    return out
