from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from click.testing import CliRunner

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
        ["add", "remind me at 2026-06-13T19:00:00+00:00 to call Arjun"],
    )

    assert result.exit_code == 0, result.output
    assert "Reminder created" in result.output
    saved = store.list()
    assert len(saved) == 1
    assert saved[0].message == "call Arjun"


def test_cli_add_reports_parse_errors(monkeypatch, tmp_path) -> None:
    store = ReminderStore(tmp_path / "reminders.db")
    monkeypatch.setattr("grandpa.cli.reminders_cmd.ReminderStore", lambda: store)

    result = CliRunner().invoke(reminders, ["add", "remind me sometime soon to rest"])

    assert result.exit_code == 1
    assert "Unsupported reminder time" in result.output
    assert store.list() == []
