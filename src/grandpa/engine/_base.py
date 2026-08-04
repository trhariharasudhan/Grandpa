"""Shared engine utilities and re-exports."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Dict, List

from grandpa.core.types import Message
from grandpa.engine._stubs import InferenceEngine


class EngineConnectionError(Exception):
    """Raised when an engine is unreachable."""


class EngineModelNotFoundError(Exception):
    """Raised when an engine is reachable but the requested model is missing."""

    def __init__(self, model: str, message: str | None = None) -> None:
        self.model = model
        super().__init__(message or f"Model not found: {model}")


class EngineModelLoadError(Exception):
    """Raised when an engine cannot load an installed model."""

    def __init__(self, model: str, message: str, *, low_memory: bool = False) -> None:
        self.model = model
        self.low_memory = low_memory
        super().__init__(message)


class EngineModelPullError(Exception):
    """Raised when an explicitly requested model installation fails."""

    def __init__(self, model: str, message: str) -> None:
        self.model = model
        super().__init__(message)


def messages_to_dicts(messages: Sequence[Message]) -> List[Dict[str, Any]]:
    """Convert ``Message`` objects to OpenAI-format dicts."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        d: Dict[str, Any] = {"role": m.role.value, "content": m.content}
        if m.name:
            d["name"] = m.name
        if m.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments,
                    },
                }
                for tc in m.tool_calls
            ]
        if m.tool_call_id:
            d["tool_call_id"] = m.tool_call_id
        out.append(d)
    return out


def estimate_prompt_tokens(messages: Sequence[Message]) -> int:
    """Estimate full prompt token count from message content.

    Ollama's ``prompt_eval_count`` may report only *newly evaluated*
    tokens when KV-cache hits occur, under-counting the system prompt
    and earlier conversation turns.  This helper provides a
    cache-agnostic estimate so that downstream cost / FLOPs / energy
    calculations reflect the true prompt size — matching what a cloud
    provider would charge.

    Uses ~4 characters per token (standard BPE average for English) plus
    a small per-message overhead for role markers and separators.
    """
    total_chars = sum(len(m.content) for m in messages)
    # ~4 tokens overhead per message for role markers / separators
    overhead = len(messages) * 4
    return max(1, total_chars // 4 + overhead)


__all__ = [
    "EngineConnectionError",
    "EngineModelLoadError",
    "EngineModelNotFoundError",
    "EngineModelPullError",
    "InferenceEngine",
    "estimate_prompt_tokens",
    "messages_to_dicts",
]
