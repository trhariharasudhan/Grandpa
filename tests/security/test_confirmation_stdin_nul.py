"""Confirmation prompts must treat a redirected-from-NUL stdin as non-interactive.

On Windows, stdin redirected from ``NUL`` (``< NUL``, ``subprocess.DEVNULL``)
reports ``isatty() == True``. ``grandpa ask`` without ``--yes`` then prompted,
hit EOF and aborted with exit 1 instead of refusing the tool cleanly. Found by
``scripts/verify_confirmation_enforcement.py``; ``CliRunner`` tests missed it
because their stdin is a ``StringIO``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import grandpa
from grandpa.cli import ask as ask_module

_SRC = str(Path(grandpa.__file__).resolve().parents[1])


def _run_with_devnull_stdin(code: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = _SRC + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def test_devnull_stdin_is_not_interactive() -> None:
    proc = _run_with_devnull_stdin(
        "import sys; from grandpa.cli._tty import stdin_is_interactive;"
        " sys.stdout.write(repr(stdin_is_interactive()))"
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"


def test_ask_installs_no_prompt_callback_when_stdin_is_devnull() -> None:
    proc = _run_with_devnull_stdin(
        "import sys; from grandpa.cli.ask import _resolve_confirm_callback;"
        " sys.stdout.write(repr(_resolve_confirm_callback(False)))"
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "None", (
        "ask would prompt on a stdin nobody can answer, then abort on EOF"
    )


def test_ask_prompt_treats_eof_as_no(monkeypatch) -> None:
    import grandpa.cli._tty as tty

    monkeypatch.setattr(tty, "stdin_is_interactive", lambda: True)

    def _eof(*_args, **_kwargs):
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)

    confirm = ask_module._resolve_confirm_callback(False)

    assert confirm is not None
    assert confirm("Allow execution of tool 'shell_exec'?") is False
