from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from grandpa.reminders import (
    NotificationResult,
    ReminderSchedulerService,
    ReminderStore,
    WindowsToastNotifier,
)
from grandpa.scheduler_daemon import BackgroundSchedulerDaemon
from grandpa.task_scheduler import SchedulerStore

pytestmark = pytest.mark.core


class FakeNotifier:
    def __init__(self, *, ok: bool = True, raises: Exception | None = None) -> None:
        self.ok = ok
        self.raises = raises
        self.sent: list[str] = []

    def notify(self, reminder):
        if self.raises:
            raise self.raises
        self.sent.append(reminder.id)
        return NotificationResult(self.ok, "sent" if self.ok else "failed", "fake", backend="fake", warning=None)


def _store(tmp_path) -> ReminderStore:
    return ReminderStore(tmp_path / "reminders.db")


def _routine_store(tmp_path) -> SchedulerStore:
    return SchedulerStore(tmp_path / "scheduler.db")


def _at(offset_seconds: int = 0) -> datetime:
    return datetime(2026, 6, 13, 12, 0, tzinfo=UTC) + timedelta(seconds=offset_seconds)


def test_reminder_creation_persists(tmp_path):
    store = _store(tmp_path)

    reminder = store.create("call Arjun", _at(60), source={"test": True})

    assert reminder.id
    assert reminder.status == "pending"
    assert reminder.due_at.tzinfo is not None
    restored = ReminderStore(tmp_path / "reminders.db").get(reminder.id)
    assert restored is not None
    assert restored.message == "call Arjun"
    assert restored.source == {"test": True}


def test_due_reminder_triggers_exactly_once(tmp_path):
    store = _store(tmp_path)
    reminder = store.create("stretch", _at(-30))
    notifier = FakeNotifier()
    service = ReminderSchedulerService(store, notifier=notifier, now_fn=lambda: _at())

    first = service.tick()
    second = service.tick()

    assert first["triggered"] == [reminder.id]
    assert second["triggered"] == []
    assert notifier.sent == [reminder.id]
    assert store.get(reminder.id).status == "triggered"  # type: ignore[union-attr]


def test_future_reminder_does_not_trigger_early(tmp_path):
    store = _store(tmp_path)
    store.create("future", _at(300))
    notifier = FakeNotifier()
    service = ReminderSchedulerService(store, notifier=notifier, now_fn=lambda: _at())

    result = service.tick()

    assert result["triggered"] == []
    assert notifier.sent == []


def test_cancelled_reminder_never_triggers(tmp_path):
    store = _store(tmp_path)
    reminder = store.create("cancel me", _at(-30))
    store.cancel(reminder.id, now=_at(-20))
    notifier = FakeNotifier()
    service = ReminderSchedulerService(store, notifier=notifier, now_fn=lambda: _at())

    result = service.tick()

    assert result["triggered"] == []
    assert notifier.sent == []
    assert store.get(reminder.id).status == "cancelled"  # type: ignore[union-attr]


def test_triggered_reminder_does_not_trigger_again_after_restart(tmp_path):
    store = _store(tmp_path)
    reminder = store.create("restart proof", _at(-30))
    notifier = FakeNotifier()
    ReminderSchedulerService(store, notifier=notifier, now_fn=lambda: _at()).tick()

    restarted_notifier = FakeNotifier()
    restarted_store = ReminderStore(tmp_path / "reminders.db")
    result = ReminderSchedulerService(restarted_store, notifier=restarted_notifier, now_fn=lambda: _at(30)).tick()

    assert result["triggered"] == []
    assert restarted_notifier.sent == []
    assert restarted_store.get(reminder.id).status == "triggered"  # type: ignore[union-attr]


def test_recent_overdue_reminder_triggers_once_on_startup(tmp_path):
    store = _store(tmp_path)
    reminder = store.create("recent overdue", _at(-9 * 60))
    notifier = FakeNotifier()
    service = ReminderSchedulerService(store, notifier=notifier, now_fn=lambda: _at())

    result = service.tick()

    assert result["triggered"] == [reminder.id]
    assert notifier.sent == [reminder.id]


def test_stale_overdue_reminder_marked_failed_without_notification(tmp_path):
    store = _store(tmp_path)
    reminder = store.create("stale overdue", _at(-11 * 60))
    notifier = FakeNotifier()
    service = ReminderSchedulerService(store, notifier=notifier, now_fn=lambda: _at())

    result = service.tick()

    assert result["triggered"] == []
    assert result["failed"] == [reminder.id]
    assert notifier.sent == []
    saved = store.get(reminder.id)
    assert saved is not None
    assert saved.status == "failed"
    assert "older than 10 minutes" in (saved.failure_reason or "")


