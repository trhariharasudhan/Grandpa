"""Approval storage and audit log for local actions."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from grandpa.core.config import DEFAULT_CONFIG_DIR

PermissionDecision = Literal["allowed", "requires_confirmation", "blocked", "unsupported"]

DEFAULT_APPROVAL_DB = DEFAULT_CONFIG_DIR / "local_action_approvals.db"
PENDING_TTL_SECONDS = 120


class LocalActionApprovalStore:
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
                CREATE TABLE IF NOT EXISTS pending_actions (
                    id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    source_text TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    target TEXT NOT NULL,
                    message TEXT NOT NULL,
                    tts_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )
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
                "CREATE INDEX IF NOT EXISTS idx_pending_status "
                "ON pending_actions(status, expires_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_created "
                "ON audit_log(created_at)"
            )

    def create_pending(
        self,
        *,
        source_text: str,
        kind: str,
        target: str,
        message: str,
        tts_text: str,
        ttl_seconds: int = PENDING_TTL_SECONDS,
    ) -> dict[str, Any]:
        self.expire_old()
        now = time.time()
        action_id = uuid.uuid4().hex
        expires_at = now + ttl_seconds
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_actions(
                    id, created_at, expires_at, source_text, kind, target,
                    message, tts_text, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (action_id, now, expires_at, source_text, kind, target, message, tts_text),
            )
        self.audit(
            action_id=action_id,
            decision="requested",
            source_text=source_text,
            kind=kind,
            target=target,
            detail={"expires_at": expires_at},
        )
        return self.get_pending(action_id) or {}

    def get_pending(self, action_id: str) -> dict[str, Any] | None:
        self.expire_old()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, expires_at, source_text, kind, target,
                       message, tts_text, status
                FROM pending_actions
                WHERE id = ?
                """,
                (action_id,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def latest_pending(self) -> dict[str, Any] | None:
        self.expire_old()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, expires_at, source_text, kind, target,
                       message, tts_text, status
                FROM pending_actions
                WHERE status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list_pending(self) -> list[dict[str, Any]]:
        self.expire_old()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, expires_at, source_text, kind, target,
                       message, tts_text, status
                FROM pending_actions
                WHERE status = 'pending'
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def mark(self, action_id: str, decision: str) -> dict[str, Any] | None:
        item = self.get_pending(action_id)
        if not item:
            self.audit(
                action_id=action_id,
                decision="missing",
                source_text="",
                kind=None,
                target=None,
                detail={"requested_decision": decision},
            )
            return None
        if item["status"] != "pending":
            return item
        with self._connect() as conn:
            conn.execute(
                "UPDATE pending_actions SET status = ? WHERE id = ?",
                (decision, action_id),
            )
        item["status"] = decision
        self.audit(
            action_id=action_id,
            decision=decision,
            source_text=item["source_text"],
            kind=item["kind"],
            target=item["target"],
            detail=None,
        )
        return item

    def expire_old(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, source_text, kind, target
                FROM pending_actions
                WHERE status = 'pending' AND expires_at <= ?
                """,
                (now,),
            ).fetchall()
            conn.execute(
                """
                UPDATE pending_actions
                SET status = 'expired'
                WHERE status = 'pending' AND expires_at <= ?
                """,
                (now,),
            )
        for row in rows:
            self.audit(
                action_id=row["id"],
                decision="expired",
                source_text=row["source_text"],
                kind=row["kind"],
                target=row["target"],
                detail=None,
            )
        return len(rows)

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
    "PENDING_TTL_SECONDS",
    "PermissionDecision",
]
