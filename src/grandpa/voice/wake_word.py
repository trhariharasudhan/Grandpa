"""Local wake-word detection helpers for Grandpa voice mode.

This module intentionally does not pretend to provide always-on audio wake
word detection. It detects configured phrases from already-local transcripts
and reports push-to-talk mode when no native wake engine is installed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WakeWordConfig:
    """Wake phrase configuration."""

    enabled: bool = True
    phrases: tuple[str, ...] = ("hey grandpa", "grandpa")
    timeout_seconds: float = 8.0

    @classmethod
    def from_env(cls) -> "WakeWordConfig":
        raw_enabled = os.getenv("GRANDPA_WAKE_WORD_ENABLED", "true").strip().lower()
        raw_phrases = os.getenv("GRANDPA_WAKE_WORDS", "")
        phrases = tuple(p.strip().lower() for p in raw_phrases.split(",") if p.strip())
        return cls(
            enabled=raw_enabled not in {"0", "false", "no", "off"},
            phrases=phrases or ("hey grandpa", "grandpa"),
        )


@dataclass(frozen=True)
class WakeWordMatch:
    matched: bool
    phrase: str = ""
    command_text: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "phrase": self.phrase,
            "command_text": self.command_text,
            "confidence": self.confidence,
        }


@dataclass
class WakeWordDetector:
    """Transcript-based wake phrase detector."""

    config: WakeWordConfig = field(default_factory=WakeWordConfig.from_env)

    def detect(self, transcript: str) -> WakeWordMatch:
        text = _normalise(transcript)
        if not text or not self.config.enabled:
            return WakeWordMatch(matched=False, command_text=transcript.strip())

        for phrase in sorted(self.config.phrases, key=len, reverse=True):
            normalized_phrase = _normalise(phrase)
            pattern = rf"(^|\b){re.escape(normalized_phrase)}(\b|$)"
            match = re.search(pattern, text)
            if not match:
                continue
            command = text[match.end() :].strip(" ,.!?")
            return WakeWordMatch(
                matched=True,
                phrase=phrase,
                command_text=command or text,
                confidence=0.95 if text.startswith(normalized_phrase) else 0.82,
            )
        return WakeWordMatch(matched=False, command_text=transcript.strip(), confidence=0.0)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "phrases": list(self.config.phrases),
            "mode": "transcript_gate" if self.config.enabled else "disabled",
            "always_listening_available": False,
            "truthful_note": "Wake phrases are detected from local transcripts. Push-to-talk remains the reliable mode unless a native wake engine is added.",
        }


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


__all__ = ["WakeWordConfig", "WakeWordDetector", "WakeWordMatch"]
