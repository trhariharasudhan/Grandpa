from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.memory_context import (
    MemoryStore,
    build_personal_memory_context,
    capture_natural_personal_fact,
    handle_memory_command,
)


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("favorite color", "blue"),
        ("favorite bike brand", "Yamaha"),
        ("favorite food", "dosa"),
        ("favorite movie", "Interstellar"),
    ],
)
def test_natural_fact_capture_and_cross_session_recall(
    tmp_path: Path,
    attribute: str,
    value: str,
) -> None:
    database = tmp_path / "personal_memory.db"
    assert capture_natural_personal_fact(
        f"My {attribute} is {value}.",
        store=MemoryStore(database),
    )

    persisted = MemoryStore(database).list_memories()
    assert len(persisted) == 1
    assert persisted[0]["key"] == attribute.replace(" ", "_")
    assert persisted[0]["value"] == value

    context = build_personal_memory_context(
        f"What is my {attribute}?",
        store=MemoryStore(database),
    )
    later = handle_memory_command(
        f"What is my {attribute}?",
        store=MemoryStore(database),
    )

    assert f"{attribute}: {value}" in context
    assert later.message == f"Your {attribute} is {value}."


def test_natural_capture_deduplicates_by_personal_attribute(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "personal_memory.db")
    assert capture_natural_personal_fact("My favorite color is blue", store=store)
    assert capture_natural_personal_fact("My favorite color is green", store=store)

    memories = store.list_memories()
    assert len(memories) == 1
    assert memories[0]["value"] == "green"


def test_natural_capture_rejects_temporary_and_sensitive_text(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "personal_memory.db")

    assert not capture_natural_personal_fact("Hello there", store=store)
    assert not capture_natural_personal_fact("Open Chrome", store=store)
    assert not capture_natural_personal_fact(
        "My password is swordfish",
        store=store,
    )
    assert store.list_memories() == []


def test_context_includes_only_relevant_memory(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "personal_memory.db")
    capture_natural_personal_fact("My favorite color is blue", store=store)
    capture_natural_personal_fact("My preferred editor is VS Code", store=store)

    context = build_personal_memory_context("What is my favorite color?", store=store)

    assert "favorite color: blue" in context
    assert "VS Code" not in context


def test_forget_removes_naturally_captured_memory(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "personal_memory.db")
    capture_natural_personal_fact("My favorite color is blue", store=store)

    forgotten = handle_memory_command("forget favorite color", store=store)
    recalled = handle_memory_command("What is my favorite color?", store=store)

    assert "forgot 1" in forgotten.message
    assert recalled.message == "I do not know your favorite color yet."
