"""Local one-shot reminders with persistent storage and notification hooks."""

from __future__ import annotations

import importlib.util
import logging
import platform
import re
import sqlite3
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from grandpa.core.config import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

#: Kept because a test imports it. Not used as a default any more: see
#: :func:`default_reminder_db`.
DEFAULT_REMINDER_DB = DEFAULT_CONFIG_DIR / "reminders.db"


def default_reminder_db() -> Path:
    """Where the reminder database lives, resolved now rather than at import.

    Same reason as :func:`grandpa.task_scheduler.default_scheduler_db`: an
    import-time default ignores a ``GRANDPA_HOME`` set afterwards.
    """
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / "reminders.db"
ReminderStatus = Literal["pending", "triggered", "cancelled", "failed"]
#: How late a reminder may be before its delivery says so.
#:
#: This used to be the age at which a reminder was *discarded*: the tick marked
#: anything older failed and never delivered it. Combined with
#: ``scheduler.enabled`` defaulting to False, that lost every reminder on a
#: default install -- the only way to receive one was to run ``run-due`` inside
#: a ten-minute window around the due time, which nobody does.
#:
#: A late reminder is still information. "Call Arjun" delivered three hours late
#: is worth having and a person can judge it; silence is not. So the period now
#: decides the *wording*, and nothing is dropped for being old.
OVERDUE_GRACE_PERIOD = timedelta(minutes=10)


def describe_lateness(age: timedelta) -> str:
    """How late, in words a person reads, or "" when it is on time."""
    seconds = max(0.0, age.total_seconds())
    if seconds <= OVERDUE_GRACE_PERIOD.total_seconds():
        return ""
    minutes = int(seconds // 60)
    if minutes < 90:
        return f"{minutes} minutes late"
    hours = minutes / 60.0
    if hours < 36:
        return f"{hours:.0f} hours late"
    return f"{hours / 24.0:.0f} days late"


@dataclass(frozen=True)
class Reminder:
    id: str
    message: str
    due_at: datetime
    created_at: datetime
    status: ReminderStatus = "pending"
    source: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime | None = None
    triggered_at: datetime | None = None
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "message": self.message,
            "title": self.message,
            "due_at": self.due_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "triggered_at": self.triggered_at.isoformat()
            if self.triggered_at
            else None,
            "status": self.status,
            "source": self.source,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class NotificationResult:
    ok: bool
    status: str
    message: str
    backend: str = "none"
    warning: str | None = None


class ReminderNotifier(Protocol):
    def notify(self, reminder: Reminder) -> NotificationResult:
        """Send a notification for *reminder*."""


class WindowsToastNotifier:
    """Best-effort Windows toast notifier.

    Grandpa does not require a toast dependency in core installs. If a supported
    notification package is unavailable, this returns a setup warning instead of
    crashing the scheduler.
    """

    def notify(self, reminder: Reminder) -> NotificationResult:
        if platform.system().lower() != "windows":
            return NotificationResult(
                False,
                "unsupported",
                "Desktop notifications are only supported on Windows in this reminder backend.",
                backend="windows_toast",
                warning="Run Grandpa on Windows or use a custom notifier.",
            )
        if importlib.util.find_spec("winotify") is None:
            return NotificationResult(
                False,
                "setup_required",
                "Windows notifications need the optional winotify package.",
                backend="windows_toast",
                warning="Install with: uv sync --extra windows-notifications",
            )
        try:
            from winotify import Notification  # type: ignore[import-not-found]

            toast = Notification(
                app_id="Grandpa", title="Grandpa Reminder", msg=reminder.message
            )
            toast.show()
            return NotificationResult(
                True, "sent", "Windows notification sent.", backend="winotify"
            )
        except Exception as exc:
            logger.warning("Windows reminder notification failed: %s", exc)
            return NotificationResult(
                False,
                "failed",
                "Windows notification failed.",
                backend="winotify",
                warning=str(exc),
            )


class ConsoleNotifier:
    """The delivery that always works, because it needs nothing.

    A reminder whose notification fails is marked ``failed``, and on a default
    install every one of them failed: the toast backend needs ``winotify``,
    which lives in an optional extra. A reminder that never arrives is the
    whole feature not working.

    This writes the reminder to stdout and to a file under GRANDPA_HOME, so
    ``reminders run-due`` in a terminal shows it and a daemon leaves a record
    that survives the process. It is not a substitute for a toast -- nobody
    watches a log -- which is why it runs only after the toast has declined.
    """

    def __init__(self, stream: Any | None = None) -> None:
        self._stream = stream

    def notify(self, reminder: Reminder) -> NotificationResult:
        line = f"[reminder] {reminder.message}"
        stream = self._stream if self._stream is not None else sys.stdout
        try:
            print(line, file=stream, flush=True)
        except Exception as exc:  # pragma: no cover - a closed stdout
            logger.debug("Reminder console write failed: %s", exc)
        try:
            from grandpa.runtime_paths import grandpa_home

            log = grandpa_home() / "reminders-delivered.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now(UTC).isoformat()} {line}\n")
        except Exception as exc:  # pragma: no cover - a read-only home
            logger.debug("Reminder log write failed: %s", exc)
        return NotificationResult(
            True, "sent", "Reminder delivered to the console.", backend="console"
        )


