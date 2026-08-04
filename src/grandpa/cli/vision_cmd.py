"""Grandpa Vision Engine V1 developer and read-only commands."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.vision.actions import VisualActionService
from grandpa.vision.service import VisionEngine


@click.group("vision")
def vision() -> None:
    """Inspect and understand visible Windows UI without guessing coordinates."""


def _engine() -> VisionEngine:
    return VisionEngine()


def _safe_run(operation):
    try:
        return operation()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@vision.command("inspect")
def inspect_cmd() -> None:
    """Inspect active-window capture, OCR, and UI Automation readiness."""

    result = _safe_run(_engine().inspect)
    click.echo(result.message)
    if result.graph and result.graph.warnings:
        click.echo("Warnings:")
        for warning in result.graph.warnings:
            click.echo(f"- {warning}")


@vision.command("describe")
def describe() -> None:
    click.echo(_safe_run(_engine().describe).message)


@vision.command("read")
def read() -> None:
    click.echo(_safe_run(_engine().read).message)


@vision.command("graph")
@click.option("--pretty/--compact", default=True)
def graph(pretty: bool) -> None:
    result = _safe_run(_engine().inspect)
    payload = result.graph.to_dict() if result.graph else {}
    click.echo(json.dumps(payload, indent=2 if pretty else None))


@vision.command("dump")
def dump() -> None:
    result = _safe_run(_engine().inspect)
    target_dir = DEFAULT_CONFIG_DIR / "vision"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = target_dir / f"vision-graph-{stamp}.json"
    payload = result.graph.to_dict() if result.graph else {}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    click.echo(f"Vision graph saved: {path}")


@vision.command("screenshot")
@click.option("--monitor", type=click.IntRange(1), default=None)
@click.option("--active-window/--desktop", default=True)
@click.option("--output", type=click.Path(path_type=Path), default=None)
def screenshot(monitor: int | None, active_window: bool, output: Path | None) -> None:
    engine = _engine()
    graph, captured = _safe_run(
        lambda: engine.extractor.inspect(
            active_window=active_window if monitor is None else False,
            monitor=monitor,
        )
    )
    saved = _safe_run(lambda: engine.extractor.capture.save(captured, output=output))
    click.echo(
        f"Screenshot saved: {saved.saved_path}\n"
        f"Source: {graph.capture.source}; {graph.capture.width} x {graph.capture.height}"
    )


@vision.command("find")
@click.argument("query", nargs=-1, required=True)
def find(query: tuple[str, ...]) -> None:
    click.echo(_safe_run(lambda: _engine().find(" ".join(query))).message)


@vision.command("highlight")
@click.argument("query", nargs=-1, required=True)
def highlight(query: tuple[str, ...]) -> None:
    click.echo(
        _safe_run(lambda: VisualActionService().highlight(" ".join(query))).message
    )


@vision.command("buttons")
def buttons() -> None:
    click.echo(_safe_run(lambda: _engine().list_elements("button")).message)


@vision.command("controls")
def controls() -> None:
    click.echo(
        _safe_run(
            lambda: _engine().list_elements(
                "button",
                "checkbox",
                "combo_box",
                "edit",
                "hyperlink",
                "list",
                "menu",
                "radio_button",
                "tab",
                "tree",
            )
        ).message
    )


__all__ = ["vision"]
