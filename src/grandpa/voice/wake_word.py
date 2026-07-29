"""Local wake-word detection helpers for Grandpa voice mode.

This module intentionally does not provide always-on audio wake-word capture.
It detects configured phrases from local transcripts and stores safe foundation
state used by the API and simulated voice loop.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_WAKE_PHRASE = "hey grandpa"
DEFAULT_WAKE_PHRASES = ("grandpa", "hey grandpa", "hi grandpa", "wake grandpa")
DEFAULT_WAKE_WORD_SETTINGS = DEFAULT_CONFIG_DIR / "wake_word.json"


@dataclass(frozen=True)
class WakeWordConfig:
    """Wake phrase configuration."""

    enabled: bool = False
    phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES
    response_enabled: bool = True
    response_text: str = "Yes?"
    command_timeout_seconds: float = 10.0
    cooldown_seconds: float = 1.5

    @classmethod
    def from_env(cls) -> "WakeWordConfig":
        raw_enabled = os.getenv("GRANDPA_WAKE_WORD_ENABLED", "true").strip().lower()
        raw_phrases = os.getenv("GRANDPA_WAKE_WORDS", "")
        phrases = tuple(
            phrase.strip().lower()
            for phrase in raw_phrases.split(",")
            if phrase.strip()
        )
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


class WakeWordDetector:
    """Transcript-based wake phrase detector."""

    def __init__(
        self,
        config: WakeWordConfig | tuple[str, ...] | None = None,
        *,
        clock: Any = time.monotonic,
    ) -> None:
        if isinstance(config, WakeWordConfig):
            self.config = config
        elif config is None:
            self.config = WakeWordConfig(enabled=True)
        else:
            self.config = WakeWordConfig(enabled=True, phrases=tuple(config))
        self.clock = clock
        self._last_detection_at: float | None = None

    @property
    def phrases(self) -> tuple[str, ...]:
        return self.config.phrases

    def matches(self, transcript: str) -> bool:
        """Return True when transcript contains a configured wake phrase."""

        return self.detect(transcript, enforce_cooldown=False).matched

    def detect(
        self, transcript: str, *, enforce_cooldown: bool = True
    ) -> WakeWordMatch:
        text = normalize_wake_text(transcript)
        if not text or not self.config.enabled:
            return WakeWordMatch(matched=False, command_text=transcript.strip())

        words = text.split()
        for phrase in sorted(self.config.phrases, key=len, reverse=True):
            normalized_phrase = normalize_wake_text(phrase)
            phrase_words = normalized_phrase.split()
            match_index = _word_sequence_index(words, phrase_words)
            if match_index is None:
                continue
            now = float(self.clock())
            if (
                enforce_cooldown
                and self._last_detection_at is not None
                and now - self._last_detection_at < self.config.cooldown_seconds
            ):
                return WakeWordMatch(
                    matched=False,
                    command_text=transcript.strip(),
                    confidence=0.0,
                )
            command = " ".join(words[match_index + len(phrase_words) :]).strip()
            if enforce_cooldown:
                self._last_detection_at = now
            return WakeWordMatch(
                matched=True,
                phrase=phrase,
                command_text=command,
                confidence=0.95 if match_index == 0 else 0.82,
            )
        return WakeWordMatch(
            matched=False, command_text=transcript.strip(), confidence=0.0
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "phrases": list(self.config.phrases),
            "mode": "transcript_gate" if self.config.enabled else "disabled",
            "always_listening_available": False,
            "truthful_note": (
                "Wake phrases are detected from local transcripts. Push-to-talk remains "
                "the reliable mode unless a native wake engine is added."
            ),
        }


def normalize_wake_text(value: str) -> str:
    """Normalize a voice transcript for wake-word matching."""

    text = re.sub(r"[^\w\s]", " ", str(value).casefold())
    return re.sub(r"\s+", " ", text).strip()


def _word_sequence_index(words: list[str], phrase_words: list[str]) -> int | None:
    phrase_len = len(phrase_words)
    if not phrase_words or phrase_len > len(words):
        return None
    for index in range(len(words) - phrase_len + 1):
        if words[index : index + phrase_len] == phrase_words:
            return index
    return None


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
        detector = WakeWordDetector(
            WakeWordConfig(
                enabled=self.enabled and self.listening, phrases=(self.wake_phrase,)
            )
        )
        detected = detector.matches(text)
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
        self.settings_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )


__all__ = [
    "DEFAULT_WAKE_PHRASE",
    "DEFAULT_WAKE_PHRASES",
    "DEFAULT_WAKE_WORD_SETTINGS",
    "WakeWordConfig",
    "WakeWordDetector",
    "WakeWordMatch",
    "WakeWordSession",
    "normalize_wake_text",
]
