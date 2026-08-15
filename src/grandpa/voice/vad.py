"""Small local energy-based voice activity detector."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceActivityConfig:
    """Bounded speech and silence thresholds for phrase capture."""

    minimum_rms: float = 180.0
    noise_multiplier: float = 2.5
    minimum_speech_seconds: float = 0.25
    silence_seconds: float = 0.75
    maximum_utterance_seconds: float = 12.0


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

    def reset(self) -> None:
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
        threshold = max(
            self.config.minimum_rms,
            self._noise_floor * self.config.noise_multiplier,
        )
        is_speech = rms >= threshold
        if is_speech:
            self._speech_active_seconds += duration
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

        if self._elapsed >= self.config.maximum_utterance_seconds:
            self._finalization_reason = "maximum_duration"
            return True
        finalized = (
            self._speech_started
            and self._silence_after_speech >= self.config.silence_seconds
        )
        if finalized:
            self._finalization_reason = "trailing_silence"
        return finalized


__all__ = ["VoiceActivityConfig", "VoiceActivityDetector"]