class FirstWorkingNotifier:
    """Try each notifier in turn; the first that delivers wins.

    Toast first, because that is what a person actually sees. Console last,
    because it cannot fail -- which is what stops a missing optional package
    turning every reminder into a failure.
    """

    def __init__(self, notifiers: "list[ReminderNotifier] | None" = None) -> None:
        self._notifiers = notifiers or [WindowsToastNotifier(), ConsoleNotifier()]

    def notify(self, reminder: Reminder) -> NotificationResult:
        last: NotificationResult | None = None
        for notifier in self._notifiers:
            result = notifier.notify(reminder)
            if result.ok:
                return result
            last = result
        return last or NotificationResult(
            False, "failed", "No notifier was configured.", backend="none"
        )


class ReminderStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_reminder_db()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY,
                    message TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_json TEXT NOT NULL DEFAULT '{}',
                    triggered_at TEXT,
                    failure_reason TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders(status, due_at)"
            )

    def create(
        self,
        message: str,
        due_at: datetime | str,
        *,
        source: dict[str, Any] | None = None,
        reminder_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Reminder:
        clean_message = " ".join(message.strip().split())
        if not clean_message:
            raise ValueError("Reminder message is required.")
        due = _coerce_aware_datetime(due_at)
        now = _coerce_aware_datetime(created_at or datetime.now(UTC))
        reminder = Reminder(
            id=reminder_id or f"rem_{uuid.uuid4().hex[:12]}",
            message=clean_message,
            due_at=due,
            created_at=now,
            updated_at=now,
            status="pending",
            source=source or {},
        )
        import json

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reminders(id, message, due_at, created_at, updated_at, status, source_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reminder.id,
                    reminder.message,
                    reminder.due_at.isoformat(),
                    reminder.created_at.isoformat(),
                    reminder.updated_at.isoformat()
                    if reminder.updated_at
                    else reminder.created_at.isoformat(),
                    reminder.status,
                    json.dumps(reminder.source, sort_keys=True),
                ),
            )
        return reminder

    def get(self, reminder_id: str) -> Reminder | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
        return _row_to_reminder(row) if row else None

    def list(self, *, status: ReminderStatus | None = None) -> list[Reminder]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM reminders WHERE status = ? ORDER BY due_at ASC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM reminders ORDER BY due_at ASC"
                ).fetchall()
        return [_row_to_reminder(row) for row in rows]

    def delete(self, *, statuses: list[ReminderStatus] | None = None) -> int:
        with self._connect() as conn:
            if statuses is None:
                cursor = conn.execute("DELETE FROM reminders")
            elif not statuses:
                return 0
            else:
                placeholders = ", ".join("?" for _status in statuses)
                cursor = conn.execute(
                    f"DELETE FROM reminders WHERE status IN ({placeholders})",
                    tuple(statuses),
                )
        return int(cursor.rowcount)

    def cancel(
        self, reminder_id: str, *, now: datetime | None = None
    ) -> Reminder | None:
        reminder = self.get(reminder_id)
        if reminder is None:
            return None
        if reminder.status != "pending":
            return reminder
        self._set_status(reminder_id, "cancelled", now=now)
        return self.get(reminder_id)

    def mark_triggered(
        self, reminder_id: str, *, now: datetime | None = None
    ) -> Reminder | None:
        self._set_status(
            reminder_id, "triggered", now=now, triggered_at=now or datetime.now(UTC)
        )
        return self.get(reminder_id)

    def mark_failed(
        self, reminder_id: str, reason: str, *, now: datetime | None = None
    ) -> Reminder | None:
        self._set_status(reminder_id, "failed", now=now, failure_reason=reason[:1000])
        return self.get(reminder_id)

    def due_pending(self, now: datetime, *, limit: int = 25) -> list[Reminder]:
        current = _coerce_aware_datetime(now)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM reminders
                WHERE status = 'pending' AND due_at <= ?
                ORDER BY due_at ASC
                LIMIT ?
                """,
                (current.isoformat(), limit),
            ).fetchall()
        return [_row_to_reminder(row) for row in rows]

    def _set_status(
        self,
        reminder_id: str,
        status: ReminderStatus,
        *,
        now: datetime | None = None,
        triggered_at: datetime | None = None,
        failure_reason: str | None = None,
    ) -> None:
        updated = _coerce_aware_datetime(now or datetime.now(UTC))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE reminders
                SET status = ?, updated_at = ?, triggered_at = COALESCE(?, triggered_at),
                    failure_reason = COALESCE(?, failure_reason)
                WHERE id = ?
                """,
                (
                    status,
                    updated.isoformat(),
                    _coerce_aware_datetime(triggered_at).isoformat()
                    if triggered_at
                    else None,
                    failure_reason,
                    reminder_id,
                ),
            )


