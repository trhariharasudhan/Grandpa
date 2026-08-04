"""Inference Engine primitive — LLM runtime management."""

from __future__ import annotations

# Import engine modules to trigger @EngineRegistry.register() decorators
import grandpa.engine.ollama  # noqa: F401
from grandpa.engine._base import (
    EngineConnectionError,
    EngineModelLoadError,
    EngineModelNotFoundError,
    EngineModelPullError,
    InferenceEngine,
    messages_to_dicts,
)
from grandpa.engine._discovery import discover_engines, discover_models, get_engine

__all__ = [
    "EngineConnectionError",
    "EngineModelLoadError",
    "EngineModelNotFoundError",
    "EngineModelPullError",
    "InferenceEngine",
    "discover_engines",
    "discover_models",
    "get_engine",
    "messages_to_dicts",
]
