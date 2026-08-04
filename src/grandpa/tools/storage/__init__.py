"""Persistent searchable storage with lazy optional backends."""

from __future__ import annotations

import importlib
import logging

from grandpa.tools.storage._stubs import MemoryBackend, RetrievalResult

logger = logging.getLogger(__name__)
_BACKENDS = ("sqlite", "bm25", "faiss_backend", "colbert_backend", "hybrid", "dense")
_backends_loaded = False


def load_storage_backends() -> None:
    global _backends_loaded
    if _backends_loaded:
        return
    for module in _BACKENDS:
        try:
            importlib.import_module(f"grandpa.tools.storage.{module}")
        except ImportError as exc:
            logger.debug("Optional storage backend %s unavailable: %s", module, exc)
    _backends_loaded = True


def __getattr__(name: str):
    exports = {
        "Chunk": ("chunking", "Chunk"),
        "ChunkConfig": ("chunking", "ChunkConfig"),
        "chunk_text": ("chunking", "chunk_text"),
        "ContextConfig": ("context", "ContextConfig"),
        "inject_context": ("context", "inject_context"),
        "ingest_path": ("ingest", "ingest_path"),
        "read_document": ("ingest", "read_document"),
    }
    if name not in exports:
        raise AttributeError(name)
    module, attribute = exports[name]
    return getattr(
        importlib.import_module(f"grandpa.tools.storage.{module}"), attribute
    )


__all__ = [
    "Chunk",
    "ChunkConfig",
    "ContextConfig",
    "MemoryBackend",
    "RetrievalResult",
    "chunk_text",
    "inject_context",
    "ingest_path",
    "read_document",
    "load_storage_backends",
]
