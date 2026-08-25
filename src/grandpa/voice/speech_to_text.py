"""Speech-to-text interface for the offline voice assistant."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

from grandpa.voice.errors import VoiceRecognitionError
from grandpa.voice.microphone import CapturedAudio
from grandpa.voice.speech_input import SpeechInputEngine, SpeechInputResult


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
        max_attempts: int = 1,
        retry_delay_seconds: float = 0.0,
    ) -> None:
        self.language = language or "en"
        self._engine = engine or SpeechInputEngine(
            model=model, device=device, compute_type=compute_type
        )
        self.max_attempts = max(1, max_attempts)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        self.last_result: SpeechInputResult | None = None

    def transcribe(self, audio: CapturedAudio) -> str:
        last_error: VoiceRecognitionError | None = None
        for attempt in range(self.max_attempts):
            try:
                result = self._engine.listen(
                    audio_bytes=audio.data,
                    audio_format=audio.format,
                    language=self.language,
                )
                transcript = " ".join(result.transcript.strip().split())
                if not transcript:
                    raise VoiceRecognitionError(
                        "I did not hear a complete phrase. Please try again.",
                        detail="The STT backend returned an empty transcript.",
                    )
                self.last_result = result
                return transcript
            except VoiceRecognitionError as exc:
                last_error = exc
                if attempt + 1 < self.max_attempts and self.retry_delay_seconds:
                    time.sleep(self.retry_delay_seconds)
        assert last_error is not None
        raise last_error

    def transcribe_file(self, path: str | Path) -> str:
        """Transcribe a closed WAV file with the same loaded production backend."""

        backend = self._engine._get_backend()
        result = backend.transcribe_file(path, language=self.language)
        return " ".join(result.text.strip().split())

    @property
    def backend_diagnostics(self):
        """Expose read-only diagnostics from the canonical backend."""

        backend = self._engine._get_backend()
        return getattr(backend, "last_diagnostics", None)


__all__ = ["FasterWhisperSpeechToText", "SpeechToTextEngine"]
