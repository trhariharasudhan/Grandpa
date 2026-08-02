"""Faster-Whisper speech-to-text backend (local, CTranslate2-based)."""

from __future__ import annotations

import os
import tempfile
from typing import List, Optional

from grandpa.core.registry import SpeechRegistry
from grandpa.speech._stubs import Segment, SpeechBackend, TranscriptionResult

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # type: ignore[assignment, misc]


@SpeechRegistry.register("faster-whisper")
class FasterWhisperBackend(SpeechBackend):
    """Local speech-to-text using Faster-Whisper (CTranslate2)."""

    backend_id = "faster-whisper"

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "auto",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = select_compute_type(device, compute_type)
        self._model: Optional[WhisperModel] = None

    def _ensure_model(self) -> WhisperModel:
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            if WhisperModel is None:
                raise ImportError(
                    "faster-whisper is not installed. "
                    "Install with: uv sync --extra speech"
                )
            last_error: Exception | None = None
            for compute_type in _compute_type_candidates(self._device, self._compute_type):
                try:
                    self._model = WhisperModel(
                        self._model_size,
                        device=self._device,
                        compute_type=compute_type,
                    )
                    self._compute_type = compute_type
                    break
                except ValueError as exc:
                    last_error = exc
                    if not _is_float16_unsupported_error(exc):
                        raise
            if self._model is None and last_error is not None:
                raise last_error
        return self._model

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using Faster-Whisper."""
        model = self._ensure_model()

        suffix = f".{format}" if not format.startswith(".") else format
        tmp_path = _write_closed_temp_audio(audio, suffix)
        try:
            kwargs = {}
            if language:
                kwargs["language"] = language
            kwargs["initial_prompt"] = "Grandpa assistant. Ollama. The current year may be 2026."

            segments_iter, info = model.transcribe(tmp_path, **kwargs)
            segments_list = list(segments_iter)
        finally:
            _delete_temp_audio(tmp_path)

        # Build result
        text = "".join(seg.text for seg in segments_list).strip()
        segments = [
            Segment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                confidence=None,
            )
            for seg in segments_list
        ]

        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            confidence=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", 0.0),
            segments=segments,
        )

    def health(self) -> bool:
        """Check if model is loaded or loadable."""
        if self._model is not None:
            return True
        return WhisperModel is not None

    def supported_formats(self) -> List[str]:
        """Supported audio formats (same as ffmpeg/Whisper)."""
        return ["wav", "mp3", "m4a", "ogg", "flac", "webm"]


def select_compute_type(device: str = "auto", compute_type: str = "auto") -> str:
    """Choose a safe faster-whisper compute type for the requested device."""

    requested = (compute_type or "auto").strip().lower()
    selected_device = (device or "auto").strip().lower()
    if requested not in {"", "auto", "default"}:
        if requested == "float16" and selected_device in {"auto", "cpu"}:
            return "int8"
        return requested
    if selected_device in {"cuda", "gpu"}:
        return "float16"
    return "int8"


def _compute_type_candidates(device: str, compute_type: str) -> list[str]:
    primary = select_compute_type(device, compute_type)
    candidates = [primary]
    for fallback in ("int8", "float32"):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _is_float16_unsupported_error(exc: ValueError) -> bool:
    message = str(exc).lower()
    return "float16" in message and ("support" in message or "efficient" in message)


def _write_closed_temp_audio(audio: bytes, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(audio)
    except Exception:
        _delete_temp_audio(path)
        raise
    return path


def _delete_temp_audio(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
