"""Speech-to-text interface for the offline voice assistant."""

from __future__ import annotations

from typing import Protocol

from grandpa.voice.microphone import CapturedAudio
from grandpa.voice.speech_input import SpeechInputEngine


class SpeechToTextEngine(Protocol):
    """Protocol for future local STT providers."""

    def transcribe(self, audio: CapturedAudio) -> str:
        """Transcribe captured audio into normalized text."""


class FasterWhisperSpeechToText:
    """Offline STT adapter backed by Grandpa's existing faster-whisper path."""

    def __init__(
        self,
        *,
        language: str | None = None,
        model: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
        engine: SpeechInputEngine | None = None,
    ) -> None:
        self.language = language or None
        self._engine = engine or SpeechInputEngine(model=model, device=device, compute_type=compute_type)

    def transcribe(self, audio: CapturedAudio) -> str:
        result = self._engine.listen(
            audio_bytes=audio.data,
            audio_format=audio.format,
            language=self.language,
        )
        return " ".join(result.transcript.strip().split())


__all__ = ["FasterWhisperSpeechToText", "SpeechToTextEngine"]
