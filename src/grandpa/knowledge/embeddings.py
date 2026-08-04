"""Local embedding layer for Grandpa Knowledge Engine v2."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any

from grandpa.knowledge.indexing import tokenize

EMBEDDING_VERSION = "knowledge-v2"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
FALLBACK_MODEL = "deterministic-hash-v1"
FALLBACK_DIMENSIONS = 128


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model: str
    version: str
    backend: str
    true_semantic: bool
    created_at: float

    def to_record(self) -> dict[str, Any]:
        return {
            "embedding": self.vector,
            "embedding_model": self.model,
            "embedding_version": self.version,
            "backend": self.backend,
            "true_semantic": self.true_semantic,
            "created_at": self.created_at,
        }


class KnowledgeEmbedder:
    """Ollama-first local embedding adapter with deterministic fallback."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_EMBED_MODEL,
        fallback_dimensions: int = FALLBACK_DIMENSIONS,
    ) -> None:
        self.model = model
        self.fallback_dimensions = fallback_dimensions

    def status(self) -> dict[str, Any]:
        available = False
        error = ""
        forced_fallback = (
            os.getenv("GRANDPA_KNOWLEDGE_EMBEDDING_MODE", "").lower() == "fallback"
        )
        if forced_fallback:
            return {
                "status": "fallback",
                "preferred_model": self.model,
                "ollama_available": False,
                "fallback_available": True,
                "fallback_model": FALLBACK_MODEL,
                "embedding_version": EMBEDDING_VERSION,
                "true_semantic_available": False,
                "error": "",
                "local_only": True,
            }
        try:
            from grandpa.connectors.embeddings import OllamaEmbedder

            available = OllamaEmbedder(model=self.model, timeout=5.0).is_available()
        except Exception as exc:
            error = exc.__class__.__name__
        return {
            "status": "ready" if available else "fallback",
            "preferred_model": self.model,
            "ollama_available": available,
            "fallback_available": True,
            "fallback_model": FALLBACK_MODEL,
            "embedding_version": EMBEDDING_VERSION,
            "true_semantic_available": available,
            "error": error,
            "local_only": True,
        }

    def embed(self, text: str) -> EmbeddingResult:
        ollama = self._embed_with_ollama(text)
        if ollama:
            return ollama
        return EmbeddingResult(
            vector=deterministic_embedding(text, dimensions=self.fallback_dimensions),
            model=FALLBACK_MODEL,
            version=EMBEDDING_VERSION,
            backend="deterministic_fallback",
            true_semantic=False,
            created_at=time.time(),
        )

    def _embed_with_ollama(self, text: str) -> EmbeddingResult | None:
        if os.getenv("GRANDPA_KNOWLEDGE_EMBEDDING_MODE", "").lower() == "fallback":
            return None
        try:
            from grandpa.connectors.embeddings import OllamaEmbedder, decode_embedding

            embedder = OllamaEmbedder(model=self.model, timeout=8.0)
            if not embedder.is_available():
                return None
            blob = embedder.embed(text)
            arr = decode_embedding(blob)
            if arr is None:
                return None
            vector = [float(item) for item in arr.tolist()]
            return EmbeddingResult(
                vector=normalize_vector(vector),
                model=embedder.model_version,
                version=EMBEDDING_VERSION,
                backend="ollama",
                true_semantic=True,
                created_at=time.time(),
            )
        except Exception:
            return None


def deterministic_embedding(
    text: str, *, dimensions: int = FALLBACK_DIMENSIONS
) -> list[float]:
    """Create a stable lexical fallback vector without external services."""

    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * (1.0 + min(len(token), 16) / 16.0)
    return normalize_vector(vector)


def normalize_vector(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(item * item for item in vector))
    if magnitude <= 0:
        return vector
    return [item / magnitude for item in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def encode_vector(vector: list[float]) -> str:
    return json.dumps(vector, ensure_ascii=True, separators=(",", ":"))


def decode_vector(value: str) -> list[float]:
    try:
        loaded = json.loads(value or "[]")
        if isinstance(loaded, list):
            return [float(item) for item in loaded]
    except Exception:
        return []
    return []


__all__ = [
    "DEFAULT_EMBED_MODEL",
    "EMBEDDING_VERSION",
    "FALLBACK_MODEL",
    "KnowledgeEmbedder",
    "cosine_similarity",
    "decode_vector",
    "deterministic_embedding",
    "encode_vector",
]
