"""Shared SQLite corruption recovery helpers for Grandpa memory stores."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

MEMORY_RECOVERY_MESSAGE = "Memory database was invalid and was backed up. A healthy empty database was created."
_MEMORY_RECOVERY_WARNINGS: list[str] = []


class MemoryRecoveryError(RuntimeError):
    """Raised when a corrupt memory database cannot be moved safely."""


def consume_memory_recovery_warnings() -> list[str]:
    """Return and clear pending user-facing memory recovery notices."""

    warnings = list(_MEMORY_RECOVERY_WARNINGS)
    _MEMORY_RECOVERY_WARNINGS.clear()
    return warnings


def validate_sqlite_connection(connection: sqlite3.Connection) -> None:
    """Raise ``DatabaseError`` unless SQLite reports a healthy database."""

    row = connection.execute("PRAGMA quick_check").fetchone()
    if not row or str(row[0]).casefold() != "ok":
        detail = row[0] if row else "no integrity result"
        raise sqlite3.DatabaseError(f"SQLite integrity check failed: {detail}")


def recover_sqlite_database(path: Path, *, retries: int = 3) -> list[Path]:
    """Move a corrupt database and its WAL/SHM files to timestamped backups."""

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups: list[Path] = []
    for source in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if not source.exists():
            continue
        destination = _unique_backup_path(source, timestamp)
        last_error: OSError | None = None
        for attempt in range(retries):
            try:
                os.replace(source, destination)
                backups.append(destination)
                last_error = None
                break
            except OSError as exc:
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(0.05 * (attempt + 1))
        if last_error is not None:
            raise MemoryRecoveryError(
                f"Grandpa found a damaged memory database but could not back up "
                f"{source}. Close other Grandpa processes and try again."
            ) from last_error
    _MEMORY_RECOVERY_WARNINGS.append(MEMORY_RECOVERY_MESSAGE)
    return backups


def _unique_backup_path(source: Path, timestamp: str) -> Path:
    candidate = source.with_name(f"{source.name}.corrupt-{timestamp}")
    suffix = 1
    while candidate.exists():
        candidate = source.with_name(f"{source.name}.corrupt-{timestamp}-{suffix}")
        suffix += 1
    return candidate


__all__ = [
    "MEMORY_RECOVERY_MESSAGE",
    "MemoryRecoveryError",
    "consume_memory_recovery_warnings",
    "recover_sqlite_database",
    "validate_sqlite_connection",
]
