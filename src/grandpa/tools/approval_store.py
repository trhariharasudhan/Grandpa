"""ApprovalStore — SQLite-backed store for pending action approvals.

One table, ``pending_actions``: proposals awaiting a user decision, and the
decision once made.

A second table, ``permission_memory``, and the API over it were retired by
AD-031. They were the store half of the proactive-agent feature that arrived in
``4652b6e8`` and whose consumer was deleted in ``c40b58ab``; the store outlived
it and was later reused for patch proposals. Nothing read or wrote the
remembered decisions in between. Existing databases keep the table as an
orphan -- AD-031 g deliberately authorises no ``DROP TABLE`` and no migration,
because nothing reads it.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_EXPIRED = "expired"
STATUS_EXECUTED = "executed"

# Tiers govern default ask behavior
TIER_TRIVIAL = "trivial"  # Execute immediately, no ask
TIER_LOW = "low"
TIER_MEDIUM = "medium"
TIER_HIGH = "high"


@dataclass
class PendingAction:
    """An action awaiting a user decision."""

    id: str
    action_type: str
    description: str
    payload: Dict[str, Any]
    permission_key: str
    tier: str
    status: str = STATUS_PENDING
    created_at: str = ""
    expires_at: str = ""
    notification_sent: bool = False
    decision_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "description": self.description,
            "payload": json.dumps(self.payload),
            "permission_key": self.permission_key,
            "tier": self.tier,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "notification_sent": int(self.notification_sent),
            "decision_at": self.decision_at,
        }

    @classmethod
    def from_row(cls, row: tuple) -> PendingAction:
        (
            id_,
            action_type,
            description,
            payload_json,
            permission_key,
            tier,
            status,
            created_at,
            expires_at,
            notification_sent,
            decision_at,
        ) = row
        return cls(
            id=id_,
            action_type=action_type,
            description=description,
            payload=json.loads(payload_json) if payload_json else {},
            permission_key=permission_key,
            tier=tier,
            status=status,
            created_at=created_at or "",
            expires_at=expires_at or "",
            notification_sent=bool(notification_sent),
            decision_at=decision_at,
        )


class ApprovalStore:
    """SQLite store for pending action approvals."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(Path.home() / ".grandpa" / "approvals.db")
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._conn.commit()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS pending_actions (
                id TEXT PRIMARY KEY,
                action_type TEXT NOT NULL,
                description TEXT NOT NULL,
                payload TEXT NOT NULL,
                permission_key TEXT NOT NULL,
                tier TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                notification_sent INTEGER NOT NULL DEFAULT 0,
                decision_at TEXT
            );
        """)

    # -- Pending actions -------------------------------------------------------

    def queue_action(
        self,
        action_type: str,
        description: str,
        payload: Dict[str, Any],
        permission_key: str,
        tier: str,
        ttl_hours: int = 24,
    ) -> PendingAction:
        """Create and persist a new pending action."""
        now = datetime.now(timezone.utc)
        action = PendingAction(
            id=uuid.uuid4().hex[:12],
            action_type=action_type,
            description=description,
            payload=payload,
            permission_key=permission_key,
            tier=tier,
            status=STATUS_PENDING,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=ttl_hours)).isoformat(),
        )
        self._conn.execute(
            """
            INSERT OR REPLACE INTO pending_actions
                (id, action_type, description, payload, permission_key,
                 tier, status, created_at, expires_at, notification_sent, decision_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action.id,
                action.action_type,
                action.description,
                json.dumps(action.payload),
                action.permission_key,
                action.tier,
                action.status,
                action.created_at,
                action.expires_at,
                int(action.notification_sent),
                action.decision_at,
            ),
        )
        self._conn.commit()
        return action

    def get_action(self, action_id: str) -> Optional[PendingAction]:
        row = self._conn.execute(
            "SELECT id, action_type, description, payload, permission_key, "
            "tier, status, created_at, expires_at, notification_sent, decision_at "
            "FROM pending_actions WHERE id = ?",
            (action_id,),
        ).fetchone()
        return PendingAction.from_row(row) if row else None

    def list_pending(self) -> List[PendingAction]:
        """Return all non-expired pending actions."""
        now = datetime.now(timezone.utc).isoformat()
        rows = self._conn.execute(
            "SELECT id, action_type, description, payload, permission_key, "
            "tier, status, created_at, expires_at, notification_sent, decision_at "
            "FROM pending_actions WHERE status = ? AND expires_at > ? "
            "ORDER BY created_at",
            (STATUS_PENDING, now),
        ).fetchall()
        return [PendingAction.from_row(r) for r in rows]

    def list_approved(self) -> List[PendingAction]:
        """Return approved-but-not-yet-executed actions."""
        rows = self._conn.execute(
            "SELECT id, action_type, description, payload, permission_key, "
            "tier, status, created_at, expires_at, notification_sent, decision_at "
            "FROM pending_actions WHERE status = ? ORDER BY created_at",
            (STATUS_APPROVED,),
        ).fetchall()
        return [PendingAction.from_row(r) for r in rows]

    def update_status(
        self,
        action_id: str,
        status: str,
        *,
        notification_sent: Optional[bool] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if notification_sent is not None:
            self._conn.execute(
                "UPDATE pending_actions SET status = ?, decision_at = ?, "
                "notification_sent = ? WHERE id = ?",
                (status, now, int(notification_sent), action_id),
            )
        else:
            self._conn.execute(
                "UPDATE pending_actions SET status = ?, decision_at = ? WHERE id = ?",
                (status, now, action_id),
            )
        self._conn.commit()

    def expire_stale(self) -> int:
        """Mark past-TTL pending actions as expired. Returns count."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "UPDATE pending_actions SET status = ? "
            "WHERE status = ? AND expires_at <= ?",
            (STATUS_EXPIRED, STATUS_PENDING, now),
        )
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()


__all__ = [
    "ApprovalStore",
    "PendingAction",
    "STATUS_PENDING",
    "STATUS_APPROVED",
    "STATUS_DENIED",
    "STATUS_EXPIRED",
    "STATUS_EXECUTED",
    "TIER_TRIVIAL",
    "TIER_LOW",
    "TIER_MEDIUM",
    "TIER_HIGH",
]
