"""Reminders and routines: two stores, catalogued as two things.

The audit found that chat's reminder handling spans reminders.db and
scheduler.db, and that "remind me to X at 5pm" becomes a daily rule rather than
a one-off. Neither is fixed here. These tests pin the behaviour as it is, so
that when someone does fix it the change is visible rather than silent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.action_layer.catalogue import CATALOGUE, Binding, get
from grandpa.action_layer.executor import execute
from grandpa.action_layer.model import ActionRequest, Origin, RiskLevel
from grandpa.reminders import REMINDER_ACTIONS, parse_reminder_intent
from grandpa.task_scheduler import SCHEDULER_ACTIONS, parse_scheduler_command

# Opted out of the default-deny actuation fixture (tests/actuation_guard.py):
pytestmark = pytest.mark.real_actions(
    reason="drives the real domain implementation against the store under the test's own GRANDPA_HOME"
)

REMINDER_SPECS = tuple(
    spec for spec in CATALOGUE if spec.binding is Binding.REMINDER_ACTION
)
SCHEDULER_SPECS = tuple(
    spec for spec in CATALOGUE if spec.binding is Binding.SCHEDULER_ACTION
)


@pytest.fixture(autouse=True)
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from grandpa.reminders import ReminderStore
    from grandpa.task_scheduler import SchedulerStore

    monkeypatch.setattr(
        "grandpa.reminders.ReminderStore",
        lambda *a, **k: ReminderStore(tmp_path / "reminders.db"),
    )
    monkeypatch.setattr(
        "grandpa.task_scheduler.SchedulerStore",
        lambda *a, **k: SchedulerStore(tmp_path / "scheduler.db"),
    )
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))


def act(action: str, confirm=None, **parameters):
    spec = get(action)
    return execute(
        ActionRequest(
            action,
            parameters,
            origin=Origin.USER_CHAT,
            risk=spec.risk,
            requires_confirmation=spec.requires_confirmation,
        ),
        confirm,
    )


# --- both seams are fully catalogued -----------------------------------------


def test_every_reminder_action_is_catalogued() -> None:
    assert set(REMINDER_ACTIONS) == {spec.action_alias for spec in REMINDER_SPECS}


def test_every_scheduler_action_is_catalogued() -> None:
    assert set(SCHEDULER_ACTIONS) == {spec.action_alias for spec in SCHEDULER_SPECS}


def test_they_point_at_their_own_domains() -> None:
    assert {spec.implementation for spec in REMINDER_SPECS} == {
        "grandpa.reminders.execute_reminder_action"
    }
    assert {spec.implementation for spec in SCHEDULER_SPECS} == {
        "grandpa.task_scheduler.execute_scheduler_action"
    }


# --- one-shot reminders -------------------------------------------------------


def test_create_then_list_then_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC

    monkeypatch.setattr(
        "grandpa.reminder_parser.default_reminder_timezone", lambda: UTC
    )

    created = act("reminder_create", subject="remind me in 30 minutes to drink water")
    assert created.success is True, created
    assert "Reminder created" in created.message
    reminder_id = created.data["target"]

    listed = act("reminder_list")
    assert "drink water" in listed.message

    cancelled = act("reminder_cancel", subject=reminder_id)
    assert cancelled.success is True, cancelled
    assert "cancelled" in cancelled.message.lower()


def test_a_phrase_with_no_time_is_not_a_reminder() -> None:
    assert parse_reminder_intent("tell me about the weather") is None


def test_cancelling_something_that_is_not_there_says_so() -> None:
    result = act("reminder_cancel", subject="no-such-id")

    assert result.success is False
    assert "not found" in result.message.lower()


# --- routines -----------------------------------------------------------------


def test_create_list_disable_and_enable_a_routine() -> None:
    created = act("routine_create_morning")
    assert created.success is True, created

    assert "morning routine" in act("routine_list").message.lower()

    disabled = act("routine_disable", name="morning")
    assert disabled.success is True, disabled
    assert "Disabled" in disabled.message

    enabled = act("routine_enable", name="morning")
    assert enabled.success is True, enabled
    assert "Enabled" in enabled.message


def test_a_routine_of_unsafe_actions_is_refused() -> None:
    result = act("routine_set_morning", targets="format the disk")

    assert result.success is False
    assert "blocked" in result.message.lower()


# --- the two findings, pinned as they are ------------------------------------


def test_remind_me_at_a_time_is_read_by_the_scheduler_as_daily() -> None:
    """Audit finding, left as found: this repeats every day, not once.

    The one-shot parser claims most "remind me" phrasings first, so this is
    what the scheduler does with the ones that reach it. Catalogued honestly
    rather than quietly corrected -- fixing it is its own task.
    """
    parsed = parse_scheduler_command("remind me to stretch at 5pm")

    assert parsed is not None
    action, parameters = parsed
    assert action == "create_recurring_reminder"
    assert parameters["schedule"] == "daily:17:00", parameters


def test_the_two_reminder_kinds_are_separate_actions_on_separate_stores() -> None:
    """Not a cosmetic split: they are different databases."""
    from grandpa.reminders import DEFAULT_REMINDER_DB
    from grandpa.task_scheduler import DEFAULT_SCHEDULER_DB

    assert DEFAULT_REMINDER_DB != DEFAULT_SCHEDULER_DB
    assert get("reminder_create").implementation != (
        get("routine_create_reminder").implementation
    )


def test_a_recurring_reminder_lands_in_the_scheduler_store(tmp_path: Path) -> None:
    result = act("routine_create_reminder", text="stretch", schedule="hourly")

    assert result.success is True, result
    assert "Reminder set" in result.message
    assert "stretch" in act("routine_list").message
    # And not in the one-shot store.
    assert "stretch" not in act("reminder_list").message


# --- tiers --------------------------------------------------------------------


def test_reading_is_low_and_changing_is_medium() -> None:
    assert get("reminder_list").risk is RiskLevel.LOW
    assert get("routine_list").risk is RiskLevel.LOW
    assert get("reminder_create").risk is RiskLevel.LOW
    for action in (
        "reminder_cancel",
        "routine_create_morning",
        "routine_run",
        "routine_create_reminder",
    ):
        assert get(action).risk is RiskLevel.MEDIUM, action


def test_none_of_them_ask() -> None:
    """None of these destroys anything, and none asked before the migration."""
    for spec in REMINDER_SPECS + SCHEDULER_SPECS:
        assert spec.requires_confirmation is False, spec.name
