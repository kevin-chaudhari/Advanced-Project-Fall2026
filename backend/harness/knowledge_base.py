"""
Knowledge bases (REAL / SYNTHETIC partitions) + data-derived reference statistics.

A knowledge base holds canonical records aligned 1:1 with FAISS index rows,
a numeric sensor matrix (NaN = missing, never imputed) and reference
statistics computed from the data itself:

* robust sensor scaling (median / IQR of the REAL data when available)
* data-derived sensor weights (share of variance explained by the failure label,
  so e.g. RPM — which is label-independent in AFRB — gets a low weight)
* per-label signatures (median + robust spread per sensor)
* reference bands used to call a channel "high" or "low"
* a calibrated "no historical match" distance threshold
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from harness.canonical import SENSORS, CanonicalRecord
from utils.logger import setup_logger

logger = setup_logger(__name__)

MODES = ("real", "synthetic", "combined")


@dataclass
class Partition:
    source_type: str                 # "real" | "synthetic"
    index_name: str
    records: List[CanonicalRecord]
    matrix: np.ndarray               # (n, 7) float, NaN for missing
    labels: np.ndarray               # (n,) object
    semantic_ok: bool = False


@dataclass
class ReferenceStats:
    center: Dict[str, float]
    scale: Dict[str, float]
    weights: Dict[str, float]
    band_low: Dict[str, float]
    band_high: Dict[str, float]
    band_source: str
    signatures: Dict[str, Dict[str, Dict[str, float]]]   # label -> {"median": {s: v}, "scale": {s: v}}
    label_counts: Dict[str, int]
    label_sources: Dict[str, Dict[str, int]]
    no_match_distance: float
    typical_nn_distance: float
    labels: List[str] = field(default_factory=list)
    equipment_label_counts: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def metadata_lift(self, label: str, equipment_type: Optional[str], alpha: float = 5.0) -> float:
        """P(label | equipment) / P(label), Laplace-smoothed and clipped to [0.25, 3].
        Flat (≈1) when labels are independent of equipment, as in the real AFRB data."""
        if not equipment_type or equipment_type not in self.equipment_label_counts:
            return 1.0
        eq = self.equipment_label_counts[equipment_type]
        n_eq = sum(eq.values())
        n_all = sum(self.label_counts.values()) or 1
        k = max(len(self.label_counts), 1)
        p_given = (eq.get(label, 0) + alpha) / (n_eq + alpha * k)
        p = (self.label_counts.get(label, 0) + alpha) / (n_all + alpha * k)
        return float(min(3.0, max(0.25, p_given / p)))


def _nanmedian(a: np.ndarray) -> float:
    a = a[~np.isnan(a)]
    return float(np.median(a)) if a.size else float("nan")


def _iqr_scale(a: np.ndarray) -> float:
    a = a[~np.isnan(a)]
    if a.size < 4:
        return float("nan")
    q1, q3 = np.percentile(a, [25, 75])
    return float((q3 - q1) / 1.349)


class KnowledgeBase:
    """All records of one dataset family (e.g. AFRB) split by provenance."""

    def __init__(self, name: str):
        self.name = name
        self.partitions: Dict[str, Partition] = {}
        self._ref_cache: Dict[str, ReferenceStats] = {}

    # ── construction ─────────────────────────────────────────────────────────
    def add_partition(self, source_type: str, index_name: str, records: List[CanonicalRecord],
                      semantic_ok: bool) -> None:
        mat = np.array([[np.nan if r.sensors.get(s) is None else r.sensors[s] for s in SENSORS]
                        for r in records], dtype=float) if records else np.zeros((0, len(SENSORS)))
        labels = np.array([r.label or "" for r in records], dtype=object)
        self.partitions[source_type] = Partition(source_type, index_name, records, mat, labels, semantic_ok)
        self._ref_cache.clear()

    def partitions_for(self, mode: str) -> List[Partition]:
        if mode == "real":
            keys = ["real"]
        elif mode == "synthetic":
            keys = ["synthetic"]
        else:
            keys = ["real", "synthetic"]
        return [self.partitions[k] for k in keys if k in self.partitions]

    def available_modes(self) -> List[str]:
        modes = []
        if "real" in self.partitions:
            modes.append("real")
        if "synthetic" in self.partitions:
            modes.append("synthetic")
        if len(modes) == 2:
            modes.append("combined")
        return modes

    def has_numeric(self) -> bool:
        return any(np.isfinite(p.matrix).any() for p in self.partitions.values() if p.matrix.size)

    # ── reference statistics ────────────────────────────────────────────────
    def reference(self, mode: str) -> ReferenceStats:
        if mode not in self._ref_cache:
            self._ref_cache[mode] = self._compute_reference(mode)
        return self._ref_cache[mode]

    def _compute_reference(self, mode: str) -> ReferenceStats:
        parts = self.partitions_for(mode)
        mat = np.vstack([p.matrix for p in parts]) if parts else np.zeros((0, len(SENSORS)))
        labels = np.concatenate([p.labels for p in parts]) if parts else np.array([], dtype=object)
        sources = np.concatenate([np.full(len(p.records), p.source_type, dtype=object) for p in parts]) \
            if parts else np.array([], dtype=object)

        # scaling from REAL data when present (stable across modes)
        scale_mat = self.partitions["real"].matrix if "real" in self.partitions and \
            np.isfinite(self.partitions["real"].matrix).any() else mat
        center, scale = {}, {}
        for j, s in enumerate(SENSORS):
            col = scale_mat[:, j] if scale_mat.size else np.array([])
            center[s] = _nanmedian(col) if col.size else 0.0
            sc = _iqr_scale(col) if col.size else 1.0
            scale[s] = sc if sc and np.isfinite(sc) and sc > 1e-9 else 1.0

        uniq = [l for l in sorted(set(labels.tolist())) if l]
        # data-derived weights: eta^2 = between-label variance / total variance
        weights = {}
        for j, s in enumerate(SENSORS):
            col = mat[:, j] if mat.size else np.array([])
            ok = np.isfinite(col) & (labels != "")
            if ok.sum() < 20:
                weights[s] = 0.0
                continue
            z = (col[ok] - center[s]) / scale[s]
            total = float(np.var(z)) or 1e-9
            between = 0.0
            for lab in uniq:
                m = labels[ok] == lab
                if m.sum():
                    between += m.sum() * (z[m].mean() - z.mean()) ** 2
            eta2 = between / (ok.sum() * total)
            weights[s] = round(max(0.03, float(eta2)), 4)

        signatures, counts, lab_src = {}, {}, {}
        for lab in uniq:
            m = labels == lab
            counts[lab] = int(m.sum())
            lab_src[lab] = {st: int(((sources == st) & m).sum()) for st in ("real", "synthetic")}
            med, sc = {}, {}
            for j, s in enumerate(SENSORS):
                col = mat[m, j]
                med[s] = _nanmedian(col)
                cs = _iqr_scale(col)
                sc[s] = max(cs if np.isfinite(cs) else scale[s], 0.3 * scale[s])
            signatures[lab] = {"median": med, "scale": sc}

        # reference bands
        normal_mask = labels == "Normal Operation"
        if normal_mask.sum() >= 50:
            band_src = "synthetic healthy envelope (2.5–97.5th pct of Normal Operation records)"
            lo_p, hi_p, band_mat = 2.5, 97.5, mat[normal_mask]
        else:
            band_src = "reference population percentiles (15–85th pct; no healthy-class data in this mode)"
            lo_p, hi_p, band_mat = 15, 85, mat
        band_low, band_high = {}, {}
        for j, s in enumerate(SENSORS):
            col = band_mat[:, j] if band_mat.size else np.array([])
            col = col[np.isfinite(col)]
            if col.size:
                band_low[s], band_high[s] = (float(np.percentile(col, lo_p)), float(np.percentile(col, hi_p)))
            else:
                band_low[s] = band_high[s] = float("nan")

        eq_counts: Dict[str, Dict[str, int]] = {}
        for p in parts:
            for r in p.records:
                if r.equipment_type and r.label:
                    d = eq_counts.setdefault(r.equipment_type, {})
                    d[r.label] = d.get(r.label, 0) + 1
        ref = ReferenceStats(center, scale, weights, band_low, band_high, band_src, signatures,
                             counts, lab_src, no_match_distance=3.0, typical_nn_distance=0.5, labels=uniq,
                             equipment_label_counts=eq_counts)
        self._calibrate_no_match(ref, mode)
        return ref

    def _calibrate_no_match(self, ref: ReferenceStats, mode: str, n: int = 300) -> None:
        """Distribution of nearest-neighbour distances of records to the rest of
        the knowledge base; the 99.5th percentile (+25 % margin) defines
        'no strong historical match'."""
        parts = self.partitions_for(mode)
        if not parts:
            return
        mat = np.vstack([p.matrix for p in parts])
        complete = np.where(np.isfinite(mat).sum(axis=1) >= 5)[0]
        if complete.size < 50:
            return
        rng = np.random.default_rng(11)
        sample = rng.choice(complete, size=min(n, complete.size), replace=False)
        dists = []
        for i in sample:
            d, _ = self.numeric_distances(mat[i], ref, mode, _mat=mat)
            d[i] = np.inf
            dists.append(float(np.min(d)))
        dists = np.array(dists)
        ref.typical_nn_distance = float(np.median(dists))
        ref.no_match_distance = float(np.percentile(dists, 99.5) * 1.25)

    # ── numeric similarity ──────────────────────────────────────────────────
    def numeric_distances(self, query: Sequence[float], ref: ReferenceStats, mode: str,
                          _mat: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray]:
        """Weighted robust distance between the query vector (NaN = unknown) and
        every record, using only channels present in both.  Returns
        (distance, coverage) where coverage is the share of the query's
        (weighted) channels that the record could be compared on."""
        mat = _mat if _mat is not None else np.vstack([p.matrix for p in self.partitions_for(mode)])
        q = np.asarray(query, dtype=float)
        centers = np.array([ref.center[s] for s in SENSORS])
        scales = np.array([ref.scale[s] for s in SENSORS])
        w = np.array([ref.weights[s] for s in SENSORS])
        qz = (q - centers) / scales
        rz = (mat - centers) / scales
        q_ok = np.isfinite(qz)
        both = np.isfinite(rz) & q_ok
        diff2 = np.where(both, (rz - np.nan_to_num(qz)) ** 2, 0.0)
        wsum = (both * w).sum(axis=1)
        qw = float((q_ok * w).sum()) or 1e-9
        dist = np.sqrt((diff2 * w).sum(axis=1) / np.maximum(wsum, 1e-9))
        dist = np.where(wsum > 0, dist, np.inf)
        coverage = wsum / qw
        return dist, coverage

    def all_records(self, mode: str) -> List[CanonicalRecord]:
        out: List[CanonicalRecord] = []
        for p in self.partitions_for(mode):
            out.extend(p.records)
        return out

    def summary(self) -> Dict:
        out = {"name": self.name, "partitions": {}}
        for st, p in self.partitions.items():
            labels = [l for l in p.labels.tolist() if l]
            from collections import Counter
            miss = float(np.isnan(p.matrix).mean()) if p.matrix.size and np.isfinite(p.matrix).any() else None
            out["partitions"][st] = {"records": len(p.records), "index": p.index_name,
                                     "semantic_search": p.semantic_ok,
                                     "labels": dict(Counter(labels).most_common()),
                                     "sensor_missing_rate": miss}
        return out
