"""Interface for local cloned-voice inference engines."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LocalVoiceEngine(ABC):
    """Abstract base class for local voice generation engines."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "grandpa",
        speed: float = 1.0,
    ) -> bytes:
        """Synthesize text into WAV audio bytes."""

    @abstractmethod
    def health(self) -> bool:
        """Check if the local voice service/engine is healthy and reachable."""
