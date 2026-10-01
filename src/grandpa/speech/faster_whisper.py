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

    #: Why the transcript came back empty, when it did. An empty transcript used
    #: to be indistinguishable from the four different things that cause one,
    #: and the only trace was a logger.info with no file handler unless
    #: --verbose, so a live failure left nothing to read.
    #:
    #: "no_segments"         Whisper decoded nothing at all.
    #: "segments_filtered"   it decoded segments and the confidence filter
    #:                       dropped every one.
    #: "repetition_filtered" it decoded a degenerate loop.
    #: ""                    the transcript is not empty.
    empty_reason: str = ""
    segments_dropped: int = 0
    trusted_audio: bool = False


try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # type: ignore[assignment, misc]


def model_cache_dir() -> str:
    """Where Whisper model weights are downloaded and cached.

    Built without ``download_root``, ``WhisperModel`` falls back to the
    huggingface_hub default -- ``~/.cache/huggingface`` -- which is outside
    ``GRANDPA_HOME``. That put a several-hundred-megabyte download in a real user
    directory on first use, and made the write guard the only thing standing
    between the test suite and the same download: a guard that a
    ``real_writes`` marker is meant to be able to lift, at which point the
    download lands in the developer's own home.

    Resolving it here, from ``GRANDPA_HOME``, fixes it by construction instead.
    Read at call time rather than at import, for the reason recorded on
    ``config._in_config_dir``: an import-time constant is evaluated before
    anything has set ``GRANDPA_HOME``.
    """
    home = Path(os.environ.get("GRANDPA_HOME", Path.home() / ".grandpa")).expanduser()
    return str(home / "models" / "faster-whisper")


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
                        download_root=model_cache_dir(),
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
        trust_audio: bool = False,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using Faster-Whisper."""
        suffix = f".{format}" if not format.startswith(".") else format
        tmp_path = _write_closed_temp_audio(audio, suffix)
        try:
            return self.transcribe_file(
                tmp_path, language=language, trust_audio=trust_audio
            )
        finally:
            _delete_temp_audio(tmp_path)

    def transcribe_file(
        self,
        path: str | Path,
        *,
        language: str | None = None,
        trust_audio: bool = False,
    ) -> TranscriptionResult:
        """Transcribe a closed audio file through the canonical production path.

        ``trust_audio`` skips the confidence filter below as well as relaxing
        Whisper's own thresholds. See :func:`build_transcription_options`.
        """

        model = self._ensure_model()
        options = build_transcription_options(language, trust_audio=trust_audio)
        segments_iter, info = model.transcribe(str(path), **options)
        segments_list = list(segments_iter)

        # Filter segments based on confidence metadata to reject background
        # noise/hallucination.
        #
        # This is a second, stricter copy of a judgement Whisper has already
        # made: no_speech_prob > 0.45 against the no_speech_threshold of 0.5
        # passed above, and avg_logprob < -0.85 against the identical
        # log_prob_threshold. A segment Whisper kept can still be dropped here.
        # Trusted audio skips it, because the user holding a key down has
        # already answered the question it asks.
        valid_segments = []
        dropped = 0
        for seg in segments_list:
            no_speech = getattr(seg, "no_speech_prob", 0.0)
            avg_log = getattr(seg, "avg_logprob", 0.0)
            # Avoid type errors in unit tests where MagicMock returns mock objects for attributes
            if not trust_audio and isinstance(no_speech, (int, float)) and isinstance(
                avg_log, (int, float)
            ):
                if no_speech > 0.45 or avg_log < -0.85:
                    logger.info(
                        "Ignoring noisy segment %r (no_speech_prob=%f, avg_logprob=%f)",
                        seg.text,
                        no_speech,
                        avg_log,
                    )
                    dropped += 1
                    continue
            valid_segments.append(seg)

        # Build result
        text = "".join(seg.text for seg in valid_segments).strip()
        repetition_filtered = False
        if text and _is_hallucinated_repetition(text):
            logger.info("Ignoring degenerate repetitive hallucination: %r", text)
            text = ""
            valid_segments = []
            repetition_filtered = True

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
            empty_reason=_empty_reason(
                text, segments_list, dropped, repetition_filtered
            ),
            segments_dropped=dropped,
            trusted_audio=trust_audio,
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


def build_transcription_options(
    language: str | None = None, *, trust_audio: bool = False
) -> dict[str, Any]:
    """Return the single production decoding policy used for local STT.

    ``trust_audio`` is for audio whose provenance already answers the question
    these thresholds exist to ask. Push-to-talk is the case: the user held a key
    down for the duration of the utterance, so "is there speech here" has been
    settled by a person and Whisper suppressing the decode on its own estimate
    can only be wrong.

    Each threshold is set to ``None``, which is how faster-whisper disables the
    corresponding check -- all three are ``Optional[float]`` in 1.2.1. Nothing
    else changes, so the decode itself is identical; only the three places it
    could discard its own output are removed.
    """

    options: dict[str, Any] = {
        "beam_size": 1,
        "temperature": 0.0,
        "condition_on_previous_text": False,
        "initial_prompt": "Grandpa, Notepad, Chrome, Calculator, VS Code, Explorer, Settings, Terminal.",
        "vad_filter": False,
        # Stricter than faster-whisper's own defaults of 0.6 and -1.0. Kept, so
        # the automatic path is unchanged by this commit.
        "no_speech_threshold": None if trust_audio else 0.5,
        "compression_ratio_threshold": None if trust_audio else 2.4,
        "log_prob_threshold": None if trust_audio else -0.85,
        "language": language or "en",
    }
    return options


def _empty_reason(
    text: str, segments_list: list[Any], dropped: int, repetition_filtered: bool
) -> str:
    """Name which of the four causes produced an empty transcript."""
    if text:
        return ""
    if repetition_filtered:
        return "repetition_filtered"
    if not segments_list:
        return "no_segments"
    if dropped:
        return "segments_filtered"
    # Whisper returned segments whose text was blank or whitespace.
    return "no_segments"


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


#: How many times a phrase must repeat before it is a loop rather than a person.
#:
#: This was 3, and 3 is what a person does when nothing is responding. It
#: discarded "Hello Grandpa. Hello Grandpa. Hello Grandpa." -- a correctly decoded
#: microphone test at no_speech_prob 0.4335 -- and reported "I could not
#: understand the audio."
#:
#: An earlier version of this note called 0.4335 "well inside every confidence
#: gate". It is not: the segment filter above cuts at 0.45, so correctly decoded
#: speech from this microphone passed by 0.0165. That margin is the measurement
#: that matters here. Speech on this device sits right at the boundary, so the
#: filter drops real sentences whenever it drifts the wrong side of it -- which
#: is why trusted audio skips it rather than having the number retuned.
#:
#: Repetition count is the signal that separates the two, and it is the only one
#: that does. Measured on this machine:
#:
#:   * gzip compression ratio does not. faster-whisper already rejects segments
#:     above 2.4; the discarded text scored 1.16, and a genuine 12x loop scores
#:     only 1.78. Whisper's own mechanism is right to keep both, and deferring to
#:     it would let short loops through.
#:   * the 65% dominance ratio does not. A phrase said three times and a phrase
#:     looped twelve times both score 1.00.
#:
#: Five, and the number came from the suite rather than from my corpus. I chose
#: eight first, on a set of cases I wrote myself; the existing tests then supplied
#: two I had not thought of and that I would have broken:
#:
#:     "I'm sorry." x5   and   "Thank you." x5   must be filtered
#:
#: Five satisfies those and the reported regression together -- "Hello Grandpa."
#: said three times is three repetitions and survives. The cost is that a genuine
#: "yes yes yes yes yes yes" is discarded, which is a real false positive and the
#: right trade: a person repeating a word six times is rare, and a decoder
#: emitting a phrase five times is not.
_MIN_LOOP_REPEATS = 5

#: Chunk sizes to test for a repeating period, in words.
#:
#: Was (1, 2, 3), which structurally cannot see a loop whose period is longer --
#: "I don't know." repeated fifteen times has a four-word period, and
#: "Subtitles by the Amara.org community" a six-word one. Both are classic
#: Whisper hallucinations and both were missed at every count threshold.
_LOOP_PERIODS = (1, 2, 3, 4, 5, 6)

#: Share of chunks the repeated phrase must account for. Unchanged.
_LOOP_DOMINANCE = 0.65


def _is_hallucinated_repetition(text: str) -> bool:
    """Return True if the transcribed text is a degenerate Whisper repetition loop.

    Strictly better than the rule it replaces in both directions: on the corpus
    in tests/speech/test_repetition_filter.py it keeps 15 of 15 real utterances
    (was 9) and catches 8 of 8 loops (was 5).
    """
    clean = re.sub(r"[^\w\s]", " ", text.lower()).strip()
    words = clean.split()
    if len(words) < 6:
        return False
    for n in _LOOP_PERIODS:
        chunks = [" ".join(words[i : i + n]) for i in range(0, len(words) - n + 1, n)]
        if len(chunks) < _MIN_LOOP_REPEATS:
            continue
        most_common = max(set(chunks), key=chunks.count)
        count = chunks.count(most_common)
        if count >= _MIN_LOOP_REPEATS and count / len(chunks) >= _LOOP_DOMINANCE:
            return True
    return False
