"""
Runtime wiring: embedder → FAISS store → knowledge bases → orchestrator.

Used by the FastAPI app (main.py), the benchmark and the tests so that every
entry point runs exactly the same pipeline.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from data_loader.afrb_loader import AFRBLoader, record_to_document
from data_loader.failure_iq_loader import FailureIQLoader
from harness.canonical import CanonicalRecord
from harness.knowledge_base import KnowledgeBase
from rag.embedder import Embedder
from rag.faiss_store import FAISSStore
from utils.logger import setup_logger

logger = setup_logger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SYNTHETIC_CSV = BACKEND_DIR / "data" / "synthetic" / "afrb_synthetic.csv"

INDEX_NAMES = {
    ("afrb", "real"): "afrb",
    ("afrb", "synthetic"): "afrb_synthetic",
    ("failure_iq", "real"): "failure_iq",
}


class Runtime:
    def __init__(self):
        self.embedder: Optional[Embedder] = None
        self.store: Optional[FAISSStore] = None
        self.kbs: Dict[str, KnowledgeBase] = {}
        self.data_quality: Dict[str, Dict] = {}
        self.orchestrator = None

    # ── loading ──────────────────────────────────────────────────────────────
    def _attach_partition(self, kb: KnowledgeBase, source_type: str, records: List[CanonicalRecord],
                          allow_build: bool = True) -> None:
        index_name = INDEX_NAMES[(kb.name, source_type)]
        ok = self.store.load_vectors_only(index_name, expected_count=len(records))
        if ok and not self._alignment_ok(index_name, records):
            logger.warning("Index '%s' is not aligned with the records — rebuilding.", index_name)
            ok = False
        if not ok and allow_build and records:
            logger.info("[BUILD] Embedding %d %s records for '%s' (one-off) …", len(records), source_type, index_name)
            self.store.build_index(index_name, [record_to_document(r) for r in records])
            ok = True
        semantic_ok = ok and self.store.is_compatible(index_name)
        if ok and not semantic_ok:
            logger.warning("Index '%s' was built with a different embedder — semantic stage disabled for it.", index_name)
        kb.add_partition(source_type, index_name, records, semantic_ok=semantic_ok)

    def _alignment_ok(self, index_name: str, records: List[CanonicalRecord]) -> bool:
        """Spot-check that FAISS row i really is record i (embeds 3 records)."""
        if not self.store.is_compatible(index_name) or not records:
            return True
        rows = sorted({0, len(records) // 2, len(records) - 1})
        vecs = self.embedder.embed([records[r].text for r in rows])
        for r, v in zip(rows, vecs):
            d, idx = self.store.search_raw(index_name, v.reshape(1, -1), 1)
            if not len(idx) or (idx[0] != r and d[0] > 1e-4):
                return False
        return True

    def load_afrb(self, real_csv: Optional[str] = None, synthetic_csv: Optional[str] = None,
                  allow_build: bool = True) -> KnowledgeBase:
        kb = KnowledgeBase("afrb")
        real_csv = real_csv or os.getenv("AFRB_CSV_PATH", str(BACKEND_DIR / "data" / "afrb_sample.csv"))
        synthetic_csv = synthetic_csv or os.getenv("AFRB_SYNTHETIC_CSV_PATH", str(DEFAULT_SYNTHETIC_CSV))
        if real_csv and Path(real_csv).exists():
            loader = AFRBLoader(real_csv, default_source_type="real")
            recs = loader.load_records("afrb")
            self.data_quality["afrb_real"] = loader.quality
            self._attach_partition(kb, "real", recs, allow_build)
        if synthetic_csv and Path(synthetic_csv).exists():
            loader = AFRBLoader(synthetic_csv, default_source_type="synthetic")
            recs = loader.load_records("afrb")
            self.data_quality["afrb_synthetic"] = loader.quality
            self._attach_partition(kb, "synthetic", recs, allow_build)
        self.kbs["afrb"] = kb
        return kb

    def load_failure_iq(self, allow_build: bool = True) -> KnowledgeBase:
        kb = KnowledgeBase("failure_iq")
        recs = FailureIQLoader().load_records()
        real = [r for r in recs if r.source_type == "real"]
        syn = [r for r in recs if r.source_type == "synthetic"]
        if real:
            self._attach_partition(kb, "real", real, allow_build)
        if syn:
            # fallback supplement only (CSV missing) — kept separate & labelled
            INDEX_NAMES[("failure_iq", "synthetic")] = "failure_iq_synthetic"
            self._attach_partition(kb, "synthetic", syn, allow_build)
        self.kbs["failure_iq"] = kb
        return kb

    # ── diagnosis ────────────────────────────────────────────────────────────
    async def diagnose(self, question: str, dataset_type: str, data_mode: str = "combined",
                       top_k: int = 8, exclude_record_ids: Sequence[str] = ()) -> Dict:
        kb = self.kbs.get(dataset_type)
        if kb is None:
            raise ValueError(f"Dataset '{dataset_type}' is not loaded.")
        modes = kb.available_modes()
        if data_mode not in modes:
            data_mode = modes[0] if modes else "real"
        return await self.orchestrator.run_harness(question=question, dataset_type=dataset_type,
                                                   data_mode=data_mode, kb=kb, embedder=self.embedder,
                                                   store=self.store, top_k=top_k,
                                                   exclude_record_ids=list(exclude_record_ids))


def build_runtime(load_afrb: bool = True, load_failure_iq: bool = True, allow_build: bool = True) -> Runtime:
    from agents.orchestrator import AgentOrchestrator
    rt = Runtime()
    rt.embedder = Embedder()
    rt.store = FAISSStore(rt.embedder)
    if load_afrb:
        try:
            rt.load_afrb(allow_build=allow_build)
        except Exception as exc:
            logger.warning("AFRB knowledge base unavailable: %s", exc)
    if load_failure_iq:
        try:
            rt.load_failure_iq(allow_build=allow_build)
        except Exception as exc:
            logger.warning("Failure IQ knowledge base unavailable: %s", exc)
    for kb in rt.kbs.values():               # warm up reference statistics / calibration
        for m in kb.available_modes():
            kb.reference(m)
    rt.orchestrator = AgentOrchestrator()
    return rt
