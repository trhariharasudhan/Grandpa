"""Small local energy-based voice activity detector."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceActivityConfig:
    """Bounded speech and silence thresholds for phrase capture."""

    minimum_rms: float = 200.0
    noise_multiplier: float = 2.5
    minimum_speech_seconds: float = 0.25

    #: Consecutive sub-threshold audio that ends an utterance.
    #:
    #: Was 0.55, which at a 0.1s chunk means six chunks -- 0.6s -- of quiet. That
    #: is inside the range of an ordinary mid-sentence pause, so a sentence was
    #: cut at its first breath and Whisper received a fragment. Measured on a
    #: synthetic 2.8s sentence with a 0.6s internal pause:
    #:
    #:     0.55 -> captured 1.2s of 2.8s   TRUNCATED
    #:     0.70 -> captured 2.8s           intact
    #:     0.80 -> captured 2.8s           intact
    #:
    #: 0.70 is the first value that holds it together, so 0.80 is that plus one
    #: chunk of margin. The cost is 0.25s more latency after the speaker stops,
    #: which is the right trade against losing the sentence: a fragment does not
    #: merely fail, it makes the model invent words to fill the gap.
    silence_seconds: float = 0.80
    maximum_utterance_seconds: float = 12.0

    #: How long to wait for speech to begin before giving up on this capture.
    #:
    #: There was no such bound. Every ``return True`` below is gated on
    #: ``_speech_started``, and the caller's utterance cap is only checked after
    #: speech starts -- so if nothing ever crossed the threshold the capture loop
    #: read frames forever. Demonstrated with synthetic audio: at amplitudes 0,
    #: 50 and 179 against a threshold of 180 the call never returned, having
    #: consumed the equivalent of over an hour of audio.
    #:
    #: That is what a user experiences as "Listening..." and then five to ten
    #: minutes of nothing at all.
    silence_before_speech_seconds: float = 8.0


class VoiceActivityDetector:
    """Track speech start/end using chunk RMS and an adaptive noise floor."""

    def __init__(self, config: VoiceActivityConfig | None = None) -> None:
        self.config = config or VoiceActivityConfig()
        self.reset()

    @property
    def speech_started(self) -> bool:
        return self._speech_started

    @property
    def noise_floor(self) -> float:
        return self._noise_floor

    @property
    def elapsed_seconds(self) -> float:
        return self._elapsed

    @property
    def speech_onset_seconds(self) -> float | None:
        return self._speech_onset_seconds

    @property
    def speech_active_seconds(self) -> float:
        return self._speech_active_seconds

    @property
    def trailing_silence_seconds(self) -> float:
        return self._silence_after_speech

    @property
    def finalization_reason(self) -> str | None:
        return self._finalization_reason

    @property
    def max_rms(self) -> float:
        """Loudest chunk seen. What to tell the user when nothing was loud enough."""
        return self._max_rms

    @property
    def speech_window_rms(self) -> float:
        """RMS of the chunks that cleared the threshold, and nothing else.

        Distinct from the whole-capture RMS, which is what the log used to
        report, and the difference is large enough to mislead: a capture whose
        speech chunks averaged 289 was reported as rms 176, because the buffer
        also holds 0.3s of pre-roll and 0.6s of trailing silence. Reading 176
        against a threshold of 180 suggests speech never crossed it, when in fact
        every speech chunk did.
        """
        if not self._speech_chunks:
            return 0.0
        return math.sqrt(self._speech_square_sum / self._speech_chunks)

    @property
    def current_threshold(self) -> float:
        """The level a chunk must reach right now to count as speech."""
        return max(
            self.config.minimum_rms,
            self._noise_floor * self.config.noise_multiplier,
        )

    def reset(self) -> None:
        # Survives reset on purpose. A false start -- speech detected, then too
        # short to keep -- calls reset(), which would restart the no-speech clock
        # and let a stream of clicks or door slams hold the capture open forever.
        # This clock measures the whole capture, not the current attempt.
        self._wall_elapsed = getattr(self, "_wall_elapsed", 0.0)
        self._max_rms = getattr(self, "_max_rms", 0.0)
        self._speech_square_sum = 0.0
        self._speech_chunks = 0
        self._elapsed = 0.0
        self._speech_seconds = 0.0
        self._silence_after_speech = 0.0
        self._noise_floor = 0.0
        self._noise_samples = 0
        self._speech_started = False
        self._speech_onset_seconds: float | None = None
        self._speech_active_seconds = 0.0
        self._finalization_reason: str | None = None

    def observe(self, rms: float, chunk_seconds: float) -> bool:
        """Return True when the utterance should stop."""

        duration = max(0.0, chunk_seconds)
        self._elapsed += duration
        self._wall_elapsed += duration
        self._max_rms = max(self._max_rms, float(rms))
        threshold = max(
            self.config.minimum_rms,
            self._noise_floor * self.config.noise_multiplier,
        )
        is_speech = rms >= threshold
        if is_speech:
            self._speech_active_seconds += duration
            self._speech_square_sum += float(rms) * float(rms)
            self._speech_chunks += 1
        if not self._speech_started:
            if is_speech:
                self._speech_seconds += duration
                if self._speech_seconds >= self.config.minimum_speech_seconds:
                    self._speech_started = True
                    self._speech_onset_seconds = max(
                        0.0, self._elapsed - self._speech_seconds
                    )
            else:
                self._speech_seconds = 0.0
                self._noise_samples += 1
                weight = 1.0 / min(self._noise_samples, 20)
                self._noise_floor = (1.0 - weight) * self._noise_floor + weight * rms
        elif is_speech:
            self._silence_after_speech = 0.0
        else:
            self._silence_after_speech += duration

        if (
            self._speech_started
            and self._speech_active_seconds >= self.config.maximum_utterance_seconds
        ):
            self._finalization_reason = "maximum_duration"
            return True
        # The only path out of this function that does not require speech to have
        # started. Without it, a capture that never hears anything never returns.
        if (
            not self._speech_started
            and self.config.silence_before_speech_seconds > 0
            and self._wall_elapsed >= self.config.silence_before_speech_seconds
        ):
            self._finalization_reason = "no_speech_timeout"
            return True
        finalized = (
            self._speech_started
            and self._silence_after_speech >= self.config.silence_seconds
        )
        if finalized:
            if self._speech_active_seconds < self.config.minimum_speech_seconds:
                self.reset()
                return False
            self._finalization_reason = "silence_timeout"
        return finalized


__all__ = ["VoiceActivityConfig", "VoiceActivityDetector"]
