"""Local wake-word detection helpers for Grandpa voice mode.

This module intentionally does not pretend to provide always-on audio wake
word detection. It detects configured phrases from already-local transcripts
and reports push-to-talk mode when no native wake engine is installed.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_WAKE_WORD_SETTINGS = DEFAULT_CONFIG_DIR / "wake_word.json"
DEFAULT_WAKE_PHRASE = "hey grandpa"


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


@dataclass
class WakeWordSession:
    """Safe wake-word foundation state.

    This class does not access microphones, start background threads, or run
    continuous audio detection. It only persists user intent and tests already
    provided text transcripts.
    """

    settings_path: Path | str = DEFAULT_WAKE_WORD_SETTINGS
    enabled: bool = False
    listening: bool = False
    last_detection_time: str | None = None
    wake_phrase: str = DEFAULT_WAKE_PHRASE

    def __post_init__(self) -> None:
        self.settings_path = Path(self.settings_path)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def enable(self) -> dict[str, Any]:
        self.enabled = True
        self.listening = True
        self._save()
        return self.status()

    def disable(self) -> dict[str, Any]:
        self.enabled = False
        self.listening = False
        self._save()
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "listening": self.listening,
            "last_detection_time": self.last_detection_time,
            "wake_phrase": self.wake_phrase,
            "always_listening": False,
            "microphone_required": False,
            "mode": "mock_transcript" if self.enabled else "disabled",
        }

    def detect_mock(self, text: str) -> dict[str, Any]:
        phrase = _normalise(self.wake_phrase)
        detected = bool(self.enabled and self.listening and phrase and phrase in _normalise(text))
        if detected:
            self.last_detection_time = datetime.now(UTC).isoformat()
        return {
            "detected": detected,
            "phrase": self.wake_phrase,
            "last_detection_time": self.last_detection_time,
        }

    def reset(self) -> dict[str, Any]:
        self.enabled = False
        self.listening = False
        self.last_detection_time = None
        self.wake_phrase = DEFAULT_WAKE_PHRASE
        self._save()
        return self.status()

    def _load(self) -> None:
        if not self.settings_path.exists():
            return
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.enabled = bool(data.get("enabled", False))
        self.listening = self.enabled
        phrase = str(data.get("wake_phrase") or DEFAULT_WAKE_PHRASE).strip()
        self.wake_phrase = phrase or DEFAULT_WAKE_PHRASE

    def _save(self) -> None:
        data = {
            "enabled": self.enabled,
            "wake_phrase": self.wake_phrase,
        }
        self.settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "DEFAULT_WAKE_PHRASE",
    "DEFAULT_WAKE_WORD_SETTINGS",
    "WakeWordConfig",
    "WakeWordDetector",
    "WakeWordMatch",
    "WakeWordSession",
]
