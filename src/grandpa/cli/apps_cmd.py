"""Application inventory CLI commands."""

from __future__ import annotations

import click

from grandpa.apps.automation import ApplicationManager
from grandpa.apps.process_manager import list_running_apps


@click.group("apps")
def apps() -> None:
    """Scan and query the local application inventory."""


@apps.command("scan")
def scan() -> None:
    _scan_apps()


def _scan_apps() -> None:
    click.echo("Scanning installed applications...")
    discovered = ApplicationManager().scan()
    click.echo(f"Found {len(discovered)} applications.")
    click.echo("Database saved.")


@apps.command("list")
@click.option("--limit", type=click.IntRange(1, 500), default=25, show_default=True)
@click.option("--all", "include_all", is_flag=True, help="Include technical and low-confidence entries.")
@click.option("--source", default=None, help="Filter by discovery source, for example start_menu.")
def list_cmd(limit: int, include_all: bool, source: str | None) -> None:
    manager = ApplicationManager()
    records = manager.list(include_all=include_all, source=source)
    if not records:
        if manager.cache_needs_refresh():
            click.echo("The application cache is missing or outdated. Run `grandpa apps refresh`.")
        else:
            click.echo("No matching user-facing applications found.")
        return
    shown = records[:limit]
    click.echo(f"Installed applications - showing {len(shown)} of {len(records)}")
    click.echo("")
    for index, record in enumerate(shown, start=1):
        source_label = f" [{record.source}]" if include_all else ""
        click.echo(f"{index}. {record.display_name}{source_label}")
    if len(records) > len(shown):
        click.echo("")
        click.echo(f"Use `grandpa apps list --limit {min(len(records), max(limit * 2, 50))}` to show more.")
    click.echo("Use `grandpa apps search <name>` to find an application.")


@apps.command("search")
@click.argument("name", nargs=-1, required=True)
def search(name: tuple[str, ...]) -> None:
    _print_find_result(name)


@apps.command("find")
@click.argument("name", nargs=-1, required=True)
def find(name: tuple[str, ...]) -> None:
    _print_find_result(name)


def _print_find_result(name: tuple[str, ...]) -> None:
    result = ApplicationManager().search(" ".join(name))
    click.echo(result.message)
    for record in result.matches:
        click.echo(record.path)


@apps.command("refresh")
def refresh() -> None:
    """Refresh the local application database."""

    _scan_apps()


@apps.command("running")
@click.option("--all-processes", is_flag=True, help="Show raw processes for diagnostics.")
@click.option("--limit", type=click.IntRange(1, 500), default=50, show_default=True)
def running(all_processes: bool, limit: int) -> None:
    """List currently running applications/processes."""

    records = list_running_apps(limit=limit, include_all_processes=all_processes)
    if not records:
        click.echo("No running applications detected, or process inspection is unavailable.")
        return
    click.echo("Running applications:" if not all_processes else "Running processes:")
    for record in records:
        count = f" x {record.process_count}" if record.process_count > 1 else ""
        pid = f" (PID {record.pid})" if all_processes else ""
        click.echo(f"- {record.display_name or record.name}{count}{pid}")


@apps.command("open")
@click.argument("name", nargs=-1, required=True)
def open_cmd(name: tuple[str, ...]) -> None:
    """Open an indexed application by name."""

    result = ApplicationManager().launch(" ".join(name))
    click.echo(result.message)


__all__ = ["apps"]
