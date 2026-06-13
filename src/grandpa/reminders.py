"""Local one-shot reminders with persistent storage and notification hooks."""

from __future__ import annotations

import importlib.util
import logging
import platform
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from grandpa.core.config import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

DEFAULT_REMINDER_DB = DEFAULT_CONFIG_DIR / "reminders.db"
ReminderStatus = Literal["pending", "triggered", "cancelled", "failed"]
OVERDUE_GRACE_PERIOD = timedelta(minutes=10)


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
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
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

            toast = Notification(app_id="Grandpa", title="Grandpa Reminder", msg=reminder.message)
            toast.show()
            return NotificationResult(True, "sent", "Windows notification sent.", backend="winotify")
        except Exception as exc:
            logger.warning("Windows reminder notification failed: %s", exc)
            return NotificationResult(False, "failed", "Windows notification failed.", backend="winotify", warning=str(exc))


class ReminderStore:
    def __init__(self, db_path: Path | str = DEFAULT_REMINDER_DB) -> None:
        self.db_path = Path(db_path)
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders(status, due_at)")

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
                    reminder.updated_at.isoformat() if reminder.updated_at else reminder.created_at.isoformat(),
                    reminder.status,
                    json.dumps(reminder.source, sort_keys=True),
                ),
            )
        return reminder

    def get(self, reminder_id: str) -> Reminder | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        return _row_to_reminder(row) if row else None

    def list(self, *, status: ReminderStatus | None = None) -> list[Reminder]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM reminders WHERE status = ? ORDER BY due_at ASC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM reminders ORDER BY due_at ASC").fetchall()
        return [_row_to_reminder(row) for row in rows]

    def cancel(self, reminder_id: str, *, now: datetime | None = None) -> Reminder | None:
        reminder = self.get(reminder_id)
        if reminder is None:
            return None
        if reminder.status != "pending":
            return reminder
        self._set_status(reminder_id, "cancelled", now=now)
        return self.get(reminder_id)

    def mark_triggered(self, reminder_id: str, *, now: datetime | None = None) -> Reminder | None:
        self._set_status(reminder_id, "triggered", now=now, triggered_at=now or datetime.now(UTC))
        return self.get(reminder_id)

    def mark_failed(self, reminder_id: str, reason: str, *, now: datetime | None = None) -> Reminder | None:
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
                    _coerce_aware_datetime(triggered_at).isoformat() if triggered_at else None,
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
        self.notifier = notifier or WindowsToastNotifier()
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
            self._thread = threading.Thread(target=self._run, daemon=True, name="grandpa-reminder-scheduler")
            self._thread.start()
            return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._thread and self._thread.is_alive() and not self._stop.is_set()),
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
            if age > OVERDUE_GRACE_PERIOD:
                self.store.mark_failed(reminder.id, "Reminder was missed after restart and is older than 10 minutes.", now=now)
                failed.append(reminder.id)
                continue
            try:
                result = self.notifier.notify(reminder)
                if result.ok:
                    self.store.mark_triggered(reminder.id, now=now)
                    triggered.append(reminder.id)
                else:
                    self.store.mark_failed(reminder.id, result.warning or result.message, now=now)
                    failed.append(reminder.id)
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.exception("Reminder notification failed")
                self.store.mark_failed(reminder.id, str(exc), now=now)
                failed.append(reminder.id)
        self._last_tick = {"status": "ok", "checked_at": now.isoformat(), "triggered": triggered, "failed": failed}
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
        updated_at=_coerce_aware_datetime(row["updated_at"]) if row["updated_at"] else None,
        status=row["status"],
        source=json.loads(row["source_json"] or "{}"),
        triggered_at=_coerce_aware_datetime(row["triggered_at"]) if row["triggered_at"] else None,
        failure_reason=row["failure_reason"],
    )


__all__ = [
    "DEFAULT_REMINDER_DB",
    "OVERDUE_GRACE_PERIOD",
    "NotificationResult",
    "Reminder",
    "ReminderSchedulerService",
    "ReminderStatus",
    "ReminderStore",
    "WindowsToastNotifier",
]
