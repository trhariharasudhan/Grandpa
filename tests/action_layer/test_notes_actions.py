"""Notes through the action layer: the first handler migrated off the waterfall.

These go through :func:`grandpa.action_layer.executor.execute` against a real
notes store in a temp directory, so what is being checked is the whole path --
catalogue entry, parameter validation, confirmation, the notes binding, and the
real files on disk.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grandpa.action_layer.catalogue import CATALOGUE, Binding, get
from grandpa.action_layer.executor import execute
from grandpa.action_layer.model import ActionRequest, Origin, RiskLevel
from grandpa.notes.models import NotesActionType

# Opted out of the default-deny actuation fixture (tests/actuation_guard.py):
pytestmark = pytest.mark.real_actions(
    reason="drives the real domain implementation against the store under the test's own GRANDPA_HOME"
)

NOTES_ACTIONS = tuple(
    spec for spec in CATALOGUE if spec.binding is Binding.NOTES_ACTION
)


@pytest.fixture(autouse=True)
def notes_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give each test its own notes directory and audit log.

    Patching ``DEFAULT_NOTES_DIR`` is not enough: ``NotesStore.__init__`` binds
    it as a default argument at definition time, so the module attribute is
    already spent. NotesAutomation builds the store, so that is where to inject.
    """
    from grandpa.notes.storage import NotesStore

    root = tmp_path / "notes"
    monkeypatch.setattr(
        "grandpa.notes.automation.NotesStore",
        lambda safety=None: NotesStore(root, safety=safety),
    )
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    return root


def act(action: str, confirm=None, **parameters):
    """Run one action the way the loop and chat do: rated from the catalogue."""
    spec = get(action)
    request = ActionRequest(
        action,
        parameters,
        origin=Origin.USER_CHAT,
        risk=spec.risk,
        requires_confirmation=spec.requires_confirmation,
    )
    return execute(request, confirm)


# --- the catalogue matches what notes can actually do -------------------------


def test_every_notes_action_the_parser_can_produce_is_catalogued() -> None:
    """Leaving some on the old path would mean two routes to the same store."""
    produced = set(NotesActionType.__args__)
    catalogued = {spec.action_alias for spec in NOTES_ACTIONS}

    assert produced == catalogued, produced ^ catalogued


def test_they_all_point_at_the_existing_notes_implementation() -> None:
    assert {spec.implementation for spec in NOTES_ACTIONS} == {
        "grandpa.notes.automation.NotesAutomation.execute"
    }


# --- the round trip -----------------------------------------------------------


def test_create_then_read_then_append_then_read(notes_home: Path) -> None:
    created = act("notes_create", title="Shopping", content="eggs")
    assert created.success is True, created
    assert 'Note created: "Shopping".' == created.message

    read = act("notes_read", title="Shopping")
    assert read.success is True, read
    assert "eggs" in read.message

    appended = act("notes_append", title="Shopping", content="milk")
    assert appended.success is True, appended

    again = act("notes_read", title="Shopping")
    assert "eggs" in again.message and "milk" in again.message


def test_list_and_search_find_what_was_created() -> None:
    act("notes_create", title="Roof repair", content="call the builder")
    act("notes_create", title="Birthday", content="buy a cake")

    listed = act("notes_list")
    assert "Roof repair" in listed.message and "Birthday" in listed.message

    found = act("notes_search", query="builder")
    assert found.success is True, found
    assert "Roof repair" in found.message


def test_rename_archive_restore_and_pin(notes_home: Path) -> None:
    act("notes_create", title="Draft", content="x")

    renamed = act("notes_rename", title="Draft", new_title="Final")
    assert renamed.success is True, renamed
    assert "Final" in renamed.message

    archived = act("notes_archive", title="Final")
    assert archived.success is True, archived
    assert "Final" not in act("notes_list").message

    restored = act("notes_restore", title="Final")
    assert restored.success is True, restored
    assert "Final" in act("notes_list").message

    assert act("notes_pin", title="Final").success is True
    assert act("notes_unpin", title="Final").success is True


def test_tags_survive_the_trip_as_a_tuple() -> None:
    """NotesAction.tags is a tuple; JSON gives a list."""
    result = act("notes_create", title="Tagged", content="x", tags=["home", "urgent"])

    assert result.success is True, result


# --- delete, which is the one that asks --------------------------------------


def test_delete_is_high_risk_and_asks() -> None:
    spec = get("notes_delete")

    assert spec.risk is RiskLevel.HIGH
    assert spec.requires_confirmation is True


def test_delete_with_no_way_to_ask_keeps_the_note(notes_home: Path) -> None:
    act("notes_create", title="Keepsake", content="x")

    result = act("notes_delete", title="Keepsake")

    assert result.error == "confirmation_required", result
    assert "Keepsake" in act("notes_list").message, "deleted with nobody asked"


def test_a_declined_delete_keeps_the_note(notes_home: Path) -> None:
    act("notes_create", title="Keepsake", content="x")

    result = act("notes_delete", title="Keepsake", confirm=lambda *_: False)

    assert result.error == "confirmation_declined", result
    assert "Keepsake" in act("notes_list").message, "deleted after answering no"


def test_an_approved_delete_removes_the_note(notes_home: Path) -> None:
    act("notes_create", title="Keepsake", content="x")
    asked = MagicMock(return_value=True)

    result = act("notes_delete", title="Keepsake", confirm=asked)

    assert result.success is True, result
    assert 'Note deleted: "Keepsake".' == result.message
    assert "Keepsake" not in act("notes_list").message

    action, parameters, risk = asked.call_args.args
    assert action == "notes_delete"
    assert parameters == {"title": "Keepsake"}
    assert risk is RiskLevel.HIGH


def test_notes_is_never_asked_a_second_time(notes_home: Path) -> None:
    """The layer holds the consent, so notes must not re-prompt for it.

    If ``confirmed=True`` were dropped, NotesAutomation would answer
    "needs_confirmation" and the note would survive an approved delete -- the
    decorative-prompt bug in a new place.
    """
    act("notes_create", title="Doomed", content="x")

    result = act("notes_delete", title="Doomed", confirm=lambda *_: True)

    assert result.data["status"] == "handled", result
    assert result.data.get("requires_confirmation") is not True


# --- validation still applies ------------------------------------------------


def test_a_missing_title_is_refused_before_notes_sees_it() -> None:
    result = act("notes_create")

    assert result.error == "invalid_parameters"
    assert "title" in result.message


def test_a_note_that_does_not_exist_is_an_error_not_a_crash() -> None:
    result = act("notes_read", title="never written")

    assert result.success is False
    assert "not found" in result.message.lower()


def test_the_action_is_audited_with_chat_as_the_origin(
    notes_home: Path, tmp_path: Path
) -> None:
    import json

    act("notes_create", title="Audited", content="x")

    records = [
        json.loads(line)
        for line in (tmp_path / "actions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert records[-1]["action_type"] == "notes_create"
    assert records[-1]["origin"] == "user_chat"
    assert records[-1]["ok"] is True
