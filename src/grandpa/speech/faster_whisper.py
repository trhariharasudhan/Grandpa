"""Faster-Whisper speech-to-text backend (local, CTranslate2-based)."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from grandpa.core.registry import SpeechRegistry
from grandpa.speech._stubs import Segment, SpeechBackend, TranscriptionResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FasterWhisperDiagnostics:
    """Details from the latest canonical Faster-Whisper invocation."""

    model: str
    options: dict[str, Any]
    decoded_duration_seconds: float
    language: str | None
    language_probability: float | None
    segments: tuple[dict[str, Any], ...]


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
        self.last_diagnostics: FasterWhisperDiagnostics | None = None

    def _ensure_model(self) -> WhisperModel:
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            if WhisperModel is None:
                raise ImportError(
                    "faster-whisper is not installed. "
                    "Install with: uv sync --extra speech"
                )
            last_error: Exception | None = None
            for compute_type in _compute_type_candidates(
                self._device, self._compute_type
            ):
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
        suffix = f".{format}" if not format.startswith(".") else format
        tmp_path = _write_closed_temp_audio(audio, suffix)
        try:
            return self.transcribe_file(tmp_path, language=language)
        finally:
            _delete_temp_audio(tmp_path)

    def transcribe_file(
        self, path: str | Path, *, language: str | None = None
    ) -> TranscriptionResult:
        """Transcribe a closed audio file through the canonical production path."""

        model = self._ensure_model()
        options = build_transcription_options(language)
        segments_iter, info = model.transcribe(str(path), **options)
        segments_list = list(segments_iter)

        # Filter segments based on confidence metadata to reject background noise/hallucination
        valid_segments = []
        for seg in segments_list:
            no_speech = getattr(seg, "no_speech_prob", 0.0)
            avg_log = getattr(seg, "avg_logprob", 0.0)
            # Avoid type errors in unit tests where MagicMock returns mock objects for attributes
            if isinstance(no_speech, (int, float)) and isinstance(
                avg_log, (int, float)
            ):
                if no_speech > 0.45 or avg_log < -0.85:
                    logger.info(
                        "Ignoring noisy segment %r (no_speech_prob=%f, avg_logprob=%f)",
                        seg.text,
                        no_speech,
                        avg_log,
                    )
                    continue
            valid_segments.append(seg)

        # Build result
        text = "".join(seg.text for seg in valid_segments).strip()
        if text and _is_hallucinated_repetition(text):
            logger.info("Ignoring degenerate repetitive hallucination: %r", text)
            text = ""
            valid_segments = []

        segments = [
            Segment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                confidence=None,
            )
            for seg in valid_segments
        ]

        result = TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            confidence=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", 0.0),
            segments=segments,
        )
        self.last_diagnostics = FasterWhisperDiagnostics(
            model=self._model_size,
            options=options,
            decoded_duration_seconds=float(getattr(info, "duration", 0.0) or 0.0),
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            segments=tuple(
                {
                    "start": float(getattr(segment, "start", 0.0)),
                    "end": float(getattr(segment, "end", 0.0)),
                    "text": str(getattr(segment, "text", "")).strip(),
                    "no_speech_probability": _numeric_or_none(
                        getattr(segment, "no_speech_prob", None)
                    ),
                    "average_log_probability": _numeric_or_none(
                        getattr(segment, "avg_logprob", None)
                    ),
                    "compression_ratio": _numeric_or_none(
                        getattr(segment, "compression_ratio", None)
                    ),
                }
                for segment in segments_list
            ),
        )
        return result

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


def build_transcription_options(language: str | None = None) -> dict[str, Any]:
    """Return the single production decoding policy used for local STT."""

    options: dict[str, Any] = {
        "beam_size": 1,
        "temperature": 0.0,
        "condition_on_previous_text": False,
        "initial_prompt": "Grandpa, Notepad, Chrome, Calculator, VS Code, Explorer, Settings, Terminal.",
        "vad_filter": False,
        "no_speech_threshold": 0.5,
        "compression_ratio_threshold": 2.4,
        "log_prob_threshold": -0.85,
        "language": language or "en",
    }
    return options


def _numeric_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


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


def _is_hallucinated_repetition(text: str) -> bool:
    """Return True if the transcribed text is a degenerate Whisper repetition loop."""
    clean = re.sub(r"[^\w\s]", " ", text.lower()).strip()
    words = clean.split()
    if len(words) >= 6:
        for n in (1, 2, 3):
            chunks = [
                " ".join(words[i : i + n]) for i in range(0, len(words) - n + 1, n)
            ]
            if len(chunks) >= 3:
                most_common = max(set(chunks), key=chunks.count)
                if chunks.count(most_common) / len(chunks) >= 0.65:
                    return True
    return False
