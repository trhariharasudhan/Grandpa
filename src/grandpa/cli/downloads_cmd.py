"""CLI commands for Grandpa Downloads Manager."""

from __future__ import annotations

import click

from grandpa.cli._tty import TerminalConfirmation
from grandpa.downloads import handle_downloads_command
from grandpa.downloads.formatter import format_operation_plan


@click.group(name="downloads")
def downloads() -> None:
    """Inspect and organize the local Downloads folder."""


def _confirmed(command: str, yes: bool) -> None:
    """Run a Downloads change, asking on the terminal unless --yes was given."""
    confirm = TerminalConfirmation(
        lambda action, items: format_operation_plan(action.action, items)
    )
    result = handle_downloads_command(command, confirmed=yes, confirm=confirm)
    confirm.finish(result.message, cancelled="Downloads change cancelled.")


@downloads.command("recent")
def recent() -> None:
    click.echo(handle_downloads_command("show recent downloads").message)


@downloads.command("today")
def today() -> None:
    click.echo(handle_downloads_command("show downloads from today").message)


@downloads.command("latest")
def latest() -> None:
    click.echo(handle_downloads_command("open latest download").message)


@downloads.command("search")
@click.argument("query", nargs=-1)
def search(query: tuple[str, ...]) -> None:
    click.echo(handle_downloads_command("find downloaded " + " ".join(query)).message)


@downloads.command("large")
def large() -> None:
    click.echo(handle_downloads_command("show large downloads").message)


@downloads.command("incomplete")
def incomplete() -> None:
    click.echo(handle_downloads_command("show incomplete downloads").message)


@downloads.command("duplicates")
def duplicates() -> None:
    click.echo(handle_downloads_command("show duplicate downloads").message)


@downloads.command("organize")
@click.option("--yes", is_flag=True, help="Confirm organization.")
def organize(yes: bool) -> None:
    _confirmed("organize my downloads folder", yes)


@downloads.command("delete")
@click.argument("selector", nargs=-1)
@click.option("--yes", is_flag=True, help="Confirm deletion.")
def delete(selector: tuple[str, ...], yes: bool) -> None:
    _confirmed("downloads delete " + " ".join(selector), yes)


@downloads.command("archive")
@click.argument("selector", nargs=-1)
@click.option("--yes", is_flag=True, help="Confirm archive.")
def archive(selector: tuple[str, ...], yes: bool) -> None:
    _confirmed("downloads archive " + " ".join(selector), yes)


@downloads.command("info")
@click.argument("selector", nargs=-1)
def info(selector: tuple[str, ...]) -> None:
    click.echo(handle_downloads_command("downloads info " + " ".join(selector)).message)


__all__ = ["downloads"]
