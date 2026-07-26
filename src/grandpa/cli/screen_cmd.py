"""Read-only Screen Vision CLI."""

from __future__ import annotations

import json
from pathlib import Path

import click

from grandpa.screen.errors import ScreenError
from grandpa.screen.service import ScreenVisionService


@click.group("screen")
def screen() -> None:
    """Inspect the Windows screen without interacting with it."""


def _service() -> ScreenVisionService:
    return ScreenVisionService()


def _run(operation) -> None:
    try:
        result = operation()
        if result is not None:
            click.echo(result.message)
    except ScreenError as exc:
        raise click.ClickException(str(exc)) from exc


def _capture_options(function):
    function = click.option(
        "--active-window", is_flag=True, help="Capture only the active window."
    )(function)
    return click.option(
        "--monitor",
        type=click.IntRange(1),
        default=None,
        help="Capture one monitor by index.",
    )(function)


@screen.command("capture")
@_capture_options
@click.option("--save", is_flag=True, help="Save a permanent screenshot.")
@click.option("--output", type=click.Path(path_type=Path), default=None)
@click.option(
    "--overwrite", is_flag=True, help="Allow replacing an existing output file."
)
def capture(
    monitor: int | None,
    active_window: bool,
    save: bool,
    output: Path | None,
    overwrite: bool,
) -> None:
    _run(
        lambda: _service().capture(
            monitor=monitor,
            active_window=active_window,
            save=save,
            output=output,
            overwrite=overwrite,
        )
    )


@screen.command("read")
@_capture_options
@click.option(
    "--language", default=None, help="Tesseract language code, for example eng."
)
def read(monitor: int | None, active_window: bool, language: str | None) -> None:
    _run(
        lambda: _service().read(
            monitor=monitor, active_window=active_window, language=language
        )
    )


@screen.command("describe")
@_capture_options
def describe(monitor: int | None, active_window: bool) -> None:
    _run(lambda: _service().describe(monitor=monitor, active_window=active_window))


@screen.command("error")
@_capture_options
def error(monitor: int | None, active_window: bool) -> None:
    _run(lambda: _service().error(monitor=monitor, active_window=active_window))


@screen.command("active")
def active() -> None:
    _run(_service().active)


@screen.command("windows")
@click.option(
    "--visible-only/--all", default=True, help="Show only user-facing visible windows."
)
@click.option("--json", "as_json", is_flag=True)
def windows(visible_only: bool, as_json: bool) -> None:
    try:
        result = _service().windows(
            visible_only=visible_only, include_all=not visible_only
        )
    except ScreenError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result.data, indent=2) if as_json else result.message)


@screen.command("monitors")
@click.option("--json", "as_json", is_flag=True)
def monitors(as_json: bool) -> None:
    result = _service().monitors()
    click.echo(json.dumps(result.data, indent=2) if as_json else result.message)


@screen.command("diagnose")
@click.option("--json", "as_json", is_flag=True)
def diagnose(as_json: bool) -> None:
    result = _service().diagnose()
    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
        return
    bounds = result.virtual_desktop_bounds
    click.echo(
        "Screen Vision diagnostics:\n"
        f"- Platform: {result.platform}\n"
        f"- Python: {result.python_executable}\n"
        f"- Capture backend: {result.capture_backend}\n"
        f"- Monitor count: {result.monitor_count}\n"
        f"- Primary monitor: {result.primary_monitor or 'unknown'}\n"
        f"- Virtual desktop: {bounds[0]}, {bounds[1]} to {bounds[2]}, {bounds[3]}\n"
        f"- Active-window API: {result.active_window_api}\n"
        f"- OCR provider: {result.ocr_provider}\n"
        f"- Tesseract: {result.tesseract_executable or 'not found'}\n"
        f"- OCR language: {result.ocr_language}\n"
        f"- Temporary directory: {result.temporary_directory}\n"
        f"- Analyzer: {result.local_vision_provider}"
    )


__all__ = ["screen"]
