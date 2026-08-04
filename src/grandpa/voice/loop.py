"""Safe continuous voice loop foundation.

This module models the state transitions for a future continuous voice loop
without accessing microphones, starting threads, or running background audio
capture. Wake and command inputs are explicitly simulated with text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from grandpa.voice.wake_word import WakeWordSession

VoiceLoopMode = Literal[
    "idle",
    "waiting_for_wake_word",
    "listening_for_command",
    "processing",
    "error",
]

VoiceCommandRouter = Callable[[str], dict[str, Any]]


@dataclass
class VoiceLoopSession:
    """Text-simulated foundation for continuous voice flow."""

    wake_word_session: WakeWordSession
    enabled: bool = False
    running: bool = False
    mode: VoiceLoopMode = "idle"
    last_wake_detected_at: str | None = None
    last_command_transcript: str | None = None
    last_error: str | None = None
    command_router: VoiceCommandRouter | None = field(default=None, repr=False)

    def enable(self) -> dict[str, Any]:
        self.enabled = True
        self.last_error = None
        return self.status()

    def disable(self) -> dict[str, Any]:
        self.enabled = False
        self.running = False
        self.mode = "idle"
        self.last_error = None
        return self.status()

    def start(self) -> dict[str, Any]:
        if not self.enabled:
            return self._fail("Voice loop is disabled.")
        if not self.wake_word_session.enabled:
            return self._fail(
                "Wake word must be enabled before starting the voice loop."
            )
        self.running = True
        self.mode = "waiting_for_wake_word"
        self.last_error = None
        return self.status()

    def stop(self) -> dict[str, Any]:
        self.running = False
        self.mode = "idle"
        self.last_error = None
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "mode": self.mode,
            "last_wake_detected_at": self.last_wake_detected_at,
            "last_command_transcript": self.last_command_transcript,
            "last_error": self.last_error,
            "microphone_required": False,
            "background_thread": False,
        }

    def simulate_wake(self, text: str) -> dict[str, Any]:
        if not self.running:
            return self._fail("Voice loop is not running.")
        wake = self.wake_word_session.detect_mock(text)
        if wake["detected"]:
            self.mode = "listening_for_command"
            self.last_wake_detected_at = wake["last_detection_time"]
            self.last_error = None
        else:
            self.mode = "waiting_for_wake_word"
        return {
            **self.status(),
            "detected": wake["detected"],
            "phrase": wake["phrase"],
        }

    def simulate_command(
        self,
        transcript: str,
        command_router: VoiceCommandRouter | None = None,
    ) -> dict[str, Any]:
        if not self.running:
            return self._fail("Voice loop is not running.")
        text = transcript.strip()
        if not text:
            return self._fail("I didn't hear anything.")

        router = command_router or self.command_router
        if router is None:
            return self._fail("Voice command router is unavailable.")

        self.mode = "processing"
        self.last_command_transcript = text
        self.last_error = None
        try:
            result = router(text)
        except Exception as exc:
            return self._fail(str(exc))

        self.mode = "waiting_for_wake_word" if self.running else "idle"
        return {
            **self.status(),
            "command": result,
        }

    def _fail(self, message: str) -> dict[str, Any]:
        self.last_error = message
        self.mode = "error"
        return {
            **self.status(),
            "error": message,
        }


__all__ = ["VoiceCommandRouter", "VoiceLoopMode", "VoiceLoopSession"]
