from pathlib import Path
import time

from grandpa import local_actions, task_scheduler
from grandpa.local_actions import LocalActionResult
from grandpa.scheduler_daemon import BackgroundSchedulerDaemon
from grandpa.task_scheduler import SchedulerStore, execute_due_once


def _store(tmp_path: Path) -> SchedulerStore:
    return SchedulerStore(tmp_path / "scheduler.db")


def _make_due(store: SchedulerStore, table: str, item_id: int) -> None:
    with store._connect() as conn:
        conn.execute(f"UPDATE {table} SET next_run_at = 1 WHERE id = ?", (item_id,))


def test_execute_due_reminder_creates_notification(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(task_scheduler, "_record_scheduler_activity", lambda *args: None)
    store = _store(tmp_path)
    reminder = store.add_reminder("stretch", "minutely")
    now = time.time()
    _make_due(store, "reminders", reminder["id"])

    result = execute_due_once(store, now=now)

    assert result["reminders_triggered"] == 1
    notifications = store.list_notifications()
    assert notifications[0]["message"] == "Reminder: stretch"
    assert store.get_reminder(reminder["id"])["next_run_at"] > now


def test_execute_due_routine_runs_safe_actions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(task_scheduler, "_record_scheduler_activity", lambda *args: None)
    calls: list[str] = []

    def fake_handle(action: str, execute: bool = True) -> LocalActionResult:
        calls.append(action)
        return LocalActionResult("handled", "app", action, f"ran {action}", f"ran {action}")

    monkeypatch.setattr(local_actions, "handle_local_action", fake_handle)
    store = _store(tmp_path)
    routine = store.upsert_routine("morning routine", ["open chrome"], schedule="daily:09:00")
    now = time.time()
    _make_due(store, "routines", routine["id"])

    result = execute_due_once(store, now=now)

    assert result["routines_run"] == 1
    assert calls == ["open chrome"]
    updated = store.get_routine("morning routine")
    assert updated["last_status"] == "handled"
    assert updated["next_run_at"] > now


def test_daemon_tick_reports_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(task_scheduler, "_record_scheduler_activity", lambda *args: None)
    daemon = BackgroundSchedulerDaemon(store=_store(tmp_path), poll_interval_seconds=0.1)

    result = daemon.tick()
    status = daemon.status()

    assert result["status"] == "ok"
    assert status["last_tick_at"] is not None
    assert status["last_error"] is None
