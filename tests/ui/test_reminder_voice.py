"""Reminders are said by the orb when they come due (Captain, 2026-11-26)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from grandpa.reminders import (
    NotificationResult,
    ReminderSchedulerService,
    ReminderStore,
)
from grandpa.ui.reminder_voice import OrbReminderNotifier


class Controller:
    def __init__(self, ok: bool = True) -> None:
        self.said: list[str] = []
        self.ok = ok

    def announce(self, text: str) -> bool:
        self.said.append(text)
        return self.ok


class Toast:
    def __init__(self, ok: bool) -> None:
        self.ok = ok

    def notify(self, reminder):
        return NotificationResult(self.ok, "x", "x")


def test_a_due_reminder_is_said_once(tmp_path) -> None:
    store = ReminderStore(tmp_path / "r.db")
    now = datetime(2026, 11, 26, 11, 0, tzinfo=UTC)
    store.create("drink water", now - timedelta(seconds=5))
    store.create("later thing", now + timedelta(hours=1))
    controller = Controller()
    service = ReminderSchedulerService(
        store, notifier=OrbReminderNotifier(controller, toast=Toast(False)), now_fn=lambda: now
    )
    service.tick()
    service.tick()
    assert controller.said == ["Reminder: drink water"]


def test_a_toast_alone_still_counts_and_nothing_at_all_fails() -> None:
    class R:
        message = "call amma"

    assert OrbReminderNotifier(Controller(ok=False), toast=Toast(True)).notify(R()).ok
    assert not OrbReminderNotifier(Controller(ok=False), toast=Toast(False)).notify(R()).ok


def test_the_orb_starts_the_reminders() -> None:
    from pathlib import Path

    source = Path("src/grandpa/cli/avatar_cmd.py").read_text(encoding="utf-8")
    assert "start_reminders(controller)" in source and "reminders.stop(" in source