def test_notification_failure_marks_failed_without_crashing(tmp_path):
    store = _store(tmp_path)
    reminder = store.create("notify failure", _at(-30))
    service = ReminderSchedulerService(store, notifier=FakeNotifier(ok=False), now_fn=lambda: _at())

    result = service.tick()

    assert result["failed"] == [reminder.id]
    assert store.get(reminder.id).status == "failed"  # type: ignore[union-attr]


def test_notification_exception_marks_failed_without_crashing(tmp_path):
    store = _store(tmp_path)
    reminder = store.create("notify exception", _at(-30))
    service = ReminderSchedulerService(store, notifier=FakeNotifier(raises=RuntimeError("toast failed")), now_fn=lambda: _at())

    result = service.tick()

    assert result["failed"] == [reminder.id]
    saved = store.get(reminder.id)
    assert saved is not None
    assert saved.status == "failed"
    assert "toast failed" in (saved.failure_reason or "")


def test_duplicate_scheduler_start_is_prevented(tmp_path):
    store = _store(tmp_path)
    service = ReminderSchedulerService(store, notifier=FakeNotifier(), poll_interval_seconds=60)

    first = service.start()
    second = service.start()
    service.stop()

    assert first is True
    assert second is False


def test_background_daemon_starts_and_stops_reminder_processing(tmp_path):
    daemon = BackgroundSchedulerDaemon(
        store=_routine_store(tmp_path),
        reminder_store=_store(tmp_path),
        reminder_notifier=FakeNotifier(),
        poll_interval_seconds=60,
        now_fn=lambda: _at(),
    )

    daemon.start()
    first_thread = daemon._thread
    daemon.start()
    assert daemon._thread is first_thread
    assert daemon.status()["running"] is True
    assert daemon.status()["reminders"]["running"] is True
    assert daemon.status()["reminders"]["hosted_by_daemon"] is True

    daemon.stop()

    assert daemon.status()["running"] is False


def test_background_daemon_triggers_reminder_without_manual_cli_run_due(tmp_path):
    routine_store = _routine_store(tmp_path)
    reminder_store = _store(tmp_path)
    reminder = reminder_store.create("daemon reminder", _at(-30))
    notifier = FakeNotifier()
    daemon = BackgroundSchedulerDaemon(
        store=routine_store,
        reminder_store=reminder_store,
        reminder_notifier=notifier,
        now_fn=lambda: _at(),
    )

    result = daemon.tick()

    assert result["reminders_triggered"] == 1
    assert result["reminders"]["triggered"] == [reminder.id]
    assert notifier.sent == [reminder.id]


def test_reminder_created_before_restart_fires_after_restart(tmp_path):
    reminder_db = tmp_path / "reminders.db"
    routine_db = tmp_path / "scheduler.db"
    initial_store = ReminderStore(reminder_db)
    reminder = initial_store.create("after restart", _at(-30))

    restarted_store = ReminderStore(reminder_db)
    notifier = FakeNotifier()
    daemon = BackgroundSchedulerDaemon(
        store=SchedulerStore(routine_db),
        reminder_store=restarted_store,
        reminder_notifier=notifier,
        now_fn=lambda: _at(),
    )

    result = daemon.tick()

    assert result["reminders"]["triggered"] == [reminder.id]
    assert notifier.sent == [reminder.id]
    assert restarted_store.get(reminder.id).status == "triggered"  # type: ignore[union-attr]


def test_application_startup_starts_and_shutdown_stops_scheduler(monkeypatch):
    pytest.importorskip("fastapi")

    from fastapi.testclient import TestClient

    from grandpa.server.app import create_app

    class FakeDaemon:
        instances: list["FakeDaemon"] = []

        def __init__(self):
            self.started = False
            self.stopped = False
            FakeDaemon.instances.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def status(self):
            return {"running": self.started and not self.stopped}

    monkeypatch.setattr("grandpa.scheduler_daemon.BackgroundSchedulerDaemon", FakeDaemon)
    engine = MagicMock()
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    app = create_app(engine, "test-model")

    with TestClient(app):
        assert FakeDaemon.instances[-1].started is True
        assert FakeDaemon.instances[-1].stopped is False

    assert FakeDaemon.instances[-1].stopped is True


def test_missing_windows_notification_backend_gives_setup_guidance(monkeypatch, tmp_path):
    reminder = _store(tmp_path).create("notify me", _at())
    monkeypatch.setattr("grandpa.reminders.platform.system", lambda: "Windows")
    monkeypatch.setattr("grandpa.reminders.importlib.util.find_spec", lambda _name: None)

    result = WindowsToastNotifier().notify(reminder)

    assert result.ok is False
    assert result.status == "setup_required"
    assert "uv sync --extra windows-notifications" in (result.warning or "")


def test_naive_datetime_is_rejected(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="timezone"):
        store.create("bad date", datetime(2026, 6, 13, 12, 0))
