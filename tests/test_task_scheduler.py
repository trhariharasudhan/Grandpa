from pathlib import Path

from grandpa import task_scheduler
from grandpa.task_scheduler import SchedulerStore, handle_scheduler_command


def _store(tmp_path: Path) -> SchedulerStore:
    return SchedulerStore(tmp_path / "scheduler.db")


def test_create_and_list_morning_routine(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(task_scheduler, "_record_scheduler_activity", lambda *args: None)
    store = _store(tmp_path)

    created = handle_scheduler_command("create a morning routine", store=store, execute=False)
    listed = handle_scheduler_command("what routines do I have?", store=store, execute=False)

    assert created.status == "handled"
    assert "morning routine" in created.message
    assert "morning routine" in listed.message


def test_every_morning_open_allowlisted_apps(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(task_scheduler, "_record_scheduler_activity", lambda *args: None)
    store = _store(tmp_path)

    result = handle_scheduler_command("Every morning open Chrome and VS Code", store=store, execute=False)
    routine = store.get_routine("morning routine")

    assert result.status == "handled"
    assert routine is not None
    assert routine["actions"] == ["open chrome", "open vs code"]


def test_reminder_every_hour(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(task_scheduler, "_record_scheduler_activity", lambda *args: None)
    store = _store(tmp_path)

    result = handle_scheduler_command("remind me every hour to drink water", store=store, execute=False)
    reminders = store.list_reminders()

    assert result.status == "handled"
    assert reminders[0]["text"] == "drink water"
    assert reminders[0]["schedule"] == "hourly"


def test_disable_routine(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(task_scheduler, "_record_scheduler_activity", lambda *args: None)
    store = _store(tmp_path)
    handle_scheduler_command("create a morning routine", store=store, execute=False)

    result = handle_scheduler_command("disable my morning routine", store=store, execute=False)

    assert result.status == "handled"
    assert store.get_routine("morning routine")["enabled"] is False


def test_unrelated_question_falls_back(tmp_path: Path) -> None:
    result = handle_scheduler_command("What is Python?", store=_store(tmp_path), execute=False)

    assert result.should_fallback is True
