"""Terminal detection and confirmation prompts for destructive commands."""

from __future__ import annotations

import sys
from collections.abc import Callable

import click

NOT_INTERACTIVE_MESSAGE = (
    "Not confirmed: stdin is not interactive, so nobody can answer the prompt. "
    "Re-run with --yes to confirm."
)


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


def confirm_destructive(prompt: str) -> bool | None:
    """Ask ``prompt`` with ``click.confirm``, defaulting to No.

    Returns None, without reading anything, when stdin is not interactive:
    nobody can answer, so the caller must abort instead of proceeding. A piped
    "y" is not an answer from a person.
    """
    if not stdin_is_interactive():
        return None
    prompt = prompt.strip()
    if prompt.endswith("[y/N]"):
        prompt = prompt[: -len("[y/N]")].rstrip()
    try:
        return click.confirm(prompt, default=False)
    except click.Abort:
        return False


class TerminalConfirmation:
    """A handler ``confirm=`` callback that asks on the terminal.

    It remembers the answer, so the command can report a declined or
    unanswerable prompt instead of echoing the handler's pending message.
    """

    def __init__(self, prompt_for: Callable[..., str]) -> None:
        self._prompt_for = prompt_for
        self.asked = False
        self.answer: bool | None = None

    def __call__(self, *args: object) -> bool:
        self.asked = True
        self.answer = confirm_destructive(self._prompt_for(*args))
        return self.answer is True

    def finish(self, message: str, *, cancelled: str) -> None:
        """Echo the handler's result, or abort when confirmation was not given."""
        if not self.asked or self.answer:
            click.echo(message)
            return
        if self.answer is None:
            click.echo(NOT_INTERACTIVE_MESSAGE, err=True)
            raise SystemExit(1)
        click.echo(cancelled)


def require_confirmation(prompt: str, *, yes: bool, cancelled: str) -> bool:
    """For commands without a handler callback: True to proceed, False if declined."""
    if yes:
        return True
    answer = confirm_destructive(prompt)
    if answer is None:
        click.echo(NOT_INTERACTIVE_MESSAGE, err=True)
        raise SystemExit(1)
    if not answer:
        click.echo(cancelled)
    return answer


__all__ = [
    "NOT_INTERACTIVE_MESSAGE",
    "TerminalConfirmation",
    "confirm_destructive",
    "require_confirmation",
    "stdin_is_interactive",
]
