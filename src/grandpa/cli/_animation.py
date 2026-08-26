"""Shared lifecycle for the CLI's terminal animations.

Both the "Listening" indicator and the "Thinking" spinner run a daemon thread
that writes to a console stream. Daemon threads are frozen rather than joined
at interpreter shutdown, so one caught mid-write on stderr leaves the
``BufferedWriter`` lock held and CPython aborts the process with::

    Fatal Python error: _enter_buffered_busy: could not acquire lock for
    <_io.BufferedWriter name='<stderr>'> at interpreter shutdown,
    possibly due to daemon threads

Making the threads non-daemon is not the fix — that would hang any exit that
happens while an animation is running. The thread must simply be stopped
before finalization, and must not write once finalization has begun.

Three guards, cheapest first:

1. :meth:`TerminalAnimation.start` is idempotent — it stops a running thread
   rather than orphaning one that nothing can ever stop again.
2. Every live animation is stopped from an :mod:`atexit` hook, which runs
   before interpreter finalization begins.
3. Writes are skipped once :func:`sys.is_finalizing` is true, covering the
   window after the hook has already run.
"""

from __future__ import annotations

import atexit
import sys
import threading
import weakref
from typing import Any

#: Animations with a running thread. Weak so a dropped animation that was
#: already stopped does not keep its console alive until exit.
_LIVE: weakref.WeakSet[TerminalAnimation] = weakref.WeakSet()
_LIVE_LOCK = threading.Lock()


def stop_all_animations() -> None:
    """Stop every running animation. Registered with :mod:`atexit`.

    Best-effort and never raises — it runs during shutdown, when streams may
    already be closing.
    """
    with _LIVE_LOCK:
        live = list(_LIVE)
    for animation in live:
        try:
            animation.stop()
        except Exception:
            pass


atexit.register(stop_all_animations)


class TerminalAnimation:
    """A frame-based spinner driven by a daemon thread.

    Subclasses supply :attr:`frames` and :attr:`thread_name`, and set
    ``self._enabled`` to say whether the attached console can render it.
    """

    frames: tuple[str, ...] = ()
    thread_name: str = "grandpa-animation"

    def __init__(self, console: Any, *, interval: float = 0.1) -> None:
        self._console = console
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._enabled = True

    def start(self) -> None:
        """Start animating. Safe to call on an already-running animation."""
        if not self._enabled:
            return
        if self._thread is not None:
            # Never leave a thread running with nothing holding its stop event.
            self.stop()
        self._stop.clear()
        thread = threading.Thread(
            target=self._run,
            name=self.thread_name,
            daemon=True,
        )
        self._thread = thread
        with _LIVE_LOCK:
            _LIVE.add(self)
        thread.start()

    def stop(self) -> None:
        """Stop animating and clear the line. Safe to call when not running."""
        thread = self._thread
        self._thread = None
        with _LIVE_LOCK:
            _LIVE.discard(self)
        if thread is None:
            return
        self._stop.set()
        thread.join(timeout=1.0)
        self._clear_line()

    @property
    def running(self) -> bool:
        """True while a worker thread is attached."""
        return self._thread is not None

    def _run(self) -> None:
        index = 0
        while not self._stop.is_set():
            if sys.is_finalizing():
                return
            self._write(f"\r{self.frames[index % len(self.frames)]}")
            index += 1
            self._stop.wait(self._interval)

    def _clear_line(self) -> None:
        self._write("\r\033[2K")

    def _write(self, text: str) -> None:
        if sys.is_finalizing():
            return
        try:
            file = self._console.file
            file.write(text)
            file.flush()
        except Exception:
            # The stream can be closed or swapped underneath us during
            # teardown (pytest capture, CLI exit). Dropping a frame is fine.
            pass


__all__ = ["TerminalAnimation", "stop_all_animations"]
