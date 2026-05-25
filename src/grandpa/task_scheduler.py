"""Local routines and reminders for Grandpa.

This module keeps Phase 9 intentionally local-first and conservative. It stores
routines/reminders in SQLite, executes routine steps through the existing local
action safety pipeline, and never runs arbitrary shell commands.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR


DEFAULT_SCHEDULER_DB = DEFAULT_CONFIG_DIR / "scheduler.db"
SAFE_ROUTINE_ACTIONS = {
    "open chrome",
    "open edge",
    "open vs code",
    "open vscode",
    "open visual studio code",
    "open youtube",
    "open downloads folder",
    "open downloads",
}


@dataclass(frozen=True)
class SchedulerResult:
    status: str
    kind: str
    target: str | None
    message: str
    tts_text: str | None = None
    permission: str | None = "allowed"
    pending_action: dict[str, Any] | None = None
    should_fallback: bool = False


class SchedulerStore:
    def __init__(self, db_path: Path | str = DEFAULT_SCHEDULER_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS routines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    name TEXT NOT NULL UNIQUE,
                    schedule TEXT,
                    actions_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    next_run_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    text TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    next_run_at REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_routines_next_run "
                "ON routines(enabled, next_run_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_next_run "
                "ON reminders(enabled, next_run_at)"
            )

    def upsert_routine(
        self,
        name: str,
        actions: list[str],
        *,
        schedule: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        now = time.time()
        next_run_at = _next_run_timestamp(schedule) if schedule and enabled else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO routines(
                    created_at, updated_at, name, schedule, actions_json, enabled, next_run_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    schedule = excluded.schedule,
                    actions_json = excluded.actions_json,
                    enabled = excluded.enabled,
                    next_run_at = excluded.next_run_at
                """,
                (
                    now,
                    now,
                    name,
                    schedule,
                    json.dumps(actions),
                    1 if enabled else 0,
                    next_run_at,
                ),
            )
        return self.get_routine(name) or {}

    def get_routine(self, name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, updated_at, name, schedule, actions_json, enabled, next_run_at
                FROM routines
                WHERE lower(name) = lower(?)
                """,
                (name,),
            ).fetchone()
        return _routine_row(row) if row else None

    def list_routines(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, updated_at, name, schedule, actions_json, enabled, next_run_at
                FROM routines
                ORDER BY enabled DESC, name ASC
                """
            ).fetchall()
        return [_routine_row(row) for row in rows]

    def set_routine_enabled(self, name: str, enabled: bool) -> dict[str, Any] | None:
        routine = self.get_routine(name)
        if not routine:
            return None
        next_run_at = (
            _next_run_timestamp(routine["schedule"]) if enabled and routine["schedule"] else None
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE routines
                SET enabled = ?, updated_at = ?, next_run_at = ?
                WHERE id = ?
                """,
                (1 if enabled else 0, time.time(), next_run_at, routine["id"]),
            )
        return self.get_routine(name)

    def delete_routine(self, name: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM routines WHERE lower(name) = lower(?)", (name,))
        return cur.rowcount > 0

    def add_reminder(self, text: str, schedule: str) -> dict[str, Any]:
        now = time.time()
        next_run_at = _next_run_timestamp(schedule)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO reminders(created_at, updated_at, text, schedule, enabled, next_run_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (now, now, text, schedule, next_run_at),
            )
        return self.get_reminder(cur.lastrowid) or {}

    def get_reminder(self, reminder_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, updated_at, text, schedule, enabled, next_run_at
                FROM reminders
                WHERE id = ?
                """,
                (reminder_id,),
            ).fetchone()
        return _reminder_row(row) if row else None

    def list_reminders(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, updated_at, text, schedule, enabled, next_run_at
                FROM reminders
                ORDER BY enabled DESC, next_run_at ASC, id DESC
                """
            ).fetchall()
        return [_reminder_row(row) for row in rows]


def handle_scheduler_command(
    text: str,
    *,
    store: SchedulerStore | None = None,
    execute: bool = True,
) -> SchedulerResult:
    command = _normalise(text)
    if not command:
        return _fallback()
    store = store or SchedulerStore()

    if command in {"create a morning routine", "create morning routine"}:
        routine = store.upsert_routine(
            "morning routine",
            ["open chrome", "open vs code"],
            schedule="daily:09:00",
            enabled=True,
        )
        _record_scheduler_activity("routine", "create", routine["name"], "daily:09:00", "handled")
        return SchedulerResult(
            "handled",
            "scheduler",
            routine["name"],
            "Created morning routine: open Chrome and VS Code every day at 9:00 AM.",
            "Created your morning routine.",
        )

    match = re.fullmatch(r"every morning open (.+)", command)
    if match:
        actions = _actions_from_open_list(match.group(1))
        if not actions:
            return _blocked("I blocked this routine because it did not contain safe open actions.")
        routine = store.upsert_routine(
            "morning routine",
            actions,
            schedule="daily:09:00",
            enabled=True,
        )
        _record_scheduler_activity("routine", "schedule", routine["name"], ", ".join(actions), "handled")
        return SchedulerResult(
            "handled",
            "scheduler",
            routine["name"],
            f"Updated morning routine with {len(actions)} safe action(s).",
            "Updated your morning routine.",
        )

    if command in {"what routines do i have", "list routines", "show routines", "what reminders do i have", "show reminders"}:
        return _list_schedule(store)

    match = re.fullmatch(r"(?:disable|turn off) (?:my )?(.+?)(?: routine)?", command)
    if match:
        name = _routine_name(match.group(1))
        routine = store.set_routine_enabled(name, False)
        if not routine:
            return SchedulerResult("handled", "scheduler", name, f"I could not find a routine named {name}.")
        _record_scheduler_activity("routine", "disable", name, None, "handled")
        return SchedulerResult("handled", "scheduler", name, f"Disabled {name}.", f"Disabled {name}.")

    match = re.fullmatch(r"(?:enable|turn on) (?:my )?(.+?)(?: routine)?", command)
    if match:
        name = _routine_name(match.group(1))
        routine = store.set_routine_enabled(name, True)
        if not routine:
            return SchedulerResult("handled", "scheduler", name, f"I could not find a routine named {name}.")
        _record_scheduler_activity("routine", "enable", name, None, "handled")
        return SchedulerResult("handled", "scheduler", name, f"Enabled {name}.", f"Enabled {name}.")

    match = re.fullmatch(r"(?:run|start) (?:my )?(.+?)(?: routine)?", command)
    if match:
        name = _routine_name(match.group(1))
        routine = store.get_routine(name)
        if not routine and name == "work setup":
            routine = store.upsert_routine("work setup", ["open chrome", "open vs code"], enabled=True)
        if not routine:
            return SchedulerResult("handled", "scheduler", name, f"I could not find a routine named {name}.")
        return _run_routine(routine, execute=execute)

    reminder = _parse_reminder(command)
    if reminder:
        item = store.add_reminder(reminder["text"], reminder["schedule"])
        _record_scheduler_activity("reminder", "create", item["text"], item["schedule"], "handled")
        return SchedulerResult(
            "handled",
            "scheduler",
            str(item["id"]),
            f"Reminder set: {item['text']} ({_schedule_label(item['schedule'])}).",
            "Reminder set.",
        )

    return _fallback()


def scheduler_summary() -> dict[str, Any]:
    store = SchedulerStore()
    return {
        "routines": store.list_routines(),
        "reminders": store.list_reminders(),
        "storage": {"backend": "sqlite", "path": str(store.db_path), "local_only": True},
    }


def run_routine(name: str) -> dict[str, Any]:
    store = SchedulerStore()
    routine = store.get_routine(_routine_name(name))
    if not routine:
        return {"status": "not_found", "message": f"I could not find a routine named {name}."}
    result = _run_routine(routine, execute=True)
    return {
        "status": result.status,
        "message": result.message,
        "routine": routine,
    }


def set_routine_enabled(name: str, enabled: bool) -> dict[str, Any]:
    store = SchedulerStore()
    routine = store.set_routine_enabled(_routine_name(name), enabled)
    if not routine:
        return {"status": "not_found", "message": f"I could not find a routine named {name}."}
    return {"status": "ok", "routine": routine}


def _run_routine(routine: dict[str, Any], *, execute: bool) -> SchedulerResult:
    if not routine.get("enabled", True):
        return SchedulerResult(
            "handled",
            "scheduler",
            routine["name"],
            f"{routine['name']} is disabled. Enable it before running.",
        )
    lines = [f"Running {routine['name']}:"]
    statuses: list[str] = []
    for action in routine["actions"]:
        if _is_risky_routine_action(action):
            lines.append(f"- {action}: needs confirmation, skipped in automatic routine run")
            statuses.append("requires_confirmation")
            continue
        from grandpa.local_actions import handle_local_action

        result = handle_local_action(action, execute=execute)
        lines.append(f"- {action}: {result.message or result.status}")
        statuses.append(result.status)
    status = "handled" if any(item == "handled" for item in statuses) else "unsupported"
    _record_scheduler_activity("routine", "run", routine["name"], "; ".join(routine["actions"]), status)
    return SchedulerResult(status, "scheduler", routine["name"], "\n".join(lines), f"Ran {routine['name']}.")


def _parse_reminder(command: str) -> dict[str, str] | None:
    match = re.fullmatch(r"remind me every hour to (.+)", command)
    if match:
        return {"text": match.group(1).strip(), "schedule": "hourly"}
    match = re.fullmatch(r"remind me to (.+) every hour", command)
    if match:
        return {"text": match.group(1).strip(), "schedule": "hourly"}
    match = re.fullmatch(r"remind me to (.+) at ([0-9]{1,2})(?::([0-9]{2}))?\s*(am|pm)", command)
    if match:
        hour = int(match.group(2))
        minute = int(match.group(3) or "0")
        suffix = match.group(4)
        if suffix == "pm" and hour != 12:
            hour += 12
        if suffix == "am" and hour == 12:
            hour = 0
        return {"text": match.group(1).strip(), "schedule": f"daily:{hour:02d}:{minute:02d}"}
    return None


def _list_schedule(store: SchedulerStore) -> SchedulerResult:
    routines = store.list_routines()
    reminders = store.list_reminders()
    if not routines and not reminders:
        return SchedulerResult("handled", "scheduler", "schedule", "You do not have routines or reminders yet.")
    lines = ["Your routines and reminders:"]
    if routines:
        lines.append("Routines:")
        for routine in routines:
            state = "enabled" if routine["enabled"] else "disabled"
            next_run = _time_label(routine.get("next_run_at"))
            lines.append(f"- {routine['name']} ({state}, next: {next_run})")
    if reminders:
        lines.append("Reminders:")
        for reminder in reminders:
            state = "enabled" if reminder["enabled"] else "disabled"
            lines.append(f"- {reminder['text']} ({state}, {_schedule_label(reminder['schedule'])})")
    return SchedulerResult("handled", "scheduler", "schedule", "\n".join(lines), "Here are your routines and reminders.")


def _actions_from_open_list(raw: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\s+and\s+|,", raw) if part.strip()]
    actions = []
    for part in parts:
        action = part if part.startswith("open ") else f"open {part}"
        normalised = _normalise(action)
        if normalised in SAFE_ROUTINE_ACTIONS:
            actions.append(normalised)
    return actions


def _is_risky_routine_action(action: str) -> bool:
    return action.startswith(("type ", "paste", "click ", "press ", "scroll ", "switch "))


def _next_run_timestamp(schedule: str | None) -> float | None:
    if not schedule:
        return None
    now = datetime.now()
    if schedule == "hourly":
        return (now + timedelta(hours=1)).timestamp()
    match = re.fullmatch(r"daily:([0-9]{2}):([0-9]{2})", schedule)
    if match:
        candidate = now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.timestamp()
    match = re.fullmatch(r"weekly:([0-6]):([0-9]{2}):([0-9]{2})", schedule)
    if match:
        weekday = int(match.group(1))
        days_ahead = (weekday - now.weekday()) % 7
        candidate = now + timedelta(days=days_ahead)
        candidate = candidate.replace(hour=int(match.group(2)), minute=int(match.group(3)), second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate.timestamp()
    return None


def _routine_name(raw: str) -> str:
    name = raw.strip().lower()
    if not name.endswith("routine") and name not in {"work setup", "coding routine"}:
        name = f"{name} routine"
    if name == "coding routine routine":
        return "coding routine"
    return name


def _routine_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "name": row["name"],
        "schedule": row["schedule"],
        "actions": json.loads(row["actions_json"] or "[]"),
        "enabled": bool(row["enabled"]),
        "next_run_at": row["next_run_at"],
        "next_run_label": _time_label(row["next_run_at"]),
    }


def _reminder_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "text": row["text"],
        "schedule": row["schedule"],
        "schedule_label": _schedule_label(row["schedule"]),
        "enabled": bool(row["enabled"]),
        "next_run_at": row["next_run_at"],
        "next_run_label": _time_label(row["next_run_at"]),
    }


def _schedule_label(schedule: str | None) -> str:
    if not schedule:
        return "manual"
    if schedule == "hourly":
        return "every hour"
    match = re.fullmatch(r"daily:([0-9]{2}):([0-9]{2})", schedule)
    if match:
        return f"daily at {int(match.group(1)):02d}:{match.group(2)}"
    return schedule


def _time_label(timestamp: float | None) -> str:
    if not timestamp:
        return "manual"
    return datetime.fromtimestamp(timestamp).strftime("%b %d, %I:%M %p").replace(" 0", " ")


def _normalise(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"[?!.\s]+$", "", value)
    return re.sub(r"\s+", " ", value)


def _record_scheduler_activity(category: str, action: str, target: str | None, detail: str | None, status: str) -> None:
    try:
        from grandpa.memory_context import record_activity

        record_activity(category, action, target, detail, status)
    except Exception:
        return


def _blocked(message: str) -> SchedulerResult:
    return SchedulerResult("blocked", "scheduler", "routine", message, message, permission="blocked")


def _fallback() -> SchedulerResult:
    return SchedulerResult("no_match", "scheduler", None, "", None, should_fallback=True)


__all__ = [
    "SchedulerResult",
    "SchedulerStore",
    "handle_scheduler_command",
    "run_routine",
    "scheduler_summary",
    "set_routine_enabled",
]