class ReminderSchedulerService:
    def __init__(
        self,
        store: ReminderStore,
        *,
        notifier: ReminderNotifier | None = None,
        poll_interval_seconds: float = 30.0,
        now_fn: Callable[[], datetime] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.store = store
        self.notifier = notifier or FirstWorkingNotifier()
        self.poll_interval_seconds = poll_interval_seconds
        self.now_fn = now_fn or (lambda: datetime.now(UTC))
        self.sleep_fn = sleep_fn or time.sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_tick: dict[str, Any] | None = None

    def start(self) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="grandpa-reminder-scheduler"
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(
                self._thread and self._thread.is_alive() and not self._stop.is_set()
            ),
            "poll_interval_seconds": self.poll_interval_seconds,
            "last_tick": self._last_tick,
        }

    def tick(self) -> dict[str, Any]:
        now = _coerce_aware_datetime(self.now_fn())
        due = self.store.due_pending(now)
        triggered: list[str] = []
        failed: list[str] = []
        for reminder in due:
            age = now - reminder.due_at
            lateness = describe_lateness(age)
            # Delivered however late, with the lateness in the text. The branch
            # that used to live here marked anything past the grace period
            # failed and delivered nothing, which is how a reminder created on
            # a default install was guaranteed to be lost.
            outgoing = (
                replace(reminder, message=f"{reminder.message}  ({lateness})")
                if lateness
                else reminder
            )
            try:
                result = self.notifier.notify(outgoing)
                if result.ok:
                    self.store.mark_triggered(reminder.id, now=now)
                    triggered.append(reminder.id)
                else:
                    self.store.mark_failed(
                        reminder.id, result.warning or result.message, now=now
                    )
                    failed.append(reminder.id)
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.exception("Reminder notification failed")
                self.store.mark_failed(reminder.id, str(exc), now=now)
                failed.append(reminder.id)
        self._last_tick = {
            "status": "ok",
            "checked_at": now.isoformat(),
            "triggered": triggered,
            "failed": failed,
        }
        return self._last_tick

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("Reminder scheduler tick failed")
            if self.sleep_fn is time.sleep:
                self._stop.wait(self.poll_interval_seconds)
            else:
                self.sleep_fn(self.poll_interval_seconds)


def _coerce_aware_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        value = datetime.fromisoformat(raw)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Reminder datetimes must include timezone information.")
    return value.astimezone(UTC)


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    import json

    return Reminder(
        id=row["id"],
        message=row["message"],
        due_at=_coerce_aware_datetime(row["due_at"]),
        created_at=_coerce_aware_datetime(row["created_at"]),
        updated_at=_coerce_aware_datetime(row["updated_at"])
        if row["updated_at"]
        else None,
        status=row["status"],
        source=json.loads(row["source_json"] or "{}"),
        triggered_at=_coerce_aware_datetime(row["triggered_at"])
        if row["triggered_at"]
        else None,
        failure_reason=row["failure_reason"],
    )


__all__ = [
    "DEFAULT_REMINDER_DB",
    "default_reminder_db",
    "OVERDUE_GRACE_PERIOD",
    "describe_lateness",
    "REMINDER_ACTIONS",
    "NotificationResult",
    "Reminder",
    "ReminderActionResult",
    "ReminderSchedulerService",
    "ReminderStatus",
    "ReminderStore",
    "ConsoleNotifier",
    "FirstWorkingNotifier",
    "WindowsToastNotifier",
    "execute_reminder_action",
    "format_reminder_list",
    "parse_reminder_intent",
]


# ---------------------------------------------------------------------------
# The structured seam
# ---------------------------------------------------------------------------

