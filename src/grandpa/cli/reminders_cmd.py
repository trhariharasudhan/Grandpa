"""CLI commands for local one-shot reminders."""

from __future__ import annotations

import time
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table

from grandpa.cli._tty import require_confirmation
from grandpa.reminder_parser import (
    ReminderParseError,
    parse_duration,
    parse_reminder_phrase,
)
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
    # Not `grandpa scheduler start`: that polls scheduled *tasks* and never
    # reads reminders.db, so it was advice that delivered nothing. `reminders
    # watch` runs the reminder service itself.
    console.print(
        "  Deliver what is due now:  [bold]grandpa reminders run-due[/bold]\n"
        "  Keep one running:         [bold]grandpa reminders watch[/bold]\n"
        "  Turn it on permanently:   [bold]grandpa config set scheduler.enabled "
        "true[/bold]"
    )
    console.print(
        "[dim]Nothing is lost by waiting: a reminder is delivered whenever it is "
        "next checked, with how late it is in the text.[/dim]"
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
@click.option(
    "--in",
    "due_in",
    default=None,
    metavar="DURATION",
    help="Create it this far from now -- 10m, 90s, 2h30m -- taking PHRASE as "
    "the message exactly as written. Without it, PHRASE has to be a sentence "
    'the parser understands, like "remind me in 10 minutes to call amma".',
)
def reminders_add(phrase: str, due_in: str | None) -> None:
    """Create a reminder, either from a phrase or from --in.

    ``--in`` exists because the phrase form needs a shape you have to know: a
    "remind me" prefix, spelled-out units, and "tomorrow" before a clock time.
    With ``--in`` the phrase is just the message.
    """
    console = Console()
    try:
        if due_in is not None:
            delta = parse_duration(due_in)
            message = " ".join(phrase.strip().split())
            if not message:
                raise ReminderParseError("Reminder text is required.")
            reminder = ReminderStore().create(
                message,
                datetime.now().astimezone() + delta,
                source={
                    "cli": "grandpa reminders add --in",
                    "input": phrase,
                    "matched_expression": due_in,
                },
            )
        else:
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
        if due_in is None:
            # The phrase form is the one with rules. Say the way out rather
            # than leaving the user to guess a second time.
            console.print(
                '[dim]Or skip the phrasing entirely: '
                '[/dim][bold]grandpa reminders add "'
                + " ".join(phrase.strip().split())[:40]
                + '" --in 10m[/bold]'
            )
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
        recurring = _recurring_reminders()
        # Name what is actually in scope. This said "all reminders" while
        # leaving every recurring one untouched, which is the same command
        # lying about what it did.
        extra = (
            f" and {len(recurring)} recurring reminder(s) in scheduler.db"
            if recurring
            else ""
        )
        if not require_confirmation(
            f"This will delete all one-shot reminders, including pending ones"
            f"{extra}. Continue?",
            yes=yes,
            cancelled="Reminder clear cancelled.",
        ):
            return
        deleted = store.delete()
        removed_recurring = _delete_recurring(recurring)
        _print_deleted(console, deleted, None)
        if removed_recurring:
            console.print(
                f"[yellow]Also removed {removed_recurring} recurring "
                f"reminder(s).[/yellow]"
            )
        return
    statuses: list[ReminderStatus] = (
        [status] if status is not None else ["triggered", "cancelled", "failed"]
    )
    deleted = store.delete(statuses=statuses)
    _print_deleted(console, deleted, status)


@reminders.command("cancel")
@click.argument("reminder_id")
def reminders_cancel(reminder_id: str) -> None:
    """Cancel a reminder, one-shot or recurring.

    Both stores, because ``list`` shows both. Cancelling an id that ``list``
    had just printed used to answer "Reminder not found" and exit 1, because
    this command only ever read ``reminders.db`` -- and nothing anywhere could
    cancel a recurring reminder at all.
    """
    console = Console()
    reminder = ReminderStore().cancel(reminder_id, now=datetime.now().astimezone())
    if reminder is not None:
        console.print(f"[yellow]Reminder {reminder.id} is {reminder.status}.[/yellow]")
        return

    if _cancel_recurring(console, reminder_id):
        return

    console.print(f"[red]Reminder not found: {reminder_id}[/red]")
    console.print("[dim]`grandpa reminders list` shows the ids of both kinds.[/dim]")
    raise SystemExit(1)


def _cancel_recurring(console: Console, reminder_id: str) -> bool:
    """Disable a recurring reminder in scheduler.db. False if it is not one."""
    try:
        numeric = int(str(reminder_id).strip())
    except (TypeError, ValueError):
        return False
    try:
        from grandpa.task_scheduler import SchedulerStore

        store = SchedulerStore()
        existing = store.get_reminder(numeric)
        if existing is None:
            return False
        if not store.set_reminder_enabled(numeric, False):
            return False
    except Exception:  # noqa: BLE001 - a missing scheduler store is simply "no"
        return False
    console.print(
        f"[yellow]Recurring reminder {numeric} is paused.[/yellow] "
        f"({existing.get('text') or existing.get('name') or ''})"
    )
    console.print("[dim]It stays in the list, disabled, so it can be resumed.[/dim]")
    return True


def _delete_recurring(rows: list[dict]) -> int:
    """Remove recurring reminders. Returns how many went."""
    if not rows:
        return 0
    try:
        from grandpa.task_scheduler import SchedulerStore

        store = SchedulerStore()
    except Exception:  # noqa: BLE001 - nothing to delete if there is no store
        return 0
    removed = 0
    for row in rows:
        try:
            if store.delete_reminder(int(row.get("id", 0))):
                removed += 1
        except Exception:  # noqa: BLE001 - one bad row is not a failed clear
            continue
    return removed


@reminders.command("watch")
@click.option(
    "--interval",
    default=30,
    type=int,
    show_default=True,
    help="Seconds between checks.",
)
def reminders_watch(interval: int) -> None:
    """Deliver reminders as they come due. Blocks this terminal.

    This is the command the create warning points at. ``grandpa scheduler
    start`` is a different thing: it polls scheduled *tasks* out of
    scheduler.db and never reads reminders.db, so it delivered nothing.
    """
    console = Console()
    service = ReminderSchedulerService(
        ReminderStore(), notifier=FirstWorkingNotifier()
    )
    console.print(
        f"[green]Watching for reminders every {interval}s.[/green] "
        "Ctrl+C to stop."
    )
    delivered = 0
    try:
        while True:
            result = service.tick()
            for reminder_id in result["triggered"]:
                delivered += 1
                console.print(f"[green]Delivered[/green] {reminder_id}")
            for reminder_id in result["failed"]:
                console.print(f"[red]Failed[/red] {reminder_id}")
            time.sleep(max(1, interval))
    except KeyboardInterrupt:
        console.print(f"\n[yellow]Stopped.[/yellow] Delivered {delivered}.")


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
