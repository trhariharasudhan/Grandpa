"""The audit log of local-action decisions.

This module used to be a second approval store as well: pending actions with
their own 120-second expiry, approvable by whichever caller said "yes" first.
That half is gone. Every action waiting for consent now lives in pc_control's
store, behind ``grandpa.desktop.kernel.approvals``, bound to the origin that
staged it and expiring on pc_control's PENDING_TTL_SECONDS. What remains is the
record of what was decided.

A database written before this change still has a ``pending_actions`` table;
nothing reads it.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Literal

from grandpa.core.config import DEFAULT_CONFIG_DIR

PermissionDecision = Literal[
    "allowed", "requires_confirmation", "blocked", "unsupported"
]

DEFAULT_APPROVAL_DB = DEFAULT_CONFIG_DIR / "local_action_approvals.db"


class LocalActionApprovalStore:
    """Writes and reads the local-action audit log. Stages nothing."""

    def __init__(self, db_path: Path | str = DEFAULT_APPROVAL_DB) -> None:
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
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    action_id TEXT,
                    decision TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    kind TEXT,
                    target TEXT,
                    detail TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)"
            )

    def audit(
        self,
        *,
        action_id: str | None,
        decision: str,
        source_text: str,
        kind: str | None,
        target: str | None,
        detail: dict[str, Any] | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_log(
                    created_at, action_id, decision, source_text, kind, target, detail
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    action_id,
                    decision,
                    source_text,
                    kind,
                    target,
                    json.dumps(detail) if detail is not None else None,
                ),
            )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, action_id, decision, source_text, kind, target, detail
                FROM audit_log
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


__all__ = [
    "DEFAULT_APPROVAL_DB",
    "LocalActionApprovalStore",
    "PermissionDecision",
]
