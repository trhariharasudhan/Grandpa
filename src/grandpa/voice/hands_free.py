"""B2: always listening for "Hey Grandpa", with barge-in.

``wake_engine.WakeWordListener`` turns the microphone into wake events on its
own reader thread. The voice session needs something calmer to talk to: "wait
until he is called", and "was he called while speaking?". ``WakeGate`` is that:
the listener puts each event in a small queue, and the session takes them out.

* ``wait_for_wake(stop, timeout)`` -- block until "Hey Grandpa" (or ``stop``,
  or the timeout). This is the always-listening idle state.
* ``clear()`` -- forget events heard while Grandpa was busy, so a "Hey Grandpa"
  said during a command does not wake him a second time afterwards.
* barge-in: ``VoiceSession`` polls the gate while a reply is playing; an event
  stops the speech and goes straight to listening for the next command.

The command itself is still captured by the session's ordinary VAD microphone
(speech start / trailing silence), so the gate only decides *when* to listen.
Audio stays in memory, exactly as in ``wake_engine``.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

from grandpa.voice.errors import MicrophoneUnavailableError
from grandpa.voice.wake_engine import WakeEvent, WakeWordEngine, WakeWordListener

logger = logging.getLogger(__name__)

#: How many un-taken events to keep. More than one is only ever stale.
_QUEUE_SIZE = 4


class WakeGate:
    """The always-listening "Hey Grandpa" source a ``VoiceSession`` waits on."""

    def __init__(
        self,
        engine: WakeWordEngine,
        *,
        device: int | str | None = None,
        sounddevice_module: Any = None,
        listener_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.engine = engine
        self._events: queue.Queue[WakeEvent] = queue.Queue(maxsize=_QUEUE_SIZE)
        factory = listener_factory or WakeWordListener
        self._listener = factory(
            engine,
            self._on_wake,
            device=device,
            sounddevice_module=sounddevice_module,
        )
        self._started = False

    @property
    def label(self) -> str:
        return self.engine.label

    @property
    def error(self) -> str:
        return str(getattr(self._listener, "error", "") or "")

    def _on_wake(self, event: WakeEvent) -> None:
        # Runs on the audio thread: never block it.
        try:
            self._events.put_nowait(event)
        except queue.Full:
            logger.debug("wake gate queue full; dropping %s", event)

    def start(self) -> None:
        if self._started:
            return
        self._listener.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self._listener.stop()

    close = stop

    def clear(self) -> None:
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                return

    def wait_for_wake(
        self, stop: threading.Event | None = None, timeout: float | None = None
    ) -> WakeEvent | None:
        """Return the next wake event, or None on ``stop``/timeout/dead mic."""

        step = 0.1
        remaining = timeout
        while stop is None or not stop.is_set():
            if self.error:
                raise MicrophoneStopped(self.error)
            wait = step if remaining is None else max(0.0, min(step, remaining))
            try:
                return self._events.get(timeout=wait)
            except queue.Empty:
                pass
            if remaining is not None:
                remaining -= wait
                if remaining <= 0:
                    return None
        return None

    def __enter__(self) -> "WakeGate":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


class MicrophoneStopped(MicrophoneUnavailableError):
    """The wake word's microphone stream died (unplugged, privacy switch...)."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"The wake-word microphone stopped: {detail}")


__all__ = ["MicrophoneStopped", "WakeGate"]
