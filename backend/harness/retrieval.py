"""
Multi-stage retrieval (FAISS is kept; it is the semantic stage).

    query profile
      ├─ Pass 1  semantic      FAISS (all-MiniLM-L6-v2) over the active partitions
      ├─ Pass 2  metadata      equipment type / mentioned failure modes / label filters
      ├─ Pass 3  numerical     weighted robust distance on the sensor channels the
      │                        user actually reported (missing channels are skipped,
      │                        never imputed); qualitative "high/low" if no numbers
      ├─ Pass 4  historical    label support among the nearest historical cases
      └─ rerank  weighted fusion → diversified evidence bundle
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from harness.canonical import SENSORS, CanonicalRecord
from harness.knowledge_base import KnowledgeBase, ReferenceStats
from harness.schema import QueryProfile
from utils.logger import setup_logger

logger = setup_logger(__name__)

FUSION_WEIGHTS = {
    "numeric": {"numeric": 0.50, "semantic": 0.20, "historical": 0.15, "metadata": 0.15},
    "qualitative": {"semantic": 0.45, "qualitative": 0.35, "metadata": 0.20},
    "text": {"semantic": 0.6, "metadata": 0.4},
}


@dataclass
class Candidate:
    key: Tuple[str, int]
    record: CanonicalRecord
    scores: Dict[str, float] = field(default_factory=dict)
    fused: float = 0.0
    numeric_distance: Optional[float] = None
    reasons: List[str] = field(default_factory=list)

    method: str = "semantic"


@dataclass
class Neighbor:
    record: CanonicalRecord
    distance: float
    coverage: float


@dataclass
class RetrievalResult:
    bundle: List[Candidate]
    neighbors: List[Neighbor]
    stats: Dict


class MultiStageRetriever:
    def __init__(self, kb: KnowledgeBase, embedder=None, store=None):
        self.kb = kb
        self.embedder = embedder
        self.store = store
        self._qcache: Dict[str, np.ndarray] = {}

    # ── helpers ──────────────────────────────────────────────────────────────
    def _embed(self, text: str) -> Optional[np.ndarray]:
        if self.embedder is None:
            return None
        if text not in self._qcache:
            if len(self._qcache) > 256:
                self._qcache.clear()
            self._qcache[text] = self.embedder.embed_single(text)
        return self._qcache[text]

    @staticmethod
    def query_vector(profile: QueryProfile) -> np.ndarray:
        return np.array([profile.sensors.get(s, np.nan) for s in SENSORS], dtype=float)

    # ── main entry ───────────────────────────────────────────────────────────
    def retrieve(self, profile: QueryProfile, mode: str, top_k: int = 8,
                 exclude_ids: Sequence[str] = (), label_filter: Optional[Sequence[str]] = None,
                 expand: float = 1.0, k_sem: int = 40, k_num: int = 60,
                 historical_k: int = 25) -> RetrievalResult:
        ref = self.kb.reference(mode)
        parts = self.kb.partitions_for(mode)
        excl: Set[str] = set(exclude_ids or [])
        lf = set(label_filter) if label_filter else None
        cands: Dict[Tuple[str, int], Candidate] = {}
        stats: Dict = {"mode": mode, "stages": [], "expand": expand, "label_filter": sorted(lf) if lf else None}

        def cand(p, row) -> Optional[Candidate]:
            rec = p.records[row]
            if rec.record_id in excl or (lf and rec.label not in lf):
                return None
            key = (p.source_type, int(row))
            if key not in cands:
                cands[key] = Candidate(key, rec)
            return cands[key]

        # Pass 1 — semantic (FAISS)
        n_sem = 0
        qv = self._embed(profile.normalized_query)
        for p in parts:
            if not p.semantic_ok or qv is None or self.store is None:
                continue
            d, idx = self.store.search_raw(p.index_name, qv, int(k_sem * expand) + len(excl))
            for dist, row in zip(d, idx):
                if row < 0:
                    continue
                c = cand(p, row)
                if c is None:
                    continue
                sim = float(max(0.0, 1.0 - dist / 2.0))  # unit-norm vectors: L2² = 2 - 2cos
                c.scores["semantic"] = max(c.scores.get("semantic", 0.0), sim)
                n_sem += 1
        stats["stages"].append({"stage": "semantic", "candidates": n_sem,
                                "skipped": n_sem == 0 and any(not p.semantic_ok for p in parts)})

        # Pass 2a — metadata-filtered candidates for text-only knowledge bases
        if not self.kb.has_numeric():
            stats["stages"].append(self._metadata_pass(profile, parts, qv, cand, int(80 * expand)))

        # Pass 3 — numerical similarity (+ qualitative directions)
        neighbors: List[Neighbor] = []
        q = self.query_vector(profile)
        has_numeric = bool(np.isfinite(q).any()) and self.kb.has_numeric()
        best_distance = None
        if has_numeric:
            all_d, all_cov, owners = [], [], []
            for p in parts:
                if not p.matrix.size:
                    continue
                d, cov = self.kb.numeric_distances(q, ref, mode, _mat=p.matrix)
                all_d.append(d)
                all_cov.append(cov)
                owners.append(p)
            flat: List[Tuple[float, float, object, int]] = []
            for p, d, cov in zip(owners, all_d, all_cov):
                eff = d + (1.0 - np.clip(cov, 0, 1)) * 1.5          # penalise partial comparability
                take = min(len(eff), int(k_num * expand) + len(excl) + 5)
                idx = np.argpartition(eff, take - 1)[:take] if take < len(eff) else np.arange(len(eff))
                for row in idx:
                    if np.isfinite(eff[row]):
                        flat.append((float(eff[row]), float(cov[row]), p, int(row)))
            flat.sort(key=lambda t: t[0])
            added = 0
            for eff, cov, p, row in flat:
                rec = p.records[row]
                if rec.record_id in excl or (lf and rec.label not in lf):
                    continue
                if len(neighbors) < max(historical_k, int(k_num * expand)):
                    neighbors.append(Neighbor(rec, eff, cov))
                if added < int(k_num * expand):
                    c = cand(p, row)
                    if c is not None:
                        c.numeric_distance = eff
                        c.scores["numeric"] = float(np.sqrt(max(cov, 0)) / (1.0 + eff))
                        added += 1
            best_distance = neighbors[0].distance if neighbors else None
            stats["stages"].append({"stage": "numeric", "candidates": added,
                                    "channels_used": [s for s in SENSORS if s in profile.sensors],
                                    "best_distance": best_distance})
        elif profile.qualitative and self.kb.has_numeric():
            stats["stages"].append(self._qualitative(profile, parts, ref, cand, k_num, expand))

        # Pass 2 — metadata
        for c in cands.values():
            c.scores["metadata"] = self._metadata_score(c.record, profile)

        # Pass 4 — historical label support among nearest cases
        hist_support = self.historical_support(neighbors[:historical_k], ref, mode)
        for c in cands.values():
            if hist_support and c.record.label:
                c.scores["historical"] = hist_support.get(c.record.label, 0.0)
        stats["stages"].append({"stage": "historical", "neighbors": len(neighbors[:historical_k]),
                                "label_support": {k: round(v, 3) for k, v in sorted(hist_support.items(), key=lambda kv: -kv[1])[:5]}})

        # rerank
        scheme = "numeric" if has_numeric else ("qualitative" if profile.qualitative and self.kb.has_numeric() else "text")
        w = FUSION_WEIGHTS[scheme]
        for c in cands.values():
            c.fused = round(sum(w.get(k, 0.0) * c.scores.get(k, 0.0) for k in w), 4)
            contrib = {k: w.get(k, 0.0) * c.scores.get(k, 0.0) for k in ("numeric", "semantic", "qualitative", "metadata")}
            c.method = max(contrib, key=contrib.get) if any(contrib.values()) else "semantic"
            c.reasons = self._reasons(c, profile)
        ranked = sorted(cands.values(), key=lambda c: -c.fused)
        bundle = self._diversify(ranked, top_k, hist_support)
        stats.update({
            "scheme": scheme,
            "fusion_weights": w,
            "candidates_total": len(cands),
            "best_numeric_distance": best_distance,
            "no_match_threshold": ref.no_match_distance if has_numeric else None,
            "typical_nn_distance": ref.typical_nn_distance if has_numeric else None,
            "no_historical_match": bool(has_numeric and (best_distance is None or best_distance > ref.no_match_distance)),
            "mean_top5_fused": round(float(np.mean([c.fused for c in bundle[:5]])), 4) if bundle else 0.0,
            "source_composition": dict(_count(c.record.source_type for c in bundle)),
            "historical_support": hist_support,
        })
        return RetrievalResult(bundle, neighbors, stats)

    # ── stages ───────────────────────────────────────────────────────────────
    def _qualitative(self, profile, parts, ref: ReferenceStats, cand, k_num, expand) -> Dict:
        cols = [(SENSORS.index(s), 1.0 if d == "high" else -1.0, s) for s, d in profile.qualitative.items() if s in SENSORS]
        added = 0
        for p in parts:
            if not p.matrix.size or not cols:
                continue
            strength = np.zeros(len(p.records))
            satisfied = np.zeros(len(p.records))
            for j, sign, s in cols:
                z = (p.matrix[:, j] - ref.center[s]) / ref.scale[s]
                z = np.nan_to_num(z, nan=0.0)
                satisfied += (sign * z > 0.5)
                strength += np.clip(sign * z, -2, 2)
            score = satisfied / len(cols) * 0.7 + np.clip(strength / (2 * len(cols)), 0, 1) * 0.3
            take = int(k_num * expand)
            idx = np.argsort(-score, kind="stable")[:take]
            for row in idx:
                c = cand(p, row)
                if c is not None:
                    c.scores["qualitative"] = float(score[row])
                    added += 1
        return {"stage": "qualitative", "candidates": added, "directions": dict(profile.qualitative)}

    def _metadata_pass(self, profile: QueryProfile, parts, qv, cand, limit: int) -> Dict:
        """Filter records by equipment type and by the sensors / failure terms the
        user mentioned, then score them semantically by reconstructing their
        stored FAISS vectors (exact cosine)."""
        terms = {s.replace("_", " ") for s in list(profile.qualitative) + list(profile.sensors)}
        terms |= {w for w in ("vibration", "temperature", "pressure", "current", "voltage", "speed", "flow",
                              "noise", "oil", "power", "bearing", "seal", "impeller", "cavitation", "winding")
                  if w in profile.normalized_query.lower()}
        added = 0
        for p in parts:
            idx = self.store.indexes.get(p.index_name) if self.store is not None else None
            hits = []
            for row, r in enumerate(p.records):
                if profile.equipment_type and r.equipment_type != profile.equipment_type:
                    continue
                blob = " ".join([str(r.extra.get("anchor") or "")] + [str(x) for x in r.extra.get("relevant_items", [])]).lower()
                if terms and not any(t in blob for t in terms):
                    continue
                hits.append(row)
            for row in hits[: limit * 3]:
                c = cand(p, row)
                if c is None:
                    continue
                if idx is not None and qv is not None and p.semantic_ok and "semantic" not in c.scores:
                    try:
                        v = idx.reconstruct(int(row))
                        c.scores["semantic"] = float(max(0.0, float(np.dot(qv[0], v))))
                    except Exception:
                        c.scores["semantic"] = 0.0
                added += 1
        return {"stage": "metadata_filter", "candidates": added, "terms": sorted(terms),
                "equipment_type": profile.equipment_type}

    @staticmethod
    def _metadata_score(rec: CanonicalRecord, profile: QueryProfile) -> float:
        score = 0.5
        if profile.equipment_type:
            score = 1.0 if rec.equipment_type == profile.equipment_type else 0.2
        if profile.mentioned_failure_modes and rec.label in profile.mentioned_failure_modes:
            score = min(1.0, score + 0.2)
        if rec.dataset == "failure_iq":
            anchor = str(rec.extra.get("anchor") or "")
            q = profile.normalized_query.lower()
            if anchor and anchor in q:
                score = min(1.0, score + 0.3)
            terms = [k.replace("_", " ") for k in list(profile.qualitative) + list(profile.sensors)]
            blob = anchor + " " + " ".join(str(x) for x in rec.extra.get("relevant_items", []))
            if any(t in blob for t in terms):
                score = min(1.0, score + 0.3)
        return score

    def historical_support(self, neighbors: List[Neighbor], ref: ReferenceStats, mode: str,
                           synthetic_weight: float = 0.8) -> Dict[str, float]:
        """Similarity-weighted label vote among the nearest historical cases.
        In combined mode synthetic cases are down-weighted so that synthetic
        evidence can never out-vote equally close real evidence."""
        if not neighbors:
            return {}
        d = np.array([n.distance for n in neighbors])
        h = max(float(np.median(d)), 0.15)
        votes: Dict[str, float] = defaultdict(float)
        for n, di in zip(neighbors, d):
            if not n.record.label:
                continue
            wgt = float(np.exp(-0.5 * (di / h) ** 2)) * max(n.coverage, 0.2)
            if mode == "combined" and n.record.source_type == "synthetic":
                wgt *= synthetic_weight
            votes[n.record.label] += wgt
        tot = sum(votes.values()) or 1.0
        return {k: v / tot for k, v in votes.items()}

    @staticmethod
    def _reasons(c: Candidate, profile: QueryProfile) -> List[str]:
        r = []
        if c.numeric_distance is not None:
            r.append(f"similar sensor profile (robust distance {c.numeric_distance:.2f})")
        if c.scores.get("semantic", 0) > 0:
            r.append(f"semantic match {c.scores['semantic']:.2f}")
        if c.scores.get("qualitative", 0) > 0:
            r.append(f"matches reported directions ({c.scores['qualitative']:.2f})")
        if profile.equipment_type and c.record.equipment_type == profile.equipment_type:
            r.append(f"same equipment type ({profile.equipment_type})")
        if c.scores.get("historical", 0) >= 0.3:
            r.append(f"label supported by {c.scores['historical']:.0%} of nearest cases")
        return r

    @staticmethod
    def _diversify(ranked: List[Candidate], top_k: int, hist: Dict[str, float]) -> List[Candidate]:
        """Top-k by fused score, but make sure the two best-supported historical
        labels are both represented so verification can contrast them."""
        bundle = ranked[: max(top_k - 2, 1)]
        present = {c.record.label for c in bundle}
        for lab, _ in sorted(hist.items(), key=lambda kv: -kv[1])[:2]:
            if lab not in present:
                nxt = next((c for c in ranked if c.record.label == lab and c not in bundle), None)
                if nxt:
                    bundle.append(nxt)
                    present.add(lab)
        for c in ranked:
            if len(bundle) >= top_k:
                break
            if c not in bundle:
                bundle.append(c)
        return sorted(bundle, key=lambda c: -c.fused)[:top_k]


def _count(it):
    out: Dict[str, int] = defaultdict(int)
    for x in it:
        out[x] += 1
    return out
