"""CLI commands for local one-shot reminders."""

from __future__ import annotations

from datetime import datetime

import click
from rich.console import Console
from rich.table import Table

from grandpa.cli._tty import require_confirmation
from grandpa.reminder_parser import ReminderParseError, parse_reminder_phrase
from grandpa.reminders import (
    FirstWorkingNotifier,
    ReminderSchedulerService,
    ReminderStatus,
    ReminderStore,
)


@click.group()
def reminders() -> None:
    """Manage local one-shot reminders."""


def _recurring_reminders() -> list[dict]:
    """Recurring reminders, which live in the other store.

    Two stores hold two different things: ``reminders.db`` holds a reminder with
    a due time, ``scheduler.db`` holds a routine with a schedule. That split is
    right -- a recurring reminder has no single due time -- and it is the
    *answer* that was split, not the data: "remind me at 5pm" landed in one or
    the other depending on which parser claimed the phrase first, so a reminder
    a person had just created could be missing from `reminders list`.

    The routing is fixed (one-shot phrasing goes to reminders.db, recurring
    phrasing to the scheduler). This closes the other half: one question, one
    answer. Nothing is migrated -- a routine has no due time to migrate to --
    and nothing is hidden.
    """
    try:
        from grandpa.task_scheduler import SchedulerStore

        # list_reminders(), not list_routines(): there are three tables, not
        # two. reminders.db/reminders holds one-shot reminders,
        # scheduler.db/reminders holds recurring ones, and scheduler.db/routines
        # holds morning routines. Chat's "every day at 5pm" writes the middle
        # one, which is the row that went missing from this listing.
        return list(SchedulerStore().list_reminders())
    except Exception:  # noqa: BLE001 - a missing scheduler store is not an error here
        return []


def _warn_if_nothing_will_fire(console: Console) -> None:
    """Say so when a reminder has been stored but nothing is running to deliver it.

    ``scheduler.enabled`` is False by default and that is deliberate: the
    scheduler is a background thread, and starting one inside all fifty CLI
    commands -- including ``grandpa --help`` -- costs every invocation for a
    feature most of them do not use.

    The cost of keeping it off is that a reminder silently never arrives, which
    is worse than the thread. So the honest version is off by default and said
    out loud.
    """
    try:
        from grandpa.core.config import load_config

        if load_config().scheduler.enabled:
            return
    except Exception:  # noqa: BLE001 - a broken config is not this command's business
        return
    console.print(
        "[yellow]Nothing is running to deliver this.[/yellow] The scheduler is "
        "off by default, because it is a background thread and every CLI "
        "command would pay for it."
    )
    console.print(
        "  Deliver what is due now:  [bold]grandpa reminders run-due[/bold]\n"
        "  Keep one running:         [bold]grandpa scheduler start[/bold]\n"
        "  Turn it on permanently:   [bold]grandpa config set scheduler.enabled "
        "true[/bold]"
    )


@reminders.command("create")
@click.argument("message")
@click.option("--due-at", required=True, help="Timezone-aware ISO 8601 datetime.")
def reminders_create(message: str, due_at: str) -> None:
    """Create a one-shot reminder."""
    console = Console()
    try:
        reminder = ReminderStore().create(
            message, due_at, source={"cli": "grandpa reminders create"}
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    console.print(f"[green]Reminder created:[/green] {reminder.id}")
    console.print(f"  Message: {reminder.message}")
    console.print(f"  Due: {reminder.due_at.isoformat()}")
    _warn_if_nothing_will_fire(console)


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
    _warn_if_nothing_will_fire(console)


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
    recurring = _recurring_reminders()
    if not items and not recurring:
        if effective_status == "pending" and status is None and not show_all:
            console.print("[dim]No pending reminders found.[/dim]")
        else:
            console.print("[dim]No reminders found.[/dim]")
        return
    table = Table(title="Grandpa Reminders")
    table.add_column("ID", style="cyan")
    table.add_column("Status")
    table.add_column("When")
    table.add_column("Message", max_width=50)
    for reminder in items:
        table.add_row(
            reminder.id, reminder.status, reminder.due_at.isoformat(), reminder.message
        )
    for routine in recurring:
        table.add_row(
            str(routine.get("id", "")),
            "recurring" if routine.get("enabled", True) else "paused",
            str(routine.get("schedule_label") or routine.get("schedule", "")),
            str(routine.get("text") or routine.get("name", "")),
        )
    console.print(table)
    if recurring:
        console.print(
            "[dim]Rows marked recurring live in scheduler.db and are managed "
            "with `grandpa scheduler`. They are listed here because a person "
            "asking what reminders they have means both.[/dim]"
        )


@reminders.command("clear")
@click.option(
    "--status",
    default=None,
    type=click.Choice(["triggered", "cancelled", "failed"]),
    help="Delete reminders matching this non-pending status.",
)
@click.option(
    "--all",
    "clear_all",
    is_flag=True,
    help="Delete all reminders, including pending reminders.",
)
@click.option("--yes", is_flag=True, help="Skip confirmation for --all.")
def reminders_clear(status: ReminderStatus | None, clear_all: bool, yes: bool) -> None:
    """Clear old reminder history from local storage."""
    console = Console()
    if status is not None and clear_all:
        raise click.ClickException("Use either --status or --all, not both.")
    store = ReminderStore()
    if clear_all:
        if not require_confirmation(
            "This will delete all reminders, including pending reminders. Continue?",
            yes=yes,
            cancelled="Reminder clear cancelled.",
        ):
            return
        deleted = store.delete()
        _print_deleted(console, deleted, None)
        return
    statuses: list[ReminderStatus] = (
        [status] if status is not None else ["triggered", "cancelled", "failed"]
    )
    deleted = store.delete(statuses=statuses)
    _print_deleted(console, deleted, status)


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
    # FirstWorkingNotifier, not the toast alone: the toast needs the
    # optional winotify package, and without it every reminder was
    # marked failed rather than delivered.
    service = ReminderSchedulerService(ReminderStore(), notifier=FirstWorkingNotifier())
    result = service.tick()
    console.print(
        f"[green]Checked reminders.[/green] Triggered: {len(result['triggered'])}; failed: {len(result['failed'])}"
    )


def _print_deleted(console: Console, deleted: int, status: str | None) -> None:
    if deleted == 0:
        console.print("[dim]No reminders matched.[/dim]")
        return
    noun = "reminder" if deleted == 1 else "reminders"
    if status:
        console.print(f"[green]Deleted {deleted} {status} {noun}.[/green]")
    else:
        console.print(f"[green]Deleted {deleted} {noun}.[/green]")


__all__ = ["reminders"]
