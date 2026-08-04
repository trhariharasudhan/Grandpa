"""Tests for the safe Google Calendar automation foundation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from grandpa.calendar import (
    CalendarAction,
    CalendarAuthManager,
    CalendarAutomation,
    CalendarEventSummary,
    CalendarParser,
)
from grandpa.calendar.auth import CalendarAuthStatus
from grandpa.calendar.safety import CalendarSafetyPolicy
from grandpa.cli.chat_cmd import _handle_calendar_slash_command
from grandpa.cli.doctor_cmd import _check_calendar_readiness
from grandpa.cli.slash_commands import get_command
from grandpa.voice.assistant import VoiceCommandProcessor
from grandpa.voice.operator import (
    execute_voice_operator_intent,
    parse_voice_operator_command,
)


class FakeCalendarClient:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.updated: list[tuple[str, dict[str, object]]] = []
        self.deleted: list[str] = []

    def account(self) -> str:
        return "hari@example.com"

    def list_events(
        self, date_range: str = "today", *, query: str = "", limit: int = 10
    ) -> tuple[CalendarEventSummary, ...]:
        events = (
            CalendarEventSummary(
                "event-1",
                title="Grandpa planning",
                start="2026-07-16T15:00:00+05:30",
                end="2026-07-16T16:00:00+05:30",
                location="Desk",
                attendees=("arjun@example.com",),
                description="Discuss API token: abcdefgh123456",
            ),
            CalendarEventSummary(
                "event-2",
                title="Review",
                start="2026-07-17T10:00:00+05:30",
                end="2026-07-17T10:30:00+05:30",
            ),
        )
        if "missing" in query:
            return ()
        return events[:limit]

    def search_events(
        self, query: str, *, limit: int = 10
    ) -> tuple[CalendarEventSummary, ...]:
        return self.list_events("upcoming", query=query, limit=limit)

    def create_event(
        self,
        *,
        title: str,
        start_text: str,
        duration_minutes: int = 60,
        timezone: str = "",
    ) -> str:
        self.created.append(
            {
                "title": title,
                "start_text": start_text,
                "duration_minutes": duration_minutes,
                "timezone": timezone,
            }
        )
        return "created-1"

    def update_event(
        self,
        event_id: str,
        *,
        title: str = "",
        start_text: str = "",
        duration_minutes: int = 60,
    ) -> str:
        self.updated.append(
            (
                event_id,
                {
                    "title": title,
                    "start_text": start_text,
                    "duration_minutes": duration_minutes,
                },
            )
        )
        return event_id

    def delete_event(self, event_id: str) -> None:
        self.deleted.append(event_id)

    def freebusy(self, date_range: str = "this afternoon") -> tuple[str, ...]:
        return (f"{date_range}: 2:00 PM - 3:00 PM",)


def test_parser_handles_core_calendar_commands() -> None:
    parser = CalendarParser()

    assert parser.parse("calendar setup") == CalendarAction("setup")
    assert parser.parse("calendar disconnect") == CalendarAction("disconnect")
    assert parser.parse("What is on my calendar today?") == CalendarAction(
        "list", date_range="today"
    )
    assert parser.parse("What meetings do I have tomorrow?") == CalendarAction(
        "list", date_range="tomorrow"
    )
    assert parser.parse("Show free time this afternoon") == CalendarAction(
        "freebusy", date_range="this afternoon"
    )
    assert parser.parse("Create a meeting tomorrow at 3 PM").action == "create"


def test_safety_redacts_event_text_and_requires_write_confirmation() -> None:
    safety = CalendarSafetyPolicy()

    redacted = safety.sanitize_text("API token: abcdefgh123456")

    assert "[redacted]" in redacted
    assert safety.requires_confirmation("create") is True
    assert safety.requires_confirmation("list") is False
    assert safety.is_blocked("accept_invitation") is True


def test_read_events_and_freebusy_are_direct() -> None:
    automation = CalendarAutomation(client=FakeCalendarClient())

    today = automation.handle("what is on my calendar today")
    free = automation.handle("show free time this afternoon")

    assert today.status == "handled"
    assert "Grandpa planning" in today.message
    assert "event-1" not in today.message
    assert free.status == "handled"
    assert "2:00 PM" in free.message


def test_create_update_delete_require_confirmation() -> None:
    automation = CalendarAutomation(client=FakeCalendarClient())

    create = automation.handle("create a meeting tomorrow at 3 PM")
    update = automation.handle("move my meeting to 4 PM")
    delete = automation.handle("cancel tomorrow's meeting")

    assert create.status == "needs_confirmation"
    assert update.status == "needs_confirmation"
    assert delete.status == "needs_confirmation"


def test_confirmed_write_actions_execute_through_client() -> None:
    client = FakeCalendarClient()
    automation = CalendarAutomation(client=client)

    created = automation.handle("create a meeting tomorrow at 3 PM", confirmed=True)
    updated = automation.handle("move my meeting to 4 PM", confirmed=True)
    deleted = automation.handle("cancel tomorrow's meeting", confirmed=True)

    assert created.status == "handled"
    assert client.created[0]["start_text"] == "tomorrow at 3 PM"
    assert updated.status == "handled"
    assert client.updated[0][0] == "event-1"
    assert deleted.status == "handled"
    assert client.deleted == ["event-1"]


def test_auto_accept_invitations_are_blocked() -> None:
    automation = CalendarAutomation(client=FakeCalendarClient())

    result = automation.handle("accept invitation")

    assert result.status == "blocked"
    assert "will not auto-accept" in result.message


def test_calendar_slash_command_routes_through_safe_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_handle(text: str):
        calls.append(text)
        return SimpleNamespace(message="Calendar today shown.")

    monkeypatch.setattr("grandpa.calendar.handle_calendar_command", fake_handle)

    assert _handle_calendar_slash_command("/calendar today") == "Calendar today shown."
    assert calls == ["calendar today"]


def test_calendar_slash_command_is_registered_for_picker() -> None:
    command = get_command("/calendar")

    assert command is not None
    assert command.category == "Memory & Productivity"
    assert "/calendar today" in command.subcommands


def test_voice_assistant_routes_calendar_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "grandpa.calendar.handle_calendar_command",
        lambda _text: SimpleNamespace(
            should_fallback=False,
            message="No calendar events found.",
            status="handled",
            action=SimpleNamespace(query=""),
        ),
    )
    processor = VoiceCommandProcessor()

    response = processor._handle_local_pipeline("what is on my calendar today")

    assert response is not None
    assert response.kind == "calendar"
    assert response.text == "No calendar events found."


def test_voice_operator_routes_calendar_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = parse_voice_operator_command("show free time this afternoon")
    assert intent.kind == "calendar"

    monkeypatch.setattr(
        "grandpa.calendar.handle_calendar_command",
        lambda _text: SimpleNamespace(
            status="handled",
            message="Free time:\n- 2 PM",
            requires_confirmation=False,
        ),
    )

    result = execute_voice_operator_intent(intent)

    assert result.status == "handled"
    assert result.action["action_type"] == "calendar"


def test_auth_status_and_disconnect_use_local_credential_paths(tmp_path: Path) -> None:
    client_secret = tmp_path / "calendar_client_secret.json"
    token = tmp_path / "calendar_token.json"
    manager = CalendarAuthManager(token_path=token, client_secret_path=client_secret)

    assert manager.status().configured is False

    client_secret.write_text("{}", encoding="utf-8")
    assert manager.status().configured is True
    assert manager.status().ready is False

    token.write_text('{"account": "hari@example.com"}', encoding="utf-8")
    assert manager.status().ready is True
    assert manager.status().account == "hari@example.com"
    assert manager.disconnect() is True
    assert not token.exists()


def test_doctor_reports_unconfigured_calendar_as_optional(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeAuth:
        def status(self):
            return CalendarAuthStatus(
                configured=False,
                ready=False,
                message="not configured",
                token_path=tmp_path / "token.json",
                client_secret_path=tmp_path / "secret.json",
            )

    monkeypatch.setattr("grandpa.calendar.CalendarAuthManager", FakeAuth)

    result = _check_calendar_readiness()

    assert result.status == "info"
    assert "Optional" in result.message
