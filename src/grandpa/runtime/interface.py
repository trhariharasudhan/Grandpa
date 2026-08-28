"""Grandpa Model Runtime Interface — backend-independent LLM execution contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from grandpa.core.types import Message


@dataclass(slots=True)
class StreamChunk:
    """A single chunk from a streaming model response."""

    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    content_blocks: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None


@dataclass(slots=True)
class ResponseFormat:
    """Structured output configuration for model runtimes."""

    type: str = "json_object"
    schema: Optional[Dict[str, Any]] = field(default=None)


class ModelRuntime(ABC):
    """Abstract Base Class for Grandpa Model Runtime backends.

    All model execution in Grandpa (agents, tools, CLI, server) communicates
    through this interface, insulating the core platform from backend-specific
    protocols.
    """

    runtime_id: str
    is_cloud: bool = False

    @abstractmethod
    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Synchronous completion — returns a dict with ``content``, ``model``, and ``usage``."""

    @abstractmethod
    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield token strings as they are generated."""
        yield ""  # pragma: no cover

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Yield rich StreamChunks including tool_calls and finish_reason."""
        async for token in self.stream(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            yield StreamChunk(content=token)
        yield StreamChunk(finish_reason="stop")

    @abstractmethod
    def list_models(self) -> List[str]:
        """Return identifiers of models available on this runtime."""

    @abstractmethod
    def health(self) -> bool:
        """Return ``True`` when the runtime backend is reachable and healthy."""

    def close(self) -> None:
        """Release any held resources (HTTP sessions, sockets, file handles)."""

    def prepare(self, model: str) -> None:
        """Optional warm-up / pre-load hook called before inference."""


__all__ = ["ModelRuntime", "ResponseFormat", "StreamChunk"]
