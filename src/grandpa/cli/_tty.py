"""Terminal detection for confirmation prompts."""

from __future__ import annotations

import sys


def stdin_is_interactive() -> bool:
    """Return True only when stdin is a terminal a person can answer.

    ``sys.stdin.isatty()`` alone is not enough on Windows: stdin redirected from
    ``NUL`` (``< NUL``, ``subprocess.DEVNULL``) is a character device, so
    ``isatty()`` reports True although nobody can type and any prompt hits EOF.
    There, only a real console input handle accepts ``GetConsoleMode``.
    """
    stdin = sys.stdin
    try:
        if stdin is None or not stdin.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(stdin.fileno())
        mode = ctypes.c_uint32()
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except (AttributeError, OSError, ValueError):
        return False


__all__ = ["stdin_is_interactive"]
