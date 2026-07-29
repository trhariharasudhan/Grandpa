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

    def reset(self) -> None:
        self._elapsed = 0.0
        self._speech_seconds = 0.0
        self._silence_after_speech = 0.0
        self._noise_floor = 0.0
        self._noise_samples = 0
        self._speech_started = False

    def observe(self, rms: float, chunk_seconds: float) -> bool:
        """Return True when the utterance should stop."""

        duration = max(0.0, chunk_seconds)
        self._elapsed += duration
        threshold = max(
            self.config.minimum_rms,
            self._noise_floor * self.config.noise_multiplier,
        )
        is_speech = rms >= threshold
        if not self._speech_started:
            if is_speech:
                self._speech_seconds += duration
                if self._speech_seconds >= self.config.minimum_speech_seconds:
                    self._speech_started = True
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
            return True
        return (
            self._speech_started
            and self._silence_after_speech >= self.config.silence_seconds
        )


__all__ = ["VoiceActivityConfig", "VoiceActivityDetector"]
