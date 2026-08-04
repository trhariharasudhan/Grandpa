from __future__ import annotations

from grandpa.memory_context import (
    MemoryStore,
    handle_memory_command,
    search_personal_memory,
)


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


def test_remember_that_learning_ai_automation(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")

    result = handle_memory_command(
        "remember that I am learning AI automation", store=store
    )

    assert result.status == "handled"
    assert "I am learning AI automation" in result.message
    assert store.list_memories()[0]["value"] == "I am learning AI automation"


def test_what_do_you_remember_about_me(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    handle_memory_command("remember my name is Hari", store=store)

    result = handle_memory_command("what do you remember about me", store=store)

    assert result.status == "handled"
    assert "Hari" in result.message


def test_forget_my_name(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    handle_memory_command("remember my name is Hari", store=store)

    result = handle_memory_command("forget my name", store=store)

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


def test_semantic_recall_project_without_exact_words(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    handle_memory_command("remember my project is Grandpa", store=store)

    result = handle_memory_command("what AI assistant am I building?", store=store)

    assert result.status == "handled"
    assert "Grandpa" in result.message
    assert "confidence" in result.message


def test_mixed_tamil_english_project_recall(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    handle_memory_command("remember my project is Grandpa", store=store)

    result = handle_memory_command("Grandpa என்ன project?", store=store)

    assert result.status == "handled"
    assert result.message == "Your project is Grandpa."


def test_semantic_recall_editor_preference(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    handle_memory_command("remember I use VS Code", store=store)

    result = handle_memory_command("what editor do I prefer?", store=store)

    assert result.status == "handled"
    assert "VS Code" in result.message


def test_semantic_search_category_filter(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    handle_memory_command("remember my project is Grandpa", store=store)
    handle_memory_command("remember I use VS Code", store=store)

    results = store.search_memories("what editor do I prefer?", category="apps_tools")

    assert results
    assert results[0]["category"] == "apps_tools"
    assert results[0]["score"] > 0


def test_semantic_low_confidence_does_not_invent_memory(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    handle_memory_command("remember my project is Grandpa", store=store)

    result = handle_memory_command(
        "what reminder do I have for my dentist?", store=store
    )

    assert result.status == "handled"
    assert "not confident" in result.message or "do not have" in result.message


def test_embedding_fallback_creates_local_metadata(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    handle_memory_command("remember my project is Grandpa", store=store)

    status = store.semantic_status()

    assert status["backend"] == "local-sqlite"
    assert status["embeddings"] == 1
    assert status["local_only"] is True


def test_memory_search_response_reports_uncertain(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.db"
    store = MemoryStore(db_path)
    handle_memory_command("remember my project is Grandpa", store=store)
    monkeypatch.setattr("grandpa.memory_context.DEFAULT_MEMORY_DB", db_path)

    response = search_personal_memory("dentist reminder", category="routines")

    assert response["category"] == "routines"
    assert response["uncertain"] is True


def test_sensitive_semantic_memory_is_still_blocked(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")

    result = handle_memory_command("remember my API key is abc123", store=store)

    assert result.status == "blocked"
    assert store.semantic_status()["embeddings"] == 0
