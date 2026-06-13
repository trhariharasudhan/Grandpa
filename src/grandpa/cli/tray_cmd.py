"""CLI entry point for the Windows tray controller."""

from __future__ import annotations

import click
from rich.console import Console

from grandpa.tray import (
    TrayAlreadyRunningError,
    TrayDependencyError,
    TrayUnsupportedError,
    run_tray_app,
)


@click.command("tray")
def tray() -> None:
    """Start the Windows system tray controller."""

    console = Console()
    try:
        result = run_tray_app()
    except TrayUnsupportedError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise SystemExit(1) from exc
    except TrayDependencyError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise SystemExit(1) from exc
    except TrayAlreadyRunningError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise SystemExit(1) from exc
    console.print(f"[green]{result.message}[/green]")


__all__ = ["tray"]
