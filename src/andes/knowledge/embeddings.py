"""Embedding providers.

``FakeEmbedder`` is deterministic and offline (feature hashing) so unit tests
need no model download. ``BGEM3Embedder`` wraps a local multilingual model.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

from andes.core.config import get_settings
from andes.core.vector import normalize

_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class Embedder(Protocol):
    dim: int

    def __call__(self, text: str) -> list[float]: ...


class FakeEmbedder:
    """Deterministic feature-hashing embedder (no model, no network)."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _bucket(self, token: str) -> int:
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") % self.dim

    def __call__(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _tokenize(text):
            vec[self._bucket(token)] += 1.0
        return normalize(vec)


class BGEM3Embedder:
    """Local multilingual embeddings via sentence-transformers (lazy import)."""

    def __init__(self, model_name: str = "BAAI/bge-m3", dim: int = 1024) -> None:
        self.dim = dim
        self._model = None
        self._model_name = model_name

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def __call__(self, text: str) -> list[float]:
        model = self._load()
        vec = model.encode(text, normalize_embeddings=True)
        return [float(x) for x in vec]


def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embeddings_provider == "bge-m3":
        return BGEM3Embedder(settings.embeddings_model, settings.embeddings_dim)
    return FakeEmbedder()
