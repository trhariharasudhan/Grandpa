from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from grandpa.memory_context import MemoryStore
from grandpa.memory_recovery import (
    MEMORY_RECOVERY_MESSAGE,
    MemoryRecoveryError,
    consume_memory_recovery_warnings,
)


@pytest.fixture(autouse=True)
def clear_recovery_warnings():
    consume_memory_recovery_warnings()
    yield
    consume_memory_recovery_warnings()


@pytest.mark.parametrize(
    "content", (b"not a sqlite database", b"SQLite format 3\x00short")
)
def test_corrupt_database_is_backed_up_and_recreated(
    tmp_path: Path,
    content: bytes,
) -> None:
    database = tmp_path / "personal_memory.db"
    database.write_bytes(content)

    with MemoryStore(database) as store:
        store.remember("preferences", "favorite_color", "blue")
        assert store.search_memories("blue")[0]["value"] == "blue"

    backups = list(tmp_path.glob("personal_memory.db.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == content
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert consume_memory_recovery_warnings() == [MEMORY_RECOVERY_MESSAGE]


def test_wal_and_shm_are_backed_up_with_corrupt_database(tmp_path: Path) -> None:
    database = tmp_path / "personal_memory.db"
    database.write_bytes(b"broken")
    Path(f"{database}-wal").write_bytes(b"wal")
    Path(f"{database}-shm").write_bytes(b"shm")

    MemoryStore(database).close()

    assert len(list(tmp_path.glob("personal_memory.db.corrupt-*"))) == 1
    assert len(list(tmp_path.glob("personal_memory.db-wal.corrupt-*"))) == 1
    assert len(list(tmp_path.glob("personal_memory.db-shm.corrupt-*"))) == 1


def test_locked_recovery_failure_is_friendly_and_preserves_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "personal_memory.db"
    database.write_bytes(b"broken")

    with patch(
        "grandpa.memory_recovery.os.replace", side_effect=PermissionError("locked")
    ):
        with pytest.raises(MemoryRecoveryError, match="Close other Grandpa processes"):
            MemoryStore(database)

    assert database.read_bytes() == b"broken"


def test_store_can_restart_after_recovery(tmp_path: Path) -> None:
    database = tmp_path / "personal_memory.db"
    database.write_bytes(b"broken")

    MemoryStore(database).close()
    with MemoryStore(database) as restarted:
        assert restarted.list_memories() == []
