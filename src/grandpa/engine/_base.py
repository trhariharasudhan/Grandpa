"""Shared engine utilities and re-exports."""

from __future__ import annotations

from grandpa.engine._stubs import InferenceEngine
from grandpa.runtime.exceptions import (
    RuntimeConnectionError,
    RuntimeModelLoadError,
    RuntimeModelNotFoundError,
    RuntimeModelPullError,
)
from grandpa.runtime.utils import estimate_prompt_tokens, messages_to_dicts

# Engine exception aliases for backwards compatibility
EngineConnectionError = RuntimeConnectionError
EngineModelNotFoundError = RuntimeModelNotFoundError
EngineModelLoadError = RuntimeModelLoadError
EngineModelPullError = RuntimeModelPullError

__all__ = [
    "EngineConnectionError",
    "EngineModelLoadError",
    "EngineModelNotFoundError",
    "EngineModelPullError",
    "InferenceEngine",
    "estimate_prompt_tokens",
    "messages_to_dicts",
]
