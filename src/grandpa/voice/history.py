"""Persistent voice command history."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_VOICE_HISTORY_DB = DEFAULT_CONFIG_DIR / "voice_history.db"
VOICE_HISTORY_LIMIT = 100


class VoiceCommandHistoryStore:
    def __init__(self, db_path: Path | str = DEFAULT_VOICE_HISTORY_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_command_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    transcript TEXT NOT NULL,
                    assistant_response TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    action_status TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_voice_history_timestamp "
                "ON voice_command_history(timestamp DESC)"
            )

    def add(
        self,
        *,
        transcript: str,
        assistant_response: str,
        action_type: str,
        action_status: str,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        created_at = timestamp or datetime.now(UTC)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO voice_command_history(
                    timestamp, transcript, assistant_response, action_type, action_status
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    created_at.isoformat(),
                    transcript,
                    assistant_response,
                    action_type,
                    action_status,
                ),
            )
            row_id = cursor.lastrowid
            self._trim(conn)
        return {
            "id": row_id,
            "timestamp": created_at.isoformat(),
            "transcript": transcript,
            "assistant_response": assistant_response,
            "action_type": action_type,
            "action_status": action_status,
        }

    def list(self, limit: int = VOICE_HISTORY_LIMIT) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, VOICE_HISTORY_LIMIT))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, transcript, assistant_response, action_type, action_status
                FROM voice_command_history
                ORDER BY id DESC
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def clear(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM voice_command_history")
        return cursor.rowcount

    def _trim(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            DELETE FROM voice_command_history
            WHERE id NOT IN (
                SELECT id FROM voice_command_history
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (VOICE_HISTORY_LIMIT,),
        )


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


__all__ = [
    "DEFAULT_VOICE_HISTORY_DB",
    "VOICE_HISTORY_LIMIT",
    "VoiceCommandHistoryStore",
]
