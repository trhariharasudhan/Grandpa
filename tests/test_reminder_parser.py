from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from click.testing import CliRunner

from grandpa.cli.chat_cmd import _create_one_shot_reminder
from grandpa.cli.reminders_cmd import reminders
from grandpa.reminder_parser import ReminderParseError, parse_reminder_phrase
from grandpa.reminders import ReminderStore

pytestmark = pytest.mark.core


NOW = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)


def test_parse_in_30_minutes() -> None:
    parsed = parse_reminder_phrase(
        "Remind me in 30 minutes to drink water",
        now=NOW,
        timezone=UTC,
    )

    assert parsed.message == "drink water"
    assert parsed.due_at == NOW + timedelta(minutes=30)
    assert parsed.due_at.tzinfo is not None


def test_parse_in_2_hours() -> None:
    parsed = parse_reminder_phrase(
        "remind me in 2 hours to stretch",
        now=NOW,
        timezone=UTC,
    )

    assert parsed.message == "stretch"
    assert parsed.due_at == NOW + timedelta(hours=2)


def test_parse_today_at_future_time() -> None:
    parsed = parse_reminder_phrase(
        "remind me today at 9 PM to check email",
        now=NOW,
        timezone=UTC,
    )

    assert parsed.message == "check email"
    assert parsed.due_at == datetime(2026, 6, 13, 21, 0, tzinfo=UTC)


def test_parse_tomorrow_at_7_pm() -> None:
    parsed = parse_reminder_phrase(
        "Remind me tomorrow at 7 PM to call Arjun",
        now=NOW,
        timezone=UTC,
    )

    assert parsed.message == "call Arjun"
    assert parsed.due_at == datetime(2026, 6, 14, 19, 0, tzinfo=UTC)


def test_parse_explicit_iso_datetime() -> None:
    parsed = parse_reminder_phrase(
        "remind me at 2026-06-13T19:00:00+00:00 to join standup",
        now=NOW,
        timezone=UTC,
    )

    assert parsed.message == "join standup"
    assert parsed.due_at == datetime(2026, 6, 13, 19, 0, tzinfo=UTC)


def test_parse_month_name_date() -> None:
    parsed = parse_reminder_phrase(
        "Remind me on June 15 at 10:30 AM to attend the meeting",
        now=NOW,
        timezone=UTC,
    )

    assert parsed.message == "attend the meeting"
    assert parsed.due_at == datetime(2026, 6, 15, 10, 30, tzinfo=UTC)


def test_ambiguous_expression_rejected() -> None:
    with pytest.raises(ReminderParseError, match="Unsupported reminder time"):
        parse_reminder_phrase("remind me sometime soon to rest", now=NOW, timezone=UTC)


def test_ambiguous_time_rejected() -> None:
    with pytest.raises(ReminderParseError, match="Ambiguous reminder time"):
        parse_reminder_phrase("remind me today at 7 to rest", now=NOW, timezone=UTC)


def test_past_time_rejected() -> None:
    with pytest.raises(ReminderParseError, match="future"):
        parse_reminder_phrase("remind me today at 9 AM to rest", now=NOW, timezone=UTC)


def test_missing_message_rejected() -> None:
    with pytest.raises(ReminderParseError):
        parse_reminder_phrase("", now=NOW, timezone=UTC)


