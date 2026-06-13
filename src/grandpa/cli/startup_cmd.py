"""CLI commands for Windows sign-in startup integration."""

from __future__ import annotations

import click
from rich.console import Console

from grandpa.windows_startup import disable_startup, enable_startup, startup_status


@click.group()
def startup() -> None:
    """Manage Windows sign-in startup for Grandpa."""


@startup.command("enable")
def startup_enable() -> None:
    """Enable Grandpa backend startup at Windows sign-in."""
    _print_result(enable_startup())


@startup.command("disable")
def startup_disable() -> None:
    """Disable Grandpa backend startup at Windows sign-in."""
    _print_result(disable_startup())


@startup.command("status")
def startup_status_cmd() -> None:
    """Show Grandpa Windows startup status."""
    _print_result(startup_status())


def _print_result(result) -> None:
    console = Console()
    style = "green" if result.ok and not result.stale else "yellow"
    if not result.ok and not result.unsupported:
        style = "red"
    console.print(f"[{style}]{result.message}[/{style}]")
    console.print(f"  Status: {result.status}")
    if result.entry_path:
        console.print(f"  Entry: {result.entry_path}")
    if result.command:
        console.print(f"  Command: {' '.join(result.command)}")
    if result.stale:
        console.print("  Warning: startup entry is stale and should be refreshed.")
    if result.error:
        console.print(f"  Detail: {result.error}")
    if not result.ok:
        raise SystemExit(1)


__all__ = ["startup"]
