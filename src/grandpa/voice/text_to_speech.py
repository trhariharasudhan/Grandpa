"""Text-to-speech interface for the offline voice assistant."""

from __future__ import annotations

import re
import threading
from typing import Protocol

from grandpa.voice.speech_output import SpeechOutputEngine


class TextToSpeechEngine(Protocol):
    """Protocol for current and future local TTS providers."""

    def speak(self, text: str, stop_event: threading.Event | None = None) -> None:
        """Speak user-facing text."""

    def stop(self) -> None:
        """Stop current speech playback."""

    @property
    def is_speaking(self) -> bool:
        """Return whether audio playback is active."""

    def wait_until_finished(self, stop_event: threading.Event | None = None) -> bool:
        """Wait for playback, returning False when interrupted."""


class GrandpaTextToSpeech:
    """Best-effort local TTS using Grandpa's existing speech output engine."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        voice: str = "",
        rate: int = 175,
        max_chars: int = 360,
    ) -> None:
        self.enabled = enabled
        self.max_chars = max_chars
        self._engine = SpeechOutputEngine(voice=voice, rate=rate, enabled=enabled)
        self._speaking = threading.Event()
        self._finished = threading.Event()
        self._finished.set()

    @property
    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    def speak(self, text: str, stop_event: threading.Event | None = None) -> None:
        if not self.enabled:
            return
        clean = clean_text_for_speech(text, max_chars=self.max_chars)
        if stop_event is None:
            self._finished.clear()
            self._speaking.set()
            try:
                res = self._engine.speak(clean, interrupt=True)
                if res is not None and getattr(res, "status", None) == "fallback":
                    raise RuntimeError(
                        f"TTS backend failed: {res.message}. Error: {res.error}"
                    )
            finally:
                self._speaking.clear()
                self._finished.set()
            return
        if stop_event.is_set():
            self.stop()
            return

        error: list[BaseException] = []

        def _worker() -> None:
            import sys

            initialized_com = False
            if sys.platform == "win32":
                try:
                    import pythoncom

                    pythoncom.CoInitialize()
                    initialized_com = True
                except Exception:
                    pass
            try:
                res = self._engine.speak(clean, interrupt=True)
                if res is not None and getattr(res, "status", None) == "fallback":
                    raise RuntimeError(
                        f"TTS backend failed: {res.message}. Error: {res.error}"
                    )
            except BaseException as exc:
                error.append(exc)
            finally:
                if initialized_com:
                    try:
                        import pythoncom

                        pythoncom.CoUninitialize()
                    except Exception:
                        pass

        thread = threading.Thread(
            target=_worker,
            name="grandpa-voice-tts",
            daemon=True,
        )
        self._finished.clear()
        self._speaking.set()
        thread.start()
        try:
            while thread.is_alive():
                thread.join(timeout=0.1)
                if stop_event.is_set():
                    self.stop()
                    return
            if error:
                raise error[0]
        finally:
            self._speaking.clear()
            self._finished.set()

    def wait_until_finished(self, stop_event: threading.Event | None = None) -> bool:
        while not self._finished.wait(timeout=0.05):
            if stop_event is not None and stop_event.is_set():
                self.stop()
                return False
        return stop_event is None or not stop_event.is_set()

    def stop(self) -> None:
        """Stop queued/current speech output best-effort."""

        self._engine.stop()
        self._speaking.clear()
        self._finished.set()


def clean_text_for_speech(text: str, *, max_chars: int = 360) -> str:
    """Remove markdown/code-heavy content before speaking a concise response."""

    value = re.sub(r"```.*?```", " ", str(text), flags=re.DOTALL)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"https?://\S+", "link", value)
    value = re.sub(r"[*_#>\[\]()]", " ", value)
    value = " ".join(value.split())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "..."


def list_system_voices() -> list[str]:
    """List local pyttsx3 voices when available."""

    try:
        pyttsx3 = __import__("pyttsx3")
        engine = pyttsx3.init()
        return [
            str(getattr(voice, "name", "") or getattr(voice, "id", ""))
            for voice in engine.getProperty("voices") or []
        ]
    except Exception:
        return []


__all__ = [
    "GrandpaTextToSpeech",
    "TextToSpeechEngine",
    "clean_text_for_speech",
    "list_system_voices",
]
