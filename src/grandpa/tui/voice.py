"""Voice in the terminal interface: talk instead of typing, hear the reply.

* :class:`PushToTalk` records one phrase from the microphone and turns it into
  text with Grandpa's local speech-to-text. The text goes into the input box,
  so the user sees it before sending.
* :class:`ReplyVoice` reads Grandpa's replies aloud with Grandpa's own voice
  (the same voices the avatar uses).

Both run on worker threads, and both fail softly: no microphone, no speech
model or no voice means a message in the status line, never a crash.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class PushToTalk:
    """One recording at a time. ``start`` returns False when already recording."""

    def __init__(
        self,
        on_text: Callable[[str], None],
        on_error: Callable[[str], None],
        on_level: Callable[[float], None] | None = None,
        max_seconds: float = 12.0,
    ) -> None:
        self.on_text = on_text
        self.on_error = on_error
        self.on_level = on_level
        self.max_seconds = max_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def recording(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> bool:
        if self.recording:
            return False
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="grandpa-ptt", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Finish now; whatever was said so far is transcribed."""
        self._stop.set()

    def _run(self) -> None:
        try:
            from grandpa.voice.microphone import MicrophoneCapture
            from grandpa.voice.speech_input import SpeechInputEngine
        except Exception as exc:  # noqa: BLE001
            self.on_error(
                f"Voice input isn't installed ({exc}). Install: uv sync --extra voice"
            )
            return
        try:
            capture = MicrophoneCapture(
                duration_seconds=self.max_seconds, on_level=self.on_level
            )
            audio = capture.capture(stop_event=self._stop)
        except Exception as exc:  # noqa: BLE001 - no device, no driver, no permission
            message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
            self.on_error(f"Microphone: {message}")
            return
        if (
            not getattr(audio, "data", b"")
            or getattr(audio, "speech_detected", True) is False
        ):
            self.on_error("Didn't hear anything. Press F2 and speak.")
            return
        try:
            result = SpeechInputEngine().listen(
                audio_bytes=audio.data,
                audio_format=getattr(audio, "format", "wav"),
                trust_audio=True,
            )
        except Exception as exc:  # noqa: BLE001
            self.on_error(f"Speech to text failed: {exc}")
            return
        text = (getattr(result, "transcript", "") or "").strip()
        if not text:
            reason = getattr(result, "error", None) or "nothing recognised"
            self.on_error(f"Speech to text: {reason}")
            return
        self.on_text(text)


_MARKDOWN = re.compile(r"```.*?```|`[^`]*`|[*_#>|]+", re.S)


def speakable(text: str, limit: int = 600) -> str:
    """Reply text worth saying aloud: no code blocks, no markdown marks."""
    cleaned = _MARKDOWN.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit]


class ReplyVoice:
    """Says replies aloud, one at a time; a new reply replaces a queued one."""

    def __init__(self, on_error: Callable[[str], None]) -> None:
        self.on_error = on_error
        self.enabled = False
        self._speaker = None
        self._label = ""
        self._lock = threading.Lock()
        self._pending: str | None = None
        self._thread: threading.Thread | None = None

    @property
    def label(self) -> str:
        return self._label

    def say(self, text: str) -> None:
        text = speakable(text)
        if not self.enabled or not text:
            return
        with self._lock:
            self._pending = text
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run, name="grandpa-say", daemon=True
            )
            self._thread.start()

    def _load(self) -> bool:
        if self._speaker is not None:
            return True
        try:
            from grandpa.ui.lipsync import default_speaker

            self._speaker, self._label = default_speaker()
        except Exception as exc:  # noqa: BLE001
            self.on_error(f"Voice output isn't available: {exc}")
            self.enabled = False
            return False
        if self._speaker is None:
            self.on_error(f"No voice available ({self._label or 'none found'})")
            self.enabled = False
            return False
        return True

    def _run(self) -> None:
        while True:
            with self._lock:
                text, self._pending = self._pending, None
            if text is None or not self._load():
                return
            try:
                self._speaker.speak(text, lambda *_a, **_k: None)
            except Exception as exc:  # noqa: BLE001
                self.on_error(f"Speaking failed: {exc}")
                return


__all__ = ["PushToTalk", "ReplyVoice", "speakable"]
