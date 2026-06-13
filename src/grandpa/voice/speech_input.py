"""Speech input abstraction for Grandpa voice mode."""

from __future__ import annotations

import importlib.util
import time
from dataclasses import dataclass
from typing import Any

from grandpa.voice.errors import MicrophoneUnavailableError, VoiceDependencyError, VoiceRecognitionError


@dataclass(frozen=True)
class SpeechInputResult:
    status: str
    transcript: str = ""
    engine: str = "none"
    latency_ms: float = 0.0
    confidence: float = 0.0
    language: str | None = None
    error: str | None = None
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "transcript": self.transcript,
            "text": self.transcript,
            "engine": self.engine,
            "latency_ms": self.latency_ms,
            "confidence": self.confidence,
            "language": self.language,
            "error": self.error,
            "fallback_reason": self.fallback_reason,
        }


class SpeechInputEngine:
    """Local-first speech input adapter.

    Audio transcription is intentionally best-effort. If local Whisper is not
    available, callers can still pass already-transcribed text from the browser
    speech runtime or mobile companion.
    """

    def __init__(self, preferred_engine: str = "auto") -> None:
        self.preferred_engine = preferred_engine
        self._last_result: SpeechInputResult | None = None

    def listen(
        self,
        *,
        text: str | None = None,
        audio_bytes: bytes | None = None,
        language: str | None = None,
    ) -> SpeechInputResult:
        started = time.perf_counter()
        if text is not None:
            result = SpeechInputResult(
                status="completed",
                transcript=text.strip(),
                engine="browser_or_mobile_transcript",
                latency_ms=_elapsed_ms(started),
                confidence=0.99 if text.strip() else 0.0,
                language=language,
            )
            self._last_result = result
            return result

        if audio_bytes:
            result = self._transcribe_audio(audio_bytes, started, language=language)
            self._last_result = result
            return result

        raise MicrophoneUnavailableError()

    def best_available_engine(self) -> str:
        if importlib.util.find_spec("faster_whisper") is not None:
            return "faster_whisper"
        if importlib.util.find_spec("whisper") is not None:
            return "whisper"
        return "push_to_talk_transcript"

    def diagnostics(self) -> dict[str, Any]:
        engine = self.best_available_engine()
        return {
            "status": "ready" if engine != "push_to_talk_transcript" else "push_to_talk",
            "engine": engine,
            "local_whisper_available": engine in {"faster_whisper", "whisper"},
            "browser_transcript_supported": True,
            "last_result": self._last_result.to_dict() if self._last_result else None,
            "truthful_note": "Local audio transcription requires Whisper/faster-whisper. Browser SpeechRecognition can send transcripts without cloud speech dependencies in Grandpa.",
        }

    def _transcribe_audio(self, audio_bytes: bytes, started: float, *, language: str | None) -> SpeechInputResult:
        engine = self.best_available_engine()
        if engine == "push_to_talk_transcript":
            raise VoiceDependencyError(detail="Local Whisper/faster-whisper is required to transcribe audio bytes.")
        raise VoiceRecognitionError(detail=f"Audio transcription adapter for {engine} is not enabled in this runtime.")


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


__all__ = ["SpeechInputEngine", "SpeechInputResult"]
