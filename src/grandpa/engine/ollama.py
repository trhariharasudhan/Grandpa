"""Ollama inference engine backend."""

from __future__ import annotations

from grandpa.core.registry import EngineRegistry
from grandpa.engine._stubs import InferenceEngine
from grandpa.runtime.ollama_adapter import (
    OllamaBackendAdapter,
    normalize_ollama_host,
)


@EngineRegistry.register("ollama")
class OllamaEngine(OllamaBackendAdapter, InferenceEngine):
    """Ollama inference engine backed by OllamaBackendAdapter."""

    engine_id = "ollama"


__all__ = [
    "OllamaEngine",
    "normalize_ollama_host",
]
