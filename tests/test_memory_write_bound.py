"""The write path stores a value, or it stores nothing.

Reported: typing "my name is hari what is your name ?" made "what is my name"
answer "Your name is hari what is your name ?." The read path had already been
fixed to fall through on a miss -- but this was not a miss. The wrong value was
genuinely in the store, written by the capture on the way in.

The capture's value group is `(.+)$`, so it took the rest of the line. These
pin the bound that replaced it, and the key agreement that made the relations
reachable at all.
"""

from __future__ import annotations

import pytest

from grandpa.memory_context import (
    _RELATIONS,
    MemoryStore,
    _canonical_key,
    capture_natural_personal_fact,
    execute_memory_action,
)

# The reported string, then five more compound sentences. Each is a different
# way for a second clause to arrive: a question word, a second fact about me,
# a comma splice, an auxiliary, an imperative, a trailing confirmation.
REFUSED = [
    "my name is hari what is your name ?",
    "my name is Hari and my sister is Swaathi",
    "my name is Hari, what do you do",
    "my name is Hari can you remember it",
    "my name is Hari so tell me where I work",
    "my name is Hari is that ok",
]

# The bound must not buy its accuracy by refusing honest values. A full name is
# three words; "black and white" has a conjunction but no second clause.
ACCEPTED = [
    ("my name is Hari", "name", "Hari"),
    ("my name is Hari Hara Sudhan", "name", "Hari Hara Sudhan"),
    ("my favorite colour is black and white", "favorite_colour", "black and white"),
    ("my location is Chennai Tamil Nadu", "location", "Chennai Tamil Nadu"),
    ("my timezone is Asia/Kolkata", "timezone", "Asia/Kolkata"),
]


@pytest.mark.parametrize("text", REFUSED)
def test_a_compound_sentence_stores_nothing(text: str, tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")

    assert capture_natural_personal_fact(text, store=store) is False
    assert store.list_memories(limit=50) == [], (
        "a value that carries a second clause was stored anyway"
    )


@pytest.mark.parametrize(("text", "key", "value"), ACCEPTED)
def test_an_honest_value_still_stores(
    text: str, key: str, value: str, tmp_path
) -> None:
    store = MemoryStore(tmp_path / "memory.db")

    assert capture_natural_personal_fact(text, store=store) is True
    rows = {item["key"]: item["value"] for item in store.list_memories(limit=50)}
    assert rows == {key: value}


@pytest.mark.real_actions(reason="reaches the real execute_memory_action")
def test_the_reported_string_now_falls_through_to_the_model(tmp_path) -> None:
    """Nothing stored, so the recall is a miss, so the model answers.

    The two halves have to hold together: refusing the write is only right
    because the read falls through rather than inventing a reply.
    """
    store = MemoryStore(tmp_path / "memory.db")
    capture_natural_personal_fact("my name is hari what is your name ?", store=store)

    result = execute_memory_action("attribute", store=store, subject="name")

    assert store.list_memories(limit=50) == []
    assert result.should_fallback is True
    assert "hari what is your name" not in result.message


def test_the_write_key_and_the_read_key_agree(tmp_path) -> None:
    """Measured, not assumed, and this is the measurement that found it.

    A restart proof showed "remember that my sister is Swaathi Sri" storing
    ``sister`` while "what is my sister name" looked up ``sister_name``. The row
    survived the restart; the two paths just disagreed about the key.
    """
    assert _canonical_key("sister name") == "sister"
    assert _canonical_key("sister") == "sister"
    # "name" is the fact, not a qualifier, so it is the one key that survives.
    assert _canonical_key("name") == "name"

    store = MemoryStore(tmp_path / "memory.db")
    capture_natural_personal_fact("my sister is Swaathi Sri", store=store)

    asked_with_name = execute_memory_action(
        "attribute", store=store, subject="sister name"
    )
    asked_without = execute_memory_action("attribute", store=store, subject="sister")

    assert asked_with_name.should_fallback is False
    assert "Swaathi Sri" in asked_with_name.message
    assert asked_without.should_fallback is False


@pytest.mark.parametrize("relation", _RELATIONS)
def test_each_relation_is_captured_in_the_first_person(
    relation: str, tmp_path
) -> None:
    """Both phrasings, one key.

    Nine relations were added to the allowlist. Third person -- "she name is
    X", with the subject inferred from the previous turn -- was deliberately
    left out: storing a wrong fact is worse than storing none.
    """
    for phrasing in (f"my {relation} is Sundar", f"my {relation} name is Sundar"):
        store = MemoryStore(tmp_path / f"{relation}-{len(phrasing)}.db")
        assert capture_natural_personal_fact(phrasing, store=store) is True
        keys = [item["key"] for item in store.list_memories(limit=50)]
        assert keys == [relation], phrasing


def test_third_person_is_not_captured(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")

    for text in ("she name is Swaathi", "her name is Swaathi", "his name is Arun"):
        assert capture_natural_personal_fact(text, store=store) is False
    assert store.list_memories(limit=50) == []


def test_a_bad_value_can_be_removed_from_chat(tmp_path) -> None:
    """`/memory forget` already does this -- pinned so it keeps doing it.

    Matching is on key, key-with-spaces, value, or row id, so a value that got
    in before the bound existed can be named directly.
    """
    store = MemoryStore(tmp_path / "memory.db")
    store.remember("people", "name", "hari what is your name ?", source="natural_chat")

    assert store.forget("name") == 1
    assert store.list_memories(limit=50) == []

    store.remember("people", "name", "hari what is your name ?", source="natural_chat")
    assert store.forget("hari what is your name") == 1, "forget by value"
