"""CLI commands for Grandpa Google Calendar integration."""

from __future__ import annotations

import click

from grandpa.calendar import CalendarAuthManager, handle_calendar_command


@click.group(name="calendar")
def calendar() -> None:
    """Manage Google Calendar integration."""


@calendar.command("setup")
def setup() -> None:
    """Run the explicit Google Calendar OAuth setup flow."""

    result = handle_calendar_command("calendar setup")
    click.echo(result.message)
    if result.status not in {"handled", "not_configured"}:
        raise click.ClickException(result.message)


@calendar.command("status")
def status() -> None:
    """Show Calendar connection status."""

    auth_status = CalendarAuthManager().status()
    click.echo(auth_status.message)
    if auth_status.account:
        click.echo(f"Account: {auth_status.account}")


@calendar.command("disconnect")
def disconnect() -> None:
    """Disconnect Calendar by removing the local OAuth token."""

    result = handle_calendar_command("calendar disconnect")
    click.echo(result.message)


@calendar.command("today")
def today() -> None:
    click.echo(handle_calendar_command("calendar today").message)


@calendar.command("tomorrow")
def tomorrow() -> None:
    click.echo(handle_calendar_command("calendar tomorrow").message)


@calendar.command("week")
def week() -> None:
    click.echo(handle_calendar_command("calendar week").message)


@calendar.command("upcoming")
def upcoming() -> None:
    click.echo(handle_calendar_command("calendar upcoming").message)


@calendar.command("free")
@click.argument("window", nargs=-1)
def free(window: tuple[str, ...]) -> None:
    command = "show free time " + " ".join(window) if window else "show free time"
    click.echo(handle_calendar_command(command).message)


@calendar.command("search")
@click.argument("query", nargs=-1)
def search(query: tuple[str, ...]) -> None:
    click.echo(
        handle_calendar_command("search calendar for " + " ".join(query)).message
    )


@calendar.command("create")
@click.argument("detail", nargs=-1)
@click.option("--yes", is_flag=True, help="Confirm event creation.")
def create(detail: tuple[str, ...], yes: bool) -> None:
    result = handle_calendar_command(
        "create a meeting " + " ".join(detail), confirmed=yes
    )
    click.echo(result.message)


@calendar.command("update")
@click.argument("detail", nargs=-1)
@click.option("--yes", is_flag=True, help="Confirm event update.")
def update(detail: tuple[str, ...], yes: bool) -> None:
    result = handle_calendar_command(
        "move my meeting to " + " ".join(detail), confirmed=yes
    )
    click.echo(result.message)


@calendar.command("delete")
@click.argument("detail", nargs=-1)
@click.option("--yes", is_flag=True, help="Confirm event deletion.")
def delete(detail: tuple[str, ...], yes: bool) -> None:
    command = "cancel meeting " + " ".join(detail) if detail else "cancel meeting"
    result = handle_calendar_command(command, confirmed=yes)
    click.echo(result.message)


__all__ = ["calendar"]
