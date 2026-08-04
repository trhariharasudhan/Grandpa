"""Unit tests for MemoryStore SQLite persistence layer in Grandpa Memory System V1."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from grandpa.memory.models import MemoryItem
from grandpa.memory.store import MemoryStore


@pytest.fixture
def temp_store():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_memory.db"
        store = MemoryStore(db_path=db_path)
        yield store


def test_memory_store_init_and_schema(temp_store: MemoryStore) -> None:
    assert temp_store.db_path.exists()
    with temp_store._connect() as conn:
        ver = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()[
            "version"
        ]
        assert ver == 1


def test_memory_store_crud(temp_store: MemoryStore) -> None:
    item = MemoryItem(
        key="user_name", content="Hari Hara Sudhan", category="preference"
    )
    inserted = temp_store.insert(item)
    assert inserted.key == "user_name"
    assert inserted.content == "Hari Hara Sudhan"

    # Get by key & id
    fetched_key = temp_store.get_by_key("user_name")
    assert fetched_key is not None
    assert fetched_key.content == "Hari Hara Sudhan"
    assert fetched_key.access_count == 1

    fetched_id = temp_store.get_by_id(inserted.id)
    assert fetched_id is not None
    assert fetched_id.key == "user_name"

    # Update
    updated = temp_store.update("user_name", content="Hari Hara Sudhan (AGY Lead)")
    assert updated is not None
    assert updated.content == "Hari Hara Sudhan (AGY Lead)"

    # Delete (soft)
    deleted = temp_store.delete("user_name", soft=True)
    assert deleted is True
    assert temp_store.get_by_key("user_name") is None
    assert temp_store.get_by_key("user_name", include_deleted=True) is not None


def test_persistence_across_process_restart(temp_store: MemoryStore) -> None:
    db_path = temp_store.db_path
    item = MemoryItem(
        key="persistent_key", content="Durable memory content", category="knowledge"
    )
    temp_store.insert(item)

    # Simulate process restart by creating new MemoryStore instance with same DB path
    new_store_instance = MemoryStore(db_path=db_path)
    fetched = new_store_instance.get_by_key("persistent_key")
    assert fetched is not None
    assert fetched.content == "Durable memory content"


def test_category_filtering_and_list(temp_store: MemoryStore) -> None:
    temp_store.insert(MemoryItem(key="pref1", content="Val1", category="preference"))
    temp_store.insert(
        MemoryItem(
            key="proj1", content="Val2", category="project", project_name="Grandpa"
        )
    )
    temp_store.insert(MemoryItem(key="know1", content="Val3", category="knowledge"))

    prefs = temp_store.list_all(category="preference")
    assert len(prefs) == 1
    assert prefs[0].key == "pref1"

    projs = temp_store.list_all(category="project", project_name="Grandpa")
    assert len(projs) == 1
    assert projs[0].key == "proj1"

    all_items = temp_store.list_all()
    assert len(all_items) == 3


def test_sensitive_content_rejection(temp_store: MemoryStore) -> None:
    sensitive_item = MemoryItem(
        key="my_secret_token",
        content="Bearer eyJhbGciOiJIUzI1NiI...",
        category="knowledge",
    )
    with pytest.raises(ValueError, match="sensitive"):
        temp_store.insert(sensitive_item)

    # Rejection during update
    valid_item = temp_store.insert(
        MemoryItem(key="safe_key", content="Safe text", category="knowledge")
    )
    with pytest.raises(ValueError, match="sensitive"):
        temp_store.update(valid_item.id, content="my_password_is_123")


def test_clear_functionality(temp_store: MemoryStore) -> None:
    temp_store.insert(MemoryItem(key="k1", content="c1", category="knowledge"))
    temp_store.insert(MemoryItem(key="p1", content="c2", category="preference"))

    cleared_pref = temp_store.clear(category="preference")
    assert cleared_pref == 1
    assert temp_store.get_by_key("p1") is None
    assert temp_store.get_by_key("k1") is not None

    cleared_all = temp_store.clear()
    assert cleared_all == 1
    assert temp_store.get_by_key("k1") is None
