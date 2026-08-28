"""Backend adapter base class bridging engine providers to Grandpa ModelRuntime."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any, Dict, List

from grandpa.core.types import Message
from grandpa.runtime.interface import ModelRuntime


class BackendAdapter(ModelRuntime, ABC):
    """Base class for backend-specific adapters.

    Adapters translate Grandpa core primitives (Message, StreamChunk, ModelSpec)
    into the protocol expected by a target inference provider (e.g. Ollama, llama.cpp),
    and normalize provider responses back to Grandpa's standard dictionary format.
    """

    adapter_name: str = "base_adapter"

    @property
    def runtime_id(self) -> str:
        return self.adapter_name

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
        """Execute completion request on the target backend."""

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
        """Stream tokens from target backend."""
        yield ""  # pragma: no cover

    @abstractmethod
    def list_models(self) -> List[str]:
        """Query installed models from the target backend."""

    @abstractmethod
    def health(self) -> bool:
        """Probe backend health."""


__all__ = ["BackendAdapter"]
