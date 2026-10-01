"""Speech-to-text interface for the offline voice assistant."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from grandpa.voice.errors import VoiceRecognitionError
from grandpa.voice.microphone import CapturedAudio
from grandpa.voice.speech_input import SpeechInputEngine, SpeechInputResult

#: What an empty ``reason`` means, for anything printing one.
EMPTY_REASONS = {
    "no_segments": "Whisper decoded no speech from it",
    "segments_filtered": "every decoded segment was dropped as low confidence",
    "repetition_filtered": "the decode came back as a repetition loop",
}


@dataclass(frozen=True)
class TrustedTranscript:
    """The result of transcribing audio that must not be refused.

    ``text`` empty is a legitimate outcome, not an error, and ``reason`` says
    which gate produced it. The counts are carried so a user who gets nothing
    back can see whether Whisper decoded anything at all.
    """

    text: str
    reason: str = ""
    segments_considered: int = 0
    segments_dropped: int = 0
    decoded_seconds: float = 0.0

    @property
    def explanation(self) -> str:
        """A sentence for the empty case."""
        return EMPTY_REASONS.get(self.reason, "nothing recognisable was in it")


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

    def transcribe_trusted(self, audio: CapturedAudio) -> TrustedTranscript:
        """Transcribe audio the user explicitly recorded. Never refuses it.

        Three things differ from :meth:`transcribe`:

        * Whisper's own ``no_speech``, ``log_prob`` and ``compression_ratio``
          suppression is disabled, and so is this project's stricter copy of the
          first two. Those thresholds exist to decide whether there is speech in
          the audio, and for push-to-talk a person has already decided.
        * an empty transcript comes back as an empty string with a reason,
          rather than as ``VoiceRecognitionError``. It is an answer, not a
          failure.
        * the reason names which gate emptied it, so an empty result is
          diagnosable instead of silent.

        The repetition filter is deliberately still in force. It does not judge
        the audio, it rejects a decoder failure mode -- a hundred words of "new,
        new, new" -- and reporting that plainly is more use than routing it.
        """
        result = self._engine.listen(
            audio_bytes=audio.data,
            audio_format=audio.format,
            language=self.language,
            trust_audio=True,
        )
        self.last_result = result
        transcript = " ".join(result.transcript.strip().split())
        diagnostics = self.backend_diagnostics
        return TrustedTranscript(
            text=transcript,
            reason="" if transcript else (result.fallback_reason or "no_segments"),
            segments_considered=len(getattr(diagnostics, "segments", ()) or ()),
            segments_dropped=int(getattr(diagnostics, "segments_dropped", 0) or 0),
            decoded_seconds=float(
                getattr(diagnostics, "decoded_duration_seconds", 0.0) or 0.0
            ),
        )

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


__all__ = [
    "EMPTY_REASONS",
    "FasterWhisperSpeechToText",
    "SpeechToTextEngine",
    "TrustedTranscript",
]
