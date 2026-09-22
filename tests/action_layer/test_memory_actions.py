"""Memory through the action layer -- the first domain that needed a seam built.

Notes and downloads both had ``execute(action, ...)`` under their parser.
Memory had one function that parsed and performed together, with forget and
clear written inline. So the migration extracted ``parse_memory_command`` and
``execute_memory_action`` from the same bodies first. These tests check both
halves still line up, and that the one deliberate behaviour change -- a wipe
now asks -- actually holds.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grandpa.action_layer.catalogue import CATALOGUE, Binding, get
from grandpa.action_layer.executor import execute
from grandpa.action_layer.model import ActionRequest, Origin, RiskLevel
from grandpa.memory_context import (
    MEMORY_ACTIONS,
    MemoryStore,
    parse_memory_command,
)

# Opted out of the default-deny actuation fixture (tests/actuation_guard.py):
pytestmark = pytest.mark.real_actions(
    reason="drives the real domain implementation against the store under the test's own GRANDPA_HOME"
)

MEMORY_SPECS = tuple(
    spec for spec in CATALOGUE if spec.binding is Binding.MEMORY_ACTION
)


@pytest.fixture(autouse=True)
def memory_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "memory.db"
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(path))
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    return path


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


# --- the seam and the catalogue agree ----------------------------------------


def test_every_action_the_seam_exposes_is_catalogued() -> None:
    catalogued = {spec.action_alias for spec in MEMORY_SPECS}

    assert set(MEMORY_ACTIONS) == catalogued, set(MEMORY_ACTIONS) ^ catalogued


def test_they_all_point_at_the_extracted_seam() -> None:
    assert {spec.implementation for spec in MEMORY_SPECS} == {
        "grandpa.memory_context.execute_memory_action"
    }


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("remember that my dog is called Rex", ("remember", "my dog is called Rex")),
        ("forget my dog", ("forget", "my dog")),
        ("clear my memory", ("clear", "")),
        ("what do you know about me", ("profile", "")),
        ("what are my preferences", ("preferences", "")),
        ("what am i working on", ("projects", "")),
        ("what is my project", ("project_name", "")),
        ("what apps did i open today", ("apps_today", "")),
        ("what was i doing", ("recent_activity", "")),
        # Not ("continue_project", "roof") -- see the test below.
        ("continue my roof project", ("project_name", "")),
        ("the weather in Paris", None),
    ],
)
def test_the_parser_still_decides_what_it_always_did(phrase, expected) -> None:
    """The regexes were lifted out unchanged; this is the proof."""
    assert parse_memory_command(phrase) == expected


def test_continue_project_is_unreachable_and_that_is_pre_existing() -> None:
    """A dead branch the migration found rather than introduced.

    ``continue my <topic> project`` can never match: an earlier branch claims
    anything containing "project" and one of {enna, yenna, my, namma}, and the
    continue regex requires the literal "my". The catalogue still lists
    memory_continue_project because the action layer *can* reach it by name --
    which is more than the parser could. Left as found; reordering chat's
    matcher is not this task.
    """
    assert parse_memory_command("continue my roof project") == ("project_name", "")
    assert parse_memory_command("continue my project") == ("project_name", "")

    # Reachable through the layer, which does not go through the regexes.
    from grandpa.action_layer.catalogue import get

    assert get("memory_continue_project").action_alias == "continue_project"


# --- the round trip -----------------------------------------------------------


def test_remember_then_recall(memory_db: Path) -> None:
    remembered = act("memory_remember", subject="my dog is called Rex")
    assert remembered.success is True, remembered

    recalled = act("memory_recall", subject="dog")
    assert recalled.success is True, recalled
    assert "Rex" in recalled.message


def test_forget_removes_without_asking(memory_db: Path) -> None:
    """Targeted forget has never prompted, and the migration kept that."""
    act("memory_remember", subject="my dog is called Rex")
    asked = MagicMock(return_value=True)

    forgotten = act("memory_forget", subject="dog", confirm=asked)

    assert forgotten.success is True, forgotten
    asked.assert_not_called()
    assert "Rex" not in act("memory_recall", subject="dog").message


def test_the_reads_need_no_arguments_and_do_not_ask() -> None:
    for action in (
        "memory_profile",
        "memory_preferences",
        "memory_projects",
        "memory_apps_today",
        "memory_recent_activity",
    ):
        spec = get(action)
        assert spec.risk is RiskLevel.LOW, action
        assert spec.requires_confirmation is False, action
        assert act(action).success is True, action


# --- the one deliberate change -----------------------------------------------


def test_clearing_everything_is_high_risk_and_asks() -> None:
    spec = get("memory_clear")

    assert spec.risk is RiskLevel.HIGH
    assert spec.requires_confirmation is True


def test_a_wipe_with_nobody_to_ask_keeps_the_memories(memory_db: Path) -> None:
    act("memory_remember", subject="my dog is called Rex")

    result = act("memory_clear")

    assert result.error == "confirmation_required", result
    assert "Rex" in act("memory_recall", subject="dog").message, "wiped unasked"


def test_a_declined_wipe_keeps_the_memories(memory_db: Path) -> None:
    act("memory_remember", subject="my dog is called Rex")

    result = act("memory_clear", confirm=lambda *_: False)

    assert result.error == "confirmation_declined", result
    assert "Rex" in act("memory_recall", subject="dog").message


def test_an_approved_wipe_erases_them(memory_db: Path) -> None:
    act("memory_remember", subject="my dog is called Rex")

    result = act("memory_clear", confirm=lambda *_: True)

    assert result.success is True, result
    assert "Rex" not in act("memory_recall", subject="dog").message


def test_the_store_is_untouched_by_a_refusal(memory_db: Path) -> None:
    """The point of the tier: refusing must not half-clear anything."""
    act("memory_remember", subject="my dog is called Rex")
    act("memory_remember", subject="my project is Grandpa")

    act("memory_clear", confirm=lambda *_: False)

    store = MemoryStore(memory_db)
    try:
        assert len(store.list_memories()) >= 2
    finally:
        store.close()
