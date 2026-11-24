"""``grandpa tui``: the full-screen terminal interface (also bare ``grandpa``)."""

from __future__ import annotations

import click


@click.command()
@click.option("-m", "--model", "model_name", default=None, help="Model to use.")
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
def tui(model_name: str | None, engine_key: str | None) -> None:
    """Open Grandpa's full-screen terminal interface."""
    from grandpa.tui import main

    args: list[str] = []
    if model_name:
        args += ["--model", model_name]
    if engine_key:
        args += ["--engine", engine_key]
    raise SystemExit(main(args))
