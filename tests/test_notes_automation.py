"""Tests for Grandpa's safe local notes system."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from grandpa.cli.chat_cmd import _handle_notes_slash_command
from grandpa.cli.doctor_cmd import _check_notes_readiness
from grandpa.cli.slash_commands import get_command
from grandpa.notes import (
    NotesAction,
    NotesAutomation,
    NotesParser,
    NotesStore,
    handle_notes_command,
)
from grandpa.notes.safety import NotesSafetyError, NotesSafetyPolicy
from grandpa.voice.assistant import VoiceCommandProcessor
from grandpa.voice.operator import (
    execute_voice_operator_intent,
    parse_voice_operator_command,
)


def test_create_append_open_and_search_notes(tmp_path) -> None:
    store = NotesStore(tmp_path)
    automation = NotesAutomation(store=store)

    created = automation.handle("create a note called Grandpa Ideas")
    appended = automation.handle("append this to my grandpa ideas note browser automation plan")
    opened = automation.handle("open my note Grandpa Ideas")
    searched = automation.handle("search notes for browser automation")

    assert created.status == "handled"
    assert 'Note created: "Grandpa Ideas"' in created.message
    assert appended.status == "handled"
    assert opened.status == "handled"
    assert "browser automation plan" in opened.message
    assert searched.status == "handled"
    assert "Grandpa Ideas" in searched.message


def test_rename_pin_archive_restore_and_recent_notes(tmp_path) -> None:
    store = NotesStore(tmp_path)
    automation = NotesAutomation(store=store)
    automation.handle("create a note called Project Notes")

    renamed = automation.handle("rename note Project Notes to Grandpa Project Notes")
    pinned = automation.handle("pin note Grandpa Project Notes")
    archived = automation.handle("archive note Grandpa Project Notes")
    list_visible = automation.handle("show my notes")
    restored = automation.handle("restore note Grandpa Project Notes")
    recent = automation.handle("list recent notes")

    assert renamed.status == "handled"
    assert pinned.status == "handled"
    assert archived.status == "handled"
    assert "No notes found" in list_visible.message
    assert restored.status == "handled"
    assert "Grandpa Project Notes" in recent.message


def test_delete_requires_confirmation_and_confirmed_delete_removes_file(tmp_path) -> None:
    store = NotesStore(tmp_path)
    automation = NotesAutomation(store=store)
    automation.handle("create a note called Delete Me")

    pending = automation.handle("delete note Delete Me")
    deleted = automation.handle("delete note Delete Me", confirmed=True)
    opened = automation.handle("open my note Delete Me")

    assert pending.status == "needs_confirmation"
    assert pending.requires_confirmation is True
    assert deleted.status == "handled"
    assert opened.status == "error"
    assert "Note not found" in opened.message


def test_storage_prevents_path_traversal_and_secret_capture(tmp_path) -> None:
    safety = NotesSafetyPolicy()
    store = NotesStore(tmp_path, safety=safety)

    with pytest.raises(NotesSafetyError):
        safety.ensure_inside_root(tmp_path, tmp_path.parent / "outside.md")

    result = NotesAutomation(store=store).handle("add this to my notes token: abcdefgh123456")

    assert result.status == "blocked"
    assert "secret" in result.message


def test_duplicate_titles_do_not_corrupt_existing_notes(tmp_path) -> None:
    store = NotesStore(tmp_path)

    first = store.create("Grandpa Ideas", "one")
    second = store.create("Grandpa Ideas", "two")

    assert first.slug == "grandpa-ideas"
    assert second.slug == "grandpa-ideas-2"
    assert len(tuple(tmp_path.glob("*.md"))) == 2


def test_parser_handles_requested_natural_commands() -> None:
    parser = NotesParser()

    assert parser.parse("show my notes") == NotesAction("list")
    assert parser.parse("list recent notes") == NotesAction("recent")
    assert parser.parse("find note about AI").action == "search"
    assert parser.parse("create a project note").category == "project"
    assert parser.parse("delete note Grandpa Ideas").action == "delete"


def test_notes_slash_command_routes_through_safe_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_handle(text: str):
        calls.append(text)
        return SimpleNamespace(message="Notes listed.")

    monkeypatch.setattr("grandpa.notes.handle_notes_command", fake_handle)

    assert _handle_notes_slash_command("/notes list") == "Notes listed."
    assert calls == ["show my notes"]


def test_notes_slash_command_is_registered_for_picker() -> None:
    command = get_command("/notes")

    assert command is not None
    assert command.category == "Memory & Productivity"
    assert "/notes search <query>" in command.subcommands


def test_voice_assistant_routes_notes_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "grandpa.notes.handle_notes_command",
        lambda _text: SimpleNamespace(
            should_fallback=False,
            message='Note created: "Quick Note".',
            status="handled",
            action=SimpleNamespace(query=""),
        ),
    )
    processor = VoiceCommandProcessor()

    response = processor._handle_local_pipeline("take a note browser automation idea")

    assert response is not None
    assert response.kind == "notes"
    assert "Note created" in response.text


def test_voice_operator_routes_notes_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    intent = parse_voice_operator_command("search notes for browser automation")
    assert intent.kind == "notes"

    monkeypatch.setattr(
        "grandpa.notes.handle_notes_command",
        lambda _text: SimpleNamespace(
            status="handled",
            message="Search results",
            requires_confirmation=False,
        ),
    )

    result = execute_voice_operator_intent(intent)

    assert result.status == "handled"
    assert result.action["action_type"] == "notes"


def test_doctor_reports_notes_storage_ready(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class FakeStore:
        def status(self):
            return "ready", f"Notes storage ready at {tmp_path}."

    monkeypatch.setattr("grandpa.notes.NotesStore", FakeStore)

    result = _check_notes_readiness()

    assert result.status == "ok"
    assert "Ready" in result.message


def test_handle_notes_command_accepts_custom_store(tmp_path) -> None:
    store = NotesStore(tmp_path)

    result = handle_notes_command("create a note called Custom Store", store=store)

    assert result.status == "handled"
    assert (tmp_path / "custom-store.md").exists()