REMINDER_ACTIONS: tuple[str, ...] = ("create", "list", "cancel")
"""What chat could ask of one-shot reminders.

These were three private helpers in ``cli/chat_cmd.py``. They live here now so
the domain owns them and the action layer can call them, which is the first
step of docs/architecture/MIGRATION-PATTERN.md.

Note what is *not* here. Recurring reminders ("remind me to X every hour", and
"remind me to X at 5pm", which becomes a daily rule) are a different store
entirely -- ``task_scheduler.SchedulerStore`` on scheduler.db, while these sit
in reminders.db. Both are catalogued, separately and honestly. Joining them is
its own task.
"""


@dataclass(frozen=True)
class ReminderActionResult:
    """What one reminder operation did."""

    status: str
    message: str
    target: str | None = None
    error: str | None = None
    kind: str = "reminder"


def parse_reminder_intent(text: str) -> tuple[str, str] | None:
    """Decide which reminder action a phrase asks for, or ``None``.

    The list and cancel patterns are chat's, moved; creation defers to
    :func:`grandpa.reminder_parser.parse_reminder_phrase`, which is the thing
    that knows how to read "in 30 minutes".
    """
    from grandpa.reminder_parser import ReminderParseError, parse_reminder_phrase

    normalized = " ".join(text.lower().strip(" ?!.").split())
    if _is_reminder_list_intent(normalized):
        return "list", ""

    cancel_match = re.match(r"^(cancel|delete|remove)\s+reminder\s+(.+)$", normalized)
    if cancel_match:
        return "cancel", cancel_match.group(2).strip()

    try:
        parse_reminder_phrase(text)
    except ReminderParseError:
        return None
    return "create", text


def execute_reminder_action(
    action: str,
    *,
    store: "ReminderStore | None" = None,
    subject: str = "",
) -> ReminderActionResult:
    """Perform one reminder operation, already parsed."""
    from grandpa.reminder_parser import ReminderParseError, parse_reminder_phrase

    store = store or ReminderStore()

    if action == "create":
        try:
            parsed = parse_reminder_phrase(subject)
        except ReminderParseError as exc:
            return ReminderActionResult(
                "error", f"I could not read a time from that: {exc}", error="unparsed"
            )
        reminder = store.create(
            parsed.message,
            parsed.due_at,
            source={
                "cli": "grandpa chat",
                "input": subject,
                "matched_expression": parsed.matched_expression,
            },
        )
        return ReminderActionResult(
            "handled",
            f"Reminder created: {reminder.message} at {reminder.due_at.isoformat()}.",
            target=reminder.id,
        )

    if action == "list":
        return ReminderActionResult(
            "handled",
            format_reminder_list(
                store.list(status="pending"),
                empty=(
                    "No pending reminders found. You can create one with: "
                    "remind me in 30 minutes to drink water"
                ),
            ),
            target="pending",
        )

    if action == "cancel":
        reminder = store.cancel(subject)
        if reminder is None:
            return ReminderActionResult(
                "error",
                "Reminder not found. Use /reminders list to see reminder IDs.",
                target=subject,
                error="not_found",
            )
        if reminder.status == "cancelled":
            return ReminderActionResult(
                "handled", "Reminder cancelled.", target=subject
            )
        return ReminderActionResult(
            "handled", f"Reminder is already {reminder.status}.", target=subject
        )

    return ReminderActionResult(
        "unsupported", "That reminder action is not supported.", target=action
    )


def format_reminder_list(items: list, *, empty: str) -> str:
    """Chat's own formatting, moved verbatim so the output does not change."""
    if not items:
        return empty
    lines = ["Reminders:"]
    for reminder in items[:20]:
        lines.append(
            f"- {reminder.id} [{reminder.status}] {reminder.message} "
            f"at {reminder.due_at.isoformat()}"
        )
    return "\n".join(lines)


_REMINDER_LIST_INTENTS = frozenset(
    {
        "do i have any reminders",
        "list my reminders",
        "show me my reminders",
        "show my reminders",
        "what are my reminders",
        "what reminder do i have",
        "show reminders",
        "list reminders",
        "what reminders do i have",
    }
)


def _is_reminder_list_intent(normalized: str) -> bool:
    if normalized in _REMINDER_LIST_INTENTS:
        return True
    return bool(
        re.fullmatch(r"(show|list)\s+(me\s+)?(my\s+)?reminders", normalized)
        or re.fullmatch(r"what\s+reminders?\s+do\s+i\s+have", normalized)
        or re.fullmatch(r"what\s+are\s+my\s+reminders", normalized)
        or re.fullmatch(r"do\s+i\s+have\s+any\s+reminders", normalized)
    )
