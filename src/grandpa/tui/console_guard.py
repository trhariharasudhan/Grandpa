"""Keep the Windows console input mode the way the full-screen app set it.

Textual turns off line input and echo and turns on VT input when it starts. If
anything else that shares the console resets the input mode (a child process,
a library that calls ``SetConsoleMode``, ``input()`` on another thread), the
classic Command Prompt window goes back to echoing what it reads. Mouse and
focus reports then show up on screen as raw text such as ``^[[<35;71;1M``.

``ConsoleModeGuard`` remembers the mode right after the app started and puts
it back whenever it changes. On other systems it does nothing.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004


class ConsoleModeGuard:
    """Restores the console input mode captured by :meth:`capture`."""

    def __init__(self, kernel32=None, handle=None) -> None:
        self._kernel32 = kernel32
        self._handle = handle
        self._wanted: int | None = None
        self.repairs = 0
        if kernel32 is None and sys.platform == "win32":
            try:
                import ctypes

                self._kernel32 = ctypes.windll.kernel32
                self._handle = self._kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
            except (AttributeError, OSError):
                self._kernel32 = None

    @property
    def active(self) -> bool:
        return self._kernel32 is not None and self._wanted is not None

    def _get(self) -> int | None:
        import ctypes

        mode = ctypes.c_uint32()
        if not self._kernel32.GetConsoleMode(self._handle, ctypes.byref(mode)):
            return None
        return int(mode.value)

    def capture(self) -> None:
        """Remember the current mode, if it is the app's (no echo, no line input)."""
        if self._kernel32 is None:
            return
        mode = self._get()
        if mode is None or mode & (ENABLE_ECHO_INPUT | ENABLE_LINE_INPUT):
            return
        self._wanted = mode

    def check(self) -> bool:
        """Put the remembered mode back if it changed. True when it repaired."""
        if not self.active:
            return False
        mode = self._get()
        if mode is None or mode == self._wanted:
            return False
        self._kernel32.SetConsoleMode(self._handle, self._wanted)
        self.repairs += 1
        if self.repairs <= 3:
            logger.warning(
                "console input mode changed from %#06x to %#06x; restored",
                self._wanted,
                mode,
            )
        return True
