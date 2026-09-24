"""Dump every thread's stack if the process stops making progress.

A command that hangs tells you nothing. You see no output and no error, you kill
it, and all you have is the knowledge that it was slow. That happened here twice
with ``grandpa reminders add``, in two different sessions: the command printed
its full, correct output and then the process did not exit within five minutes.
Ruling out a lingering non-daemon thread took a purpose-built probe, and it only
ruled something out -- the cause is still unknown, because by the time anyone
looked the process was gone.

This makes the process say what it was doing. ``faulthandler.dump_traceback_later``
arms a watchdog in C: after N seconds with nobody cancelling it, it writes every
thread's stack to a file and (optionally) kills the process. It costs one timer
and no polling, so it is on in the CLI rather than reserved for debugging -- a
user whose ``grandpa`` command hangs can send the file instead of a description.

Off by default at the module level and switched on by the CLI, because a library
should not install watchdogs in somebody else's process.
"""

from __future__ import annotations

import faulthandler
import os
from pathlib import Path
from typing import TextIO

ENV_VAR = "GRANDPA_STALL_TIMEOUT"
"""Seconds of no progress before the stacks are dumped. 0 or unset disables it."""

DEFAULT_TIMEOUT_SECONDS = 0.0
"""Off unless asked for. The e2e suite sets the variable; a user can too."""

_handle: TextIO | None = None


def stall_log_path() -> Path:
    """Where the stacks go: beside the rest of Grandpa's state."""
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / "stalled-stacks.log"


def configured_timeout() -> float:
    raw = os.environ.get(ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else 0.0


def arm(timeout: float | None = None) -> bool:
    """Start the watchdog. Returns whether it was armed.

    Safe to call more than once; the later call replaces the earlier timer.
    """
    global _handle
    seconds = configured_timeout() if timeout is None else timeout
    if seconds <= 0:
        return False
    path = stall_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8")
    except OSError:
        # Nowhere to write is not a reason to fail the command the user asked for.
        return False
    _handle = handle
    handle.write(
        f"\n--- armed: stall watchdog at {seconds:g}s, pid {os.getpid()} ---\n"
    )
    handle.flush()
    # exit=True, because a process that has already stalled past the deadline is
    # not going to be rescued by being allowed to continue, and a caller waiting
    # on it needs it to end. The stacks are written first.
    faulthandler.dump_traceback_later(seconds, repeat=False, file=handle, exit=True)
    return True


def disarm() -> None:
    """Cancel the watchdog. Called when the command finishes normally."""
    global _handle
    faulthandler.cancel_dump_traceback_later()
    if _handle is not None:
        try:
            _handle.close()
        except OSError:  # pragma: no cover - a closed stream is fine
            pass
        _handle = None


__all__ = ["ENV_VAR", "arm", "configured_timeout", "disarm", "stall_log_path"]
