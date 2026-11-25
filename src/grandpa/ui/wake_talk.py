""""Hey Grandpa" for the orb.

The microphone stays open (16 kHz, in memory only) while wake listening is
on. When the phrase is heard the ring turns to *listening* and what follows
goes through the controller exactly like hold-to-talk: same confirmations for
risky actions, same reply, same voice.

Two detectors, chosen at start:

* a trained ``hey_grandpa.onnx`` (openWakeWord) when one is installed --
  fastest and lightest;
* otherwise :class:`~grandpa.voice.wake_spotter.TranscriptWakeEngine`, which
  needs no training: it reads only the moments someone speaks.

Listening pauses by itself while Grandpa is busy or speaking (so his own
voice saying "Grandpa" cannot wake him) and for two seconds after.
The on/off choice is kept in ``<grandpa home>/orb.json``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: Phrases removed from the front of what was said after the wake.
STRIP_PHRASES = (
    "hey grandpa", "hi grandpa", "hello grandpa", "ok grandpa", "okay grandpa",
    "hey grand pa", "hey granpa", "hey grampa", "grandpa", "granpa", "grampa",
)

AFTER_BUSY_SECONDS = 1.5
"""Quiet time after a reply, so the tail of Grandpa's own voice is not heard."""


def settings_path() -> Path:
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / "orb.json"


def load_wake_enabled(default: bool = True) -> bool:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        value = data.get("wake")
        return bool(value) if isinstance(value, bool) else default
    except (OSError, ValueError, AttributeError):
        return default


def save_wake_enabled(enabled: bool) -> None:
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data["wake"] = bool(enabled)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def strip_wake(text: str) -> str:
    from grandpa.voice.wake_word import strip_leading_wake_phrase

    return strip_leading_wake_phrase(str(text or ""), STRIP_PHRASES)


class WakeToTalk:
    """Keeps the wake detector running and hands each wake to the controller."""

    def __init__(
        self,
        controller: Any,
        bridge: Any,
        listen: Callable[[], Any],
        *,
        enabled: bool = True,
        engine_factory: Callable[..., Any] | None = None,
        listener_factory: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        spawn: Callable[[Callable[[], None]], None] | None = None,
        chime: Callable[[], None] | None = None,
    ) -> None:
        self.controller = controller
        self.bridge = bridge
        self.listen = listen
        self.enabled = enabled
        self.engine_factory = engine_factory or self._default_engine
        self.listener_factory = listener_factory or self._default_listener
        self.clock = clock
        self.spawn = spawn or (lambda job: threading.Thread(target=job, daemon=True).start())
        self.chime = chime if chime is not None else _chime
        self.label = ""
        self.error = ""
        self._listener: Any = None
        self._busy_until = 0.0
        self._lock = threading.Lock()

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> bool:
        """Open the microphone and start listening. False (with ``error``) if not."""
        with self._lock:
            if self._listener is not None:
                return True
            try:
                engine = self.engine_factory(self._on_model_wake, self._on_spoken_wake, self._gate)
                listener = self.listener_factory(engine, self._on_model_event)
                listener.start()
            except Exception as exc:  # noqa: BLE001 - no mic, no model: say so
                self.error = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
                logger.warning("wake listening unavailable", exc_info=True)
                return False
            self.label = str(getattr(engine, "label", "") or "")
            self.error = ""
            self._listener = listener
            return True

    def stop(self) -> None:
        with self._lock:
            listener, self._listener = self._listener, None
        if listener is not None:
            listener.stop()

    @property
    def running(self) -> bool:
        return self._listener is not None

    def set_enabled(self, enabled: bool) -> bool:
        """The orb's mic toggle. Turning off closes the microphone."""
        self.enabled = bool(enabled)
        try:
            save_wake_enabled(self.enabled)
        except OSError:
            logger.debug("could not save the wake setting", exc_info=True)
        if self.enabled:
            return self.start()
        self.stop()
        return True

    # --- deciding -----------------------------------------------------------

    def _gate(self) -> bool:
        """Listen only when on and Grandpa is idle (and a moment after)."""
        if not self.enabled:
            return False
        if getattr(self.controller, "busy", False):
            self._busy_until = self.clock() + AFTER_BUSY_SECONDS
            return False
        return self.clock() >= self._busy_until

    def _on_model_event(self, _event: Any) -> None:
        # openWakeWord's listener calls this for every detection
        if self._gate():
            self._on_model_wake()

    def _on_model_wake(self) -> None:
        self._wake(None)

    def _on_spoken_wake(self, samples: Any, match: Any) -> None:
        command = ""
        if getattr(match, "rest", 0) > 0:
            # "Hey Grandpa, open Notepad" in one breath: read it again with the
            # main speech model (better than tiny.en) and keep what follows.
            command = self._reread(samples)
        self._wake(command or None)

    def _reread(self, samples: Any) -> str:
        from grandpa.voice.microphone import CapturedAudio
        from grandpa.voice.wake_spotter import pcm_to_wav

        try:
            heard = self.bridge.transcribe(
                CapturedAudio(data=pcm_to_wav(samples), captured_frame_count=len(samples))
            )
        except Exception:  # noqa: BLE001 - fall back to asking
            logger.debug("re-reading the wake segment failed", exc_info=True)
            return ""
        return strip_wake(getattr(heard, "text", heard))

    def _wake(self, command: str | None) -> None:
        self.chime()
        self.spawn(lambda: self.controller.talk(lambda: self._command(command)))

    def _command(self, command: str | None) -> Any:
        """What the controller routes: the words said with the wake, else the
        next sentence. Nothing said is a silent return to idle."""
        if command:
            return command
        heard = self.listen()
        text = strip_wake(getattr(heard, "text", heard))
        return text or None


# --- defaults -------------------------------------------------------------------


def _default_engine(on_model_wake, on_spoken_wake, gate):
    """The trained model if there is one, else the speech check."""
    from grandpa.voice.wake_engine import (
        WakeEngineConfig,
        WakeEngineUnavailable,
        WakeWordEngine,
        resolve_wake_model,
    )

    try:
        resolved = resolve_wake_model("")
        return WakeWordEngine(WakeEngineConfig.from_env(), resolved=resolved)
    except WakeEngineUnavailable:
        pass
    from grandpa.voice.wake_spotter import TranscriptWakeEngine, WhisperSpotter

    spotter = WhisperSpotter()
    # load the small model now, off the audio thread, so the first wake is quick
    threading.Thread(target=_quietly(spotter.load), daemon=True).start()
    return TranscriptWakeEngine(on_spoken_wake, spotter=spotter, gate=gate)


def _default_listener(engine, on_event):
    from grandpa.voice.wake_engine import WakeWordListener

    return WakeWordListener(engine, on_event)


def _quietly(job: Callable[[], None]) -> Callable[[], None]:
    def run() -> None:
        try:
            job()
        except Exception:  # noqa: BLE001
            logger.warning("wake model load failed", exc_info=True)

    return run


def _chime() -> None:
    """A short, soft tone so you know he heard you (Windows only)."""
    try:
        import winsound

        threading.Thread(
            target=lambda: winsound.Beep(880, 90), daemon=True
        ).start()
    except Exception:  # noqa: BLE001 - no sound is fine
        pass


WakeToTalk._default_engine = staticmethod(_default_engine)  # type: ignore[attr-defined]
WakeToTalk._default_listener = staticmethod(_default_listener)  # type: ignore[attr-defined]

__all__ = [
    "WakeToTalk",
    "load_wake_enabled",
    "save_wake_enabled",
    "strip_wake",
]
