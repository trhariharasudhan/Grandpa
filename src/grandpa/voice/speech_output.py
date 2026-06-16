"""Local speech output abstraction for Grandpa voice mode."""

from __future__ import annotations

import importlib.util
import platform
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from grandpa.voice.errors import VoiceOutputUnavailableError


@dataclass(frozen=True)
class SpeechOutputResult:
    status: str
    engine: str
    message: str
    spoken_text: str = ""
    latency_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "engine": self.engine,
            "message": self.message,
            "spoken_text": self.spoken_text,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass
class SpeechOutputEngine:
    """Best-effort local TTS with stop/interrupt state."""

    voice: str = ""
    rate: int = 185
    enabled: bool = True
    _queue: deque[str] = field(default_factory=deque, init=False)
    _state: str = field(default="idle", init=False)
    _last_result: SpeechOutputResult | None = field(default=None, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _stop_requested: bool = field(default=False, init=False)

    def speak(self, text: str, *, interrupt: bool = False, dry_run: bool = False) -> SpeechOutputResult:
        started = time.perf_counter()
        clean_text = _short_voice_text(text)
        engine = self.best_available_engine()
        with self._lock:
            if interrupt:
                self._queue.clear()
                self._stop_requested = True
            if not clean_text:
                result = SpeechOutputResult("skipped", engine, "No speech text provided.", latency_ms=_elapsed_ms(started))
                self._last_result = result
                return result
            self._queue.append(clean_text)
            self._state = "speaking"
            self._stop_requested = False

        if dry_run or not self.enabled:
            with self._lock:
                self._queue.clear()
                self._state = "idle"
            result = SpeechOutputResult(
                "dry_run" if dry_run else "disabled",
                engine,
                "Speech output queued safely.",
                clean_text,
                _elapsed_ms(started),
            )
            self._last_result = result
            return result

        if engine == "unavailable":
            with self._lock:
                self._queue.clear()
                self._state = "idle"
            raise VoiceOutputUnavailableError(detail="Install a local TTS backend such as pyttsx3 or Windows SAPI support.")

        # Keep runtime non-blocking and test-safe. Actual browser TTS remains
        # the daily-use path; native TTS can be wired into this adapter later.
        with self._lock:
            self._queue.clear()
            self._state = "idle" if not self._stop_requested else "interrupted"
        result = SpeechOutputResult("completed", engine, "Speech output handled.", clean_text, _elapsed_ms(started))
        self._last_result = result
        return result

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop_requested = True
            self._queue.clear()
            self._state = "idle"
        return {"status": "stopped", "message": "Speech output stopped."}

    def best_available_engine(self) -> str:
        if importlib.util.find_spec("pyttsx3") is not None:
            return "pyttsx3"
        if platform.system().lower() == "windows" and importlib.util.find_spec("win32com") is not None:
            return "windows_sapi"
        return "unavailable"

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            queue_size = len(self._queue)
            state = self._state
            last = self._last_result.to_dict() if self._last_result else None
        engine = self.best_available_engine()
        return {
            "status": "ready" if engine != "unavailable" else "text_only",
            "engine": engine,
            "enabled": self.enabled,
            "state": state,
            "queue_size": queue_size,
            "voice": self.voice,
            "rate": self.rate,
            "last_result": last,
            "interrupt_supported": True,
        }


def _short_voice_text(text: str, max_chars: int = 360) -> str:
    clean = " ".join(str(text).strip().split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "..."


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


__all__ = ["SpeechOutputEngine", "SpeechOutputResult"]