def test_cli_add_creates_reminder_from_phrase(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(
        reminders,
        ["add", "remind me at 2027-06-13T19:00:00+00:00 to call Arjun"],
    )

    assert result.exit_code == 0, result.output
    assert "Reminder created" in result.output
    saved = store.list()
    assert len(saved) == 1
    assert saved[0].message == "call Arjun"


def test_chat_creates_one_shot_reminder_from_natural_text(
    monkeypatch, tmp_path
) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    monkeypatch.setattr(
        "grandpa.reminder_parser.default_reminder_timezone",
        lambda: UTC,
    )

    message = _create_one_shot_reminder(
        "remind me in 30 minutes to drink water", store=store
    )

    reminders = store.list()
    assert message is not None
    assert "Reminder created" in message
    assert len(reminders) == 1
    assert reminders[0].message == "drink water"
    assert reminders[0].status == "pending"


def test_cli_add_reports_parse_errors(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(reminders, ["add", "remind me sometime soon to rest"])

    assert result.exit_code == 1
    assert "Unsupported reminder time" in result.output
    assert store.list() == []


def test_cli_list_defaults_to_pending_reminders(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    pending = store.create("pending reminder", NOW + timedelta(hours=1))
    cancelled = store.create("cancelled reminder", NOW + timedelta(hours=2))
    failed = store.create("failed reminder", NOW + timedelta(hours=3))
    store.cancel(cancelled.id, now=NOW)
    store.mark_failed(failed.id, "test failure", now=NOW)
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(reminders, ["list"])

    assert result.exit_code == 0, result.output
    assert pending.message in result.output
    assert "pending" in result.output
    assert cancelled.message not in result.output
    assert failed.message not in result.output


def test_cli_list_all_includes_cancelled_and_failed(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    pending = store.create("pending reminder", NOW + timedelta(hours=1))
    cancelled = store.create("cancelled reminder", NOW + timedelta(hours=2))
    failed = store.create("failed reminder", NOW + timedelta(hours=3))
    store.cancel(cancelled.id, now=NOW)
    store.mark_failed(failed.id, "test failure", now=NOW)
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(reminders, ["list", "--all"])

    assert result.exit_code == 0, result.output
    assert pending.message in result.output
    assert cancelled.message in result.output
    assert failed.message in result.output
    assert "cancelled" in result.output
    assert "failed" in result.output


def test_cli_list_status_cancelled_only(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    pending = store.create("pending reminder", NOW + timedelta(hours=1))
    cancelled = store.create("cancelled reminder", NOW + timedelta(hours=2))
    failed = store.create("failed reminder", NOW + timedelta(hours=3))
    store.cancel(cancelled.id, now=NOW)
    store.mark_failed(failed.id, "test failure", now=NOW)
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(reminders, ["list", "--status", "cancelled"])

    assert result.exit_code == 0, result.output
    assert cancelled.message in result.output
    assert "cancelled" in result.output
    assert pending.message not in result.output
    assert failed.message not in result.output


def test_cli_list_no_pending_message(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    cancelled = store.create("cancelled reminder", NOW + timedelta(hours=1))
    store.cancel(cancelled.id, now=NOW)
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(reminders, ["list"])

    assert result.exit_code == 0, result.output
    assert "No pending reminders found." in result.output
    assert store.list(status="cancelled")[0].message == "cancelled reminder"


def test_cli_cancel_pending_reminder_marks_cancelled(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    reminder = store.create("cancel from cli", NOW + timedelta(hours=1))
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(reminders, ["cancel", reminder.id])

    assert result.exit_code == 0, result.output
    assert "cancelled" in result.output
    assert store.get(reminder.id).status == "cancelled"  # type: ignore[union-attr]


def test_cli_clear_cancelled_reminders(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    pending = store.create("keep pending", NOW + timedelta(hours=1))
    first = store.create("cancelled one", NOW + timedelta(hours=2))
    second = store.create("cancelled two", NOW + timedelta(hours=3))
    store.cancel(first.id, now=NOW)
    store.cancel(second.id, now=NOW)
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(reminders, ["clear", "--status", "cancelled"])

    assert result.exit_code == 0, result.output
    assert "Deleted 2 cancelled reminders." in result.output
    assert store.get(pending.id) is not None
    assert store.get(first.id) is None
    assert store.get(second.id) is None


def test_cli_clear_failed_reminders(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    failed = store.create("failed reminder", NOW + timedelta(hours=1))
    store.mark_failed(failed.id, "test failure", now=NOW)
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(reminders, ["clear", "--status", "failed"])

    assert result.exit_code == 0, result.output
    assert "Deleted 1 failed reminder." in result.output
    assert store.get(failed.id) is None


def test_cli_clear_all_yes_clears_all_reminders(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    pending = store.create("pending reminder", NOW + timedelta(hours=1))
    cancelled = store.create("cancelled reminder", NOW + timedelta(hours=2))
    failed = store.create("failed reminder", NOW + timedelta(hours=3))
    store.cancel(cancelled.id, now=NOW)
    store.mark_failed(failed.id, "test failure", now=NOW)
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(reminders, ["clear", "--all", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Deleted 3 reminders." in result.output
    assert store.get(pending.id) is None
    assert store.get(cancelled.id) is None
    assert store.get(failed.id) is None


def test_cli_clear_status_does_not_delete_pending(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    pending = store.create("pending reminder", NOW + timedelta(hours=1))
    cancelled = store.create("cancelled reminder", NOW + timedelta(hours=2))
    store.cancel(cancelled.id, now=NOW)
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(reminders, ["clear", "--status", "cancelled"])

    assert result.exit_code == 0, result.output
    assert store.get(pending.id) is not None
    assert store.get(cancelled.id) is None


def test_cli_clear_reports_no_matches(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    store.create("pending reminder", NOW + timedelta(hours=1))
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(reminders, ["clear", "--status", "failed"])

    assert result.exit_code == 0, result.output
    assert "No reminders matched." in result.output


def test_cli_clear_keeps_default_list_pending_only(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    pending = store.create("pending reminder", NOW + timedelta(hours=1))
    cancelled = store.create("cancelled reminder", NOW + timedelta(hours=2))
    failed = store.create("failed reminder", NOW + timedelta(hours=3))
    store.cancel(cancelled.id, now=NOW)
    store.mark_failed(failed.id, "test failure", now=NOW)
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    clear_result = CliRunner().invoke(reminders, ["clear"])
    list_result = CliRunner().invoke(reminders, ["list"])

    assert clear_result.exit_code == 0, clear_result.output
    assert "Deleted 2 reminders." in clear_result.output
    assert list_result.exit_code == 0, list_result.output
    assert pending.message in list_result.output
    assert cancelled.message not in list_result.output
    assert failed.message not in list_result.output
