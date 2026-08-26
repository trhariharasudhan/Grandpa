"""Lifecycle guarantees for the CLI terminal animations.

These pin the fix for the interpreter-shutdown abort:

    Fatal Python error: _enter_buffered_busy: could not acquire lock for
    <_io.BufferedWriter name='<stderr>'> at interpreter shutdown,
    possibly due to daemon threads

The animations write to stderr from a daemon thread. A daemon thread is
frozen rather than joined at shutdown, so one still writing when the
interpreter finalizes holds the stream lock and aborts the process.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest
from rich.console import Console

from grandpa.cli._animation import TerminalAnimation, stop_all_animations
from grandpa.cli.chat_cmd import ThinkingAnimation
from grandpa.voice.presenter import ListeningAnimation, VoicePresenter


class _Spinner(TerminalAnimation):
    """Always-enabled animation writing to a real (captured) console."""

    frames = ("a", "b")
    thread_name = "grandpa-test-animation"

    def __init__(self, console, *, interval: float = 0.001) -> None:
        super().__init__(console, interval=interval)
        self._enabled = True


def _console() -> Console:
    return Console(force_terminal=True)


def _animation_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if "animation" in t.name and t.is_alive()]


def test_stop_joins_the_worker_thread():
    anim = _Spinner(_console())
    anim.start()
    assert anim.running
    thread = anim._thread
    anim.stop()
    assert not anim.running
    assert thread is not None and not thread.is_alive()


def test_restart_does_not_orphan_the_previous_thread():
    """start() on a running animation must stop the old thread, not leak it."""
    anim = _Spinner(_console())
    anim.start()
    first = anim._thread
    anim.start()
    second = anim._thread
    try:
        assert first is not second
        assert first is not None and not first.is_alive()
    finally:
        anim.stop()


def test_presenter_start_listening_twice_leaks_no_thread():
    """The presenter replaces the animation object on each start().

    Without stopping first, the previous object's thread had nothing left
    holding its stop event and ran until process exit.
    """
    before = len(_animation_threads())
    presenter = VoicePresenter(console=_console(), screen_reader=False, no_color=False)
    presenter.start_listening()
    presenter.start_listening()
    presenter.start_listening()
    try:
        assert len(_animation_threads()) <= before + 1
    finally:
        presenter.stop_listening()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and len(_animation_threads()) > before:
        time.sleep(0.01)
    assert len(_animation_threads()) == before


def test_stop_all_animations_stops_every_live_animation():
    anims = [_Spinner(_console()) for _ in range(3)]
    for a in anims:
        a.start()
    assert all(a.running for a in anims)
    stop_all_animations()
    assert not any(a.running for a in anims)


def test_write_is_skipped_once_the_interpreter_is_finalizing(monkeypatch):
    """The guard that prevents grabbing the stderr lock during shutdown."""
    written: list[str] = []

    class _Recorder:
        def write(self, text):
            written.append(text)

        def flush(self):
            pass

    class _Console:
        file = _Recorder()

    anim = _Spinner(_Console())
    monkeypatch.setattr(sys, "is_finalizing", lambda: True)
    anim._write("frame")
    assert written == []

    monkeypatch.setattr(sys, "is_finalizing", lambda: False)
    anim._write("frame")
    assert written == ["frame"]


def test_write_survives_a_closed_stream():
    """Teardown can close the stream underneath a running frame."""

    class _Closed:
        def write(self, text):
            raise ValueError("I/O operation on closed file.")

        def flush(self):
            pass

    class _Console:
        file = _Closed()

    _Spinner(_Console())._write("frame")  # must not raise


@pytest.mark.parametrize(
    "factory",
    ["ThinkingAnimation", "ListeningAnimation"],
)
def test_both_animations_share_the_guarded_lifecycle(factory):
    cls = {
        "ThinkingAnimation": ThinkingAnimation,
        "ListeningAnimation": ListeningAnimation,
    }[factory]
    assert issubclass(cls, TerminalAnimation)
    anim = cls(_console())
    anim._enabled = True
    anim.start()
    try:
        assert anim.running
    finally:
        anim.stop()
    assert not anim.running


def test_process_exits_cleanly_with_a_running_animation():
    """End-to-end: the interpreter must finalize without aborting.

    Reproduces the original crash shape — an animation left running while the
    process exits — and asserts a clean exit rather than
    ``Fatal Python error: _enter_buffered_busy``.
    """
    script = (
        "import sys, time\n"
        "from rich.console import Console\n"
        "from grandpa.voice.presenter import ListeningAnimation\n"
        "c = Console(stderr=True, force_terminal=True)\n"
        "a = ListeningAnimation(c, interval=0.0005)\n"
        "a._enabled = True\n"
        "a.start()\n"
        "time.sleep(0.05)\n"
        "# exit without stopping: the atexit hook must clean up\n"
    )
    for _ in range(5):
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert "Fatal Python error" not in proc.stderr
