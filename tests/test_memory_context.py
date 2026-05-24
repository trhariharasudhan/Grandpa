from __future__ import annotations

from grandpa.memory_context import MemoryStore, handle_memory_command


def test_remember_and_recall_project(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")

    remembered = handle_memory_command("remember my project is Grandpa", store=store)
    recalled = handle_memory_command("what is my project?", store=store)

    assert remembered.status == "handled"
    assert "project is Grandpa" in remembered.message
    assert recalled.message == "Your project is Grandpa."


def test_sensitive_memory_is_blocked(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")

    result = handle_memory_command("remember my password is swordfish", store=store)

    assert result.status == "blocked"
    assert store.list_memories() == []


def test_forget_matching_memory(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    handle_memory_command("remember I use VS Code", store=store)

    result = handle_memory_command("forget VS Code", store=store)

    assert result.status == "handled"
    assert "forgot 1" in result.message
    assert store.list_memories() == []


def test_activity_query_for_opened_apps_today(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.record_activity("app", "open", "notepad.exe", "open notepad", "handled")

    result = handle_memory_command("what apps did I open today?", store=store)

    assert result.status == "handled"
    assert "notepad" in result.message


def test_unmatched_memory_command_falls_back(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")

    result = handle_memory_command("What is Python?", store=store)

    assert result.should_fallback is True
