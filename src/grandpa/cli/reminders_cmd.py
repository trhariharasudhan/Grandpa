"""CLI commands for local one-shot reminders."""

from __future__ import annotations

from datetime import datetime

import click
from rich.console import Console
from rich.table import Table

from grandpa.reminder_parser import ReminderParseError, parse_reminder_phrase
from grandpa.reminders import (
    ReminderSchedulerService,
    ReminderStore,
    WindowsToastNotifier,
)


@click.group()
def reminders() -> None:
    """Manage local one-shot reminders."""


@reminders.command("create")
@click.argument("message")
@click.option("--due-at", required=True, help="Timezone-aware ISO 8601 datetime.")
def reminders_create(message: str, due_at: str) -> None:
    """Create a one-shot reminder."""
    console = Console()
    try:
        reminder = ReminderStore().create(message, due_at, source={"cli": "grandpa reminders create"})
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    console.print(f"[green]Reminder created:[/green] {reminder.id}")
    console.print(f"  Message: {reminder.message}")
    console.print(f"  Due: {reminder.due_at.isoformat()}")


@reminders.command("add")
@click.argument("phrase")
def reminders_add(phrase: str) -> None:
    """Create a reminder from a natural-language phrase."""
    console = Console()
    try:
        parsed = parse_reminder_phrase(phrase)
        reminder = ReminderStore().create(
            parsed.message,
            parsed.due_at,
            source={
                "cli": "grandpa reminders add",
                "input": phrase,
                "matched_expression": parsed.matched_expression,
            },
        )
    except (ReminderParseError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    console.print(f"[green]Reminder created:[/green] {reminder.id}")
    console.print(f"  Message: {reminder.message}")
    console.print(f"  Due: {reminder.due_at.isoformat()}")


@reminders.command("list")
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    help="Show all reminders, including cancelled, failed, and triggered.",
)
@click.option(
    "--status",
    default=None,
    type=click.Choice(["pending", "triggered", "cancelled", "failed"]),
    help="Filter reminders by status.",
)
def reminders_list(show_all: bool, status: str | None) -> None:
    """List local reminders."""
    console = Console()
    effective_status = status if status is not None else None if show_all else "pending"
    items = ReminderStore().list(status=effective_status)  # type: ignore[arg-type]
    if not items:
        if effective_status == "pending" and status is None and not show_all:
            console.print("[dim]No pending reminders found.[/dim]")
        else:
            console.print("[dim]No reminders found.[/dim]")
        return
    table = Table(title="Grandpa Reminders")
    table.add_column("ID", style="cyan")
    table.add_column("Status")
    table.add_column("Due")
    table.add_column("Message", max_width=50)
    for reminder in items:
        table.add_row(reminder.id, reminder.status, reminder.due_at.isoformat(), reminder.message)
    console.print(table)


@reminders.command("cancel")
@click.argument("reminder_id")
def reminders_cancel(reminder_id: str) -> None:
    """Cancel a pending reminder."""
    console = Console()
    reminder = ReminderStore().cancel(reminder_id, now=datetime.now().astimezone())
    if reminder is None:
        console.print(f"[red]Reminder not found: {reminder_id}[/red]")
        raise SystemExit(1)
    console.print(f"[yellow]Reminder {reminder.id} is {reminder.status}.[/yellow]")


@reminders.command("run-due")
def reminders_run_due() -> None:
    """Trigger currently due reminders once."""
    console = Console()
    service = ReminderSchedulerService(ReminderStore(), notifier=WindowsToastNotifier())
    result = service.tick()
    console.print(f"[green]Checked reminders.[/green] Triggered: {len(result['triggered'])}; failed: {len(result['failed'])}")


__all__ = ["reminders"]
