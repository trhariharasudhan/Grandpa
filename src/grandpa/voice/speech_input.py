"""Speech input abstraction for Grandpa voice mode."""

from __future__ import annotations

import importlib.util
import time
from dataclasses import dataclass
from typing import Any

from grandpa.voice.errors import (
    MicrophoneUnavailableError,
    VoiceDependencyError,
    VoiceRecognitionError,
)

SUPPORTED_LOCAL_AUDIO_FORMATS = {"wav", "mp3", "webm", "m4a"}


@dataclass(frozen=True)
class SpeechInputResult:
    status: str
    transcript: str = ""
    engine: str = "none"
    latency_ms: float = 0.0
    confidence: float = 0.0
    language: str | None = None
    duration_seconds: float = 0.0
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
            "duration_seconds": self.duration_seconds,
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
        self._backend: Any | None = None

    def listen(
        self,
        *,
        text: str | None = None,
        audio_bytes: bytes | None = None,
        audio_format: str = "wav",
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

        if audio_bytes is not None:
            result = self._transcribe_audio(
                audio_bytes,
                started,
                audio_format=audio_format,
                language=language,
            )
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
        status = self.stt_status()
        engine = status["engine"]
        return {
            "status": "ready" if status["ready"] else "push_to_talk",
            "engine": engine,
            "model": status["model"],
            "ready": status["ready"],
            "device": status["device"],
            "compute_type": status["compute_type"],
            "local_whisper_available": status["ready"],
            "browser_transcript_supported": True,
            "supported_audio_formats": sorted(SUPPORTED_LOCAL_AUDIO_FORMATS),
            "last_result": self._last_result.to_dict() if self._last_result else None,
            "truthful_note": "Local audio transcription requires Whisper/faster-whisper. Browser SpeechRecognition can send transcripts without cloud speech dependencies in Grandpa.",
        }

    def stt_status(self) -> dict[str, Any]:
        from grandpa.speech.faster_whisper import select_compute_type

        config = self._speech_config()
        engine = "faster_whisper" if importlib.util.find_spec("faster_whisper") is not None else "push_to_talk_transcript"
        device = getattr(config, "device", "auto")
        return {
            "engine": engine,
            "model": getattr(config, "model", "base"),
            "ready": engine == "faster_whisper",
            "device": device,
            "compute_type": select_compute_type(device, getattr(config, "compute_type", "auto")),
            "supported_audio_formats": sorted(SUPPORTED_LOCAL_AUDIO_FORMATS),
        }

    def _transcribe_audio(
        self,
        audio_bytes: bytes,
        started: float,
        *,
        audio_format: str,
        language: str | None,
    ) -> SpeechInputResult:
        if not audio_bytes:
            raise VoiceRecognitionError(detail="Empty audio was received.")

        normalized_format = audio_format.strip().lower().lstrip(".") or "wav"
        if normalized_format not in SUPPORTED_LOCAL_AUDIO_FORMATS:
            raise VoiceRecognitionError(
                detail=f"Unsupported audio format '{normalized_format}'. Use WAV, MP3, WEBM, or M4A."
            )

        if importlib.util.find_spec("faster_whisper") is None:
            raise VoiceDependencyError(detail="Local Whisper/faster-whisper is required to transcribe audio bytes.")

        try:
            backend = self._get_backend()
            result = backend.transcribe(audio_bytes, format=normalized_format, language=language)
        except ImportError as exc:
            raise VoiceDependencyError(
                "Voice mode is not fully installed.\nInstall it with:\nuv sync --extra speech\nThen retry the command.",
                detail=str(exc),
            ) from exc
        except FileNotFoundError as exc:
            raise VoiceDependencyError(
                "Local speech recognition needs ffmpeg to read this audio format.\nInstall ffmpeg and retry.",
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise VoiceRecognitionError(detail=str(exc)) from exc
        except RuntimeError as exc:
            message = str(exc)
            lowered = message.lower()
            if "ffmpeg" in lowered or "av" in lowered:
                raise VoiceDependencyError(
                    "Local speech recognition needs ffmpeg to read this audio format.\nInstall ffmpeg and retry.",
                    detail=message,
                ) from exc
            if "model" in lowered or "not found" in lowered or "download" in lowered:
                raise VoiceDependencyError(
                    "Local Whisper model is missing or could not be loaded.\nCheck the configured model and retry.",
                    detail=message,
                ) from exc
            raise VoiceRecognitionError(detail=message) from exc
        except Exception as exc:
            raise VoiceRecognitionError(detail=str(exc)) from exc

        transcript = result.text.strip()
        if not transcript:
            raise VoiceRecognitionError(detail="No speech was detected in the audio.")
        return SpeechInputResult(
            status="completed",
            transcript=transcript,
            engine="faster_whisper",
            latency_ms=_elapsed_ms(started),
            confidence=result.confidence or 0.0,
            language=result.language,
            duration_seconds=float(result.duration_seconds or 0.0),
        )

    def _get_backend(self) -> Any:
        if self._backend is None:
            self._backend = self._create_backend()
        return self._backend

    def _create_backend(self) -> Any:
        from grandpa.speech.faster_whisper import FasterWhisperBackend

        config = self._speech_config()
        return FasterWhisperBackend(
            model_size=getattr(config, "model", "base"),
            device=getattr(config, "device", "auto"),
            compute_type=getattr(config, "compute_type", "auto"),
        )

    def _speech_config(self) -> Any:
        from grandpa.core.config import load_config

        return load_config().speech


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


__all__ = ["SUPPORTED_LOCAL_AUDIO_FORMATS", "SpeechInputEngine", "SpeechInputResult"]
