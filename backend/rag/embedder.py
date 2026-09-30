"""
Sentence-Transformer embedding model wrapper.

* Caches the model at module level to avoid repeated loads.
* ``EMBEDDING_MODEL`` may be a hub name (default ``all-MiniLM-L6-v2``) or a
  local directory.
* If the model cannot be loaded (e.g. offline machine), a deterministic
  hashing embedder is used as a *labelled* fallback.  Indexes remember which
  embedder built them, and the retriever skips semantic search on an index
  whose embedder does not match rather than returning meaningless neighbours.
"""

import os
from typing import List

import numpy as np

from utils.logger import setup_logger

logger = setup_logger(__name__)

_MODEL_INSTANCE = None
_MODEL_ID: str = ""


class _HashingModel:
    """Deterministic bag-of-words hashing embedder (offline fallback)."""

    def __init__(self, dim: int = 384):
        from sklearn.feature_extraction.text import HashingVectorizer
        self.dim = dim
        self.vec = HashingVectorizer(n_features=dim, alternate_sign=False, norm="l2",
                                     ngram_range=(1, 2))

    def get_sentence_embedding_dimension(self) -> int:
        return self.dim

    def encode(self, texts, **_):
        return self.vec.transform(texts).toarray().astype(np.float32)


class Embedder:
    """Wrapper around a SentenceTransformer model for generating embeddings."""

    def __init__(self):
        global _MODEL_INSTANCE, _MODEL_ID
        model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        if _MODEL_INSTANCE is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info("Loading embedding model: %s", model_name)
                _MODEL_INSTANCE = SentenceTransformer(model_name, device=os.getenv("EMBEDDING_DEVICE", "cpu"))
                _MODEL_ID = "sentence-transformers:" + os.path.basename(model_name.rstrip("/\\"))
                logger.info("Embedding model loaded.")
            except Exception as exc:  # pragma: no cover - depends on environment
                logger.warning("Embedding model '%s' unavailable (%s). Using hashing fallback embedder.",
                               model_name, exc)
                _MODEL_INSTANCE = _HashingModel()
                _MODEL_ID = "hashing-fallback-384"
        self.model = _MODEL_INSTANCE
        self.model_id = _MODEL_ID
        self.dimension = self.model.get_sentence_embedding_dimension()

    def embed(self, texts: List[str]) -> np.ndarray:
        """Embed a list of strings -> float32 array (len(texts), dimension)."""
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        embeddings = self.model.encode(texts, show_progress_bar=False, convert_to_numpy=True,
                                       batch_size=64)
        return np.asarray(embeddings, dtype=np.float32)

    def embed_single(self, text: str) -> np.ndarray:
        return self.embed([text])
