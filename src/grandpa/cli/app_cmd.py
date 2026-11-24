"""``grandpa app``: the desktop app (a ChatGPT/Claude-style window)."""

from __future__ import annotations

import click


@click.command()
@click.option("-m", "--model", "model_name", default=None, help="Model to use.")
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option(
    "--browser",
    is_flag=True,
    help="No window: print an address to open in a browser tab instead.",
)
@click.option("--debug", is_flag=True, help="Open the web inspector with the window.")
def app(
    model_name: str | None, engine_key: str | None, browser: bool, debug: bool
) -> None:
    """Open Grandpa's desktop app."""
    from grandpa.app import run

    args: list[str] = []
    if model_name:
        args += ["--model", model_name]
    if engine_key:
        args += ["--engine", engine_key]
    try:
        code = run(chat_args=args, browser=browser, debug=debug, echo=click.echo)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    raise SystemExit(code)
