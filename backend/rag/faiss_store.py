"""
FAISS vector store managing several named flat-L2 indexes.

Index names used by the system:
  - failure_iq       (real FailureSensorIQ records)
  - afrb             (real AFRB records — the original 50k-vector index is reused)
  - afrb_synthetic   (synthetic AFRB-schema records, kept in a SEPARATE index so
                      real and synthetic data are never mixed on disk)

FAISS is kept exactly as before (IndexFlatL2).  What changed is how it is
used: ``search_raw`` exposes distances/row ids so the multi-stage retriever
can fuse semantic scores with metadata, numeric and historical signals, and a
small ``{name}_meta.json`` records which embedder built each index.
"""

import json
import os
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import faiss
import numpy as np

from rag.embedder import Embedder
from utils.logger import setup_logger

logger = setup_logger(__name__)

LEGACY_EMBEDDER_ID = "sentence-transformers:all-MiniLM-L6-v2"


class FAISSStore:
    """Manages multiple named FAISS flat-L2 indexes with document stores."""

    def __init__(self, embedder: Embedder):
        self.embedder = embedder
        self.indexes: Dict[str, faiss.IndexFlatL2] = {}
        self.doc_stores: Dict[str, List[Dict]] = {}
        self.meta: Dict[str, Dict] = {}
        self.persist_path = Path(os.getenv("FAISS_INDEX_PATH", "./faiss_indexes"))
        self.persist_path.mkdir(parents=True, exist_ok=True)

    # ── Build ────────────────────────────────────────────────────────────────

    def build_index(self, name: str, documents: List[Dict]) -> None:
        logger.info("Building FAISS index '%s' with %d docs …", name, len(documents))
        texts = [doc["content"] for doc in documents]
        embeddings = self.embedder.embed(texts)
        index = faiss.IndexFlatL2(embeddings.shape[1])
        index.add(embeddings)
        self.indexes[name] = index
        self.doc_stores[name] = documents
        self.meta[name] = {"embedder": self.embedder.model_id, "count": len(documents)}
        self._save(name)
        logger.info("Index '%s' built and saved (%d vectors).", name, index.ntotal)

    # ── Search ───────────────────────────────────────────────────────────────

    def is_compatible(self, name: str) -> bool:
        """True when the index was built by the currently loaded embedder."""
        built_with = self.meta.get(name, {}).get("embedder", LEGACY_EMBEDDER_ID)
        return built_with == self.embedder.model_id

    def search_raw(self, name: str, query_vec: np.ndarray, top_k: int) -> Tuple[np.ndarray, np.ndarray]:
        if name not in self.indexes:
            return np.empty((0,)), np.empty((0,), dtype=int)
        k = min(top_k, self.indexes[name].ntotal)
        distances, indices = self.indexes[name].search(query_vec, k)
        return distances[0], indices[0]

    def search(self, name: str, query: str, top_k: int = 5) -> List[Dict]:
        """Backward-compatible semantic search: [{content, metadata, score}]."""
        if name not in self.indexes:
            logger.warning("Index '%s' not found. Returning empty list.", name)
            return []
        query_vec = self.embedder.embed_single(query)
        distances, indices = self.search_raw(name, query_vec, top_k)
        results = []
        docs = self.doc_stores[name]
        for dist, idx in zip(distances, indices):
            if idx == -1:
                continue
            doc = docs[idx].copy()
            doc["score"] = float(1 / (1 + dist))
            results.append(doc)
        return results

    # ── Persistence ──────────────────────────────────────────────────────────

    def _save(self, name: str) -> None:
        try:
            faiss.write_index(self.indexes[name], str(self.persist_path / f"{name}.faiss"))
            with open(self.persist_path / f"{name}_docs.pkl", "wb") as f:
                pickle.dump(self.doc_stores[name], f)
            (self.persist_path / f"{name}_meta.json").write_text(json.dumps(self.meta.get(name, {})))
        except Exception as exc:
            logger.warning("Could not persist index '%s': %s", name, exc)

    def _load(self, name: str, expected_count: Optional[int] = None) -> bool:
        """Load a persisted index. Returns True on success."""
        idx_path = self.persist_path / f"{name}.faiss"
        docs_path = self.persist_path / f"{name}_docs.pkl"
        meta_path = self.persist_path / f"{name}_meta.json"
        if idx_path.exists() and docs_path.exists():
            try:
                index = faiss.read_index(str(idx_path))
                if expected_count is not None and index.ntotal != expected_count:
                    logger.warning("Persisted index '%s' has %d vectors, expected %d — ignoring cache.",
                                   name, index.ntotal, expected_count)
                    return False
                self.indexes[name] = index
                with open(docs_path, "rb") as f:
                    self.doc_stores[name] = pickle.load(f)
                self.meta[name] = json.loads(meta_path.read_text()) if meta_path.exists() else {
                    "embedder": LEGACY_EMBEDDER_ID, "count": index.ntotal}
                logger.info("Loaded persisted index '%s' (%d vectors).", name, index.ntotal)
                return True
            except Exception as exc:
                logger.warning("Could not load index '%s': %s", name, exc)
        return False

    def load_vectors_only(self, name: str, expected_count: int) -> bool:
        """Load only the .faiss file (documents come from the canonical records).
        Avoids unpickling the 90 MB legacy docs store at startup."""
        idx_path = self.persist_path / f"{name}.faiss"
        meta_path = self.persist_path / f"{name}_meta.json"
        if not idx_path.exists():
            return False
        try:
            index = faiss.read_index(str(idx_path))
        except Exception as exc:
            logger.warning("Could not read index '%s': %s", name, exc)
            return False
        if index.ntotal != expected_count:
            logger.warning("Index '%s' has %d vectors but %d records — needs rebuild.",
                           name, index.ntotal, expected_count)
            return False
        self.indexes[name] = index
        self.meta[name] = json.loads(meta_path.read_text()) if meta_path.exists() else {
            "embedder": LEGACY_EMBEDDER_ID, "count": index.ntotal}
        return True
