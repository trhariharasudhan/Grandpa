"""Defensive output helpers for expected CLI errors on Windows."""

from __future__ import annotations

import sys
from typing import TextIO

import click


def safe_cli_error(message: str) -> None:
    """Render an expected error without trusting one console wrapper.

    Also the one funnel every expected CLI failure already passes
    through, so recording the last error here needs no new call sites.
    """

    text = str(message)
    try:
        from grandpa.diagnostics.oops import record_error

        record_error(text)
    except Exception:  # noqa: BLE001 - reporting an error must not raise
        pass
    try:
        click.echo(text, err=True)
        return
    except (OSError, ValueError):
        pass
    for stream in _fallback_streams():
        try:
            stream.write(f"{text}\n")
            stream.flush()
            return
        except (OSError, ValueError, AttributeError):
            continue


def _fallback_streams() -> tuple[TextIO, ...]:
    candidates = (sys.stdout, sys.__stderr__, sys.__stdout__)
    return tuple(stream for stream in candidates if stream is not None)


__all__ = ["safe_cli_error"]
