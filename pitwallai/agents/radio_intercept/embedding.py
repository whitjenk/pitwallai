"""Shared sentence-transformer model and embedding cache."""

from __future__ import annotations

import threading
from collections import OrderedDict

from sentence_transformers import SentenceTransformer

_models: dict[str, SentenceTransformer] = {}
_model_lock = threading.Lock()


def get_embedding_model(model_name: str = "all-MiniLM-L6-v2") -> SentenceTransformer:
    """
    Return a process-wide shared SentenceTransformer instance.

    Args:
        model_name: HuggingFace / sentence-transformers model id.

    Returns:
        Loaded model (singleton per model name).
    """
    if model_name not in _models:
        with _model_lock:
            if model_name not in _models:
                _models[model_name] = SentenceTransformer(model_name)
    return _models[model_name]


class EmbeddingCache:
    """Bounded LRU cache for transcript embedding vectors."""

    def __init__(self, max_size: int = 512) -> None:
        self._max_size = max_size
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    def get(self, key: str) -> list[float] | None:
        """Return cached embedding vector if present."""
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, key: str, vector: list[float]) -> None:
        """Store embedding vector, evicting oldest when over capacity."""
        self._cache[key] = vector
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
