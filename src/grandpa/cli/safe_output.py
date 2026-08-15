"""Defensive output helpers for expected CLI errors on Windows."""

from __future__ import annotations

import sys
from typing import TextIO

import click


def safe_cli_error(message: str) -> None:
    """Render an expected error without trusting one console wrapper."""

    text = str(message)
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
