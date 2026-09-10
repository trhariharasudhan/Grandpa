"""Approval storage and audit log for local actions."""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from grandpa.core.config import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

PermissionDecision = Literal[
    "allowed", "requires_confirmation", "blocked", "unsupported"
]

DEFAULT_APPROVAL_DB = DEFAULT_CONFIG_DIR / "local_action_approvals.db"
PENDING_TTL_SECONDS = 120

#: How many wrong approval codes a single pending action tolerates.
#:
#: Eight hex characters is a 2**32 space, which a 120-second TTL already makes a
#: poor target -- but "poor" is not a security argument. Five is generous for a
#: human retyping a code off a console and leaves a 5/2**32 chance of a lucky
#: guess. The counter is persisted beside the code it protects: a cap that reset
#: when the process restarted would not be a cap.
MAX_APPROVAL_ATTEMPTS = 5


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
                    status TEXT NOT NULL DEFAULT 'pending',
                    approval_token TEXT NOT NULL DEFAULT '',
                    failed_attempts INTEGER NOT NULL DEFAULT 0
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
                "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)"
            )
            # Migrate databases created before approvals carried an out-of-band
            # code. Rows written then hold an empty token, and an empty token is
            # refused rather than filled in -- see ``verify_approval_token``.
            # The same reading ``pc_control`` gives an empty ``action_digest``:
            # a row staged before the binding existed is not approvable through
            # the bound path, because nothing about it was ever bound.
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(pending_actions)")
            }
            if "approval_token" not in columns:
                conn.execute(
                    "ALTER TABLE pending_actions "
                    "ADD COLUMN approval_token TEXT NOT NULL DEFAULT ''"
                )
            # Migrate databases created before approval attempts were counted.
            # Rows written then start at zero, which is the same budget a new
            # row gets -- they are unbound anyway, so they are refused before
            # any credential is weighed.
            if "failed_attempts" not in columns:
                conn.execute(
                    "ALTER TABLE pending_actions "
                    "ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0"
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
        """Stage an action awaiting confirmation, minting its approval code.

        The code is generated here and nowhere else, and there is deliberately
        no parameter to supply one: a credential the caller chooses is not a
        credential. 4.13B briefly accepted one so tests could build a bound row;
        that channel is the same shape as the client-supplied ``source`` and
        ``confirmed`` fields closed earlier in M4, so it is gone.

        The code is **not** returned. It reaches the operator through the log
        below and through no other channel -- the returned row, every store
        projection and ``_pending_metadata`` all omit it, because the caller
        staging an action over HTTP must not be able to read the code that
        approves it.
        """
        self.expire_old()
        now = time.time()
        action_id = uuid.uuid4().hex
        # Same primitive and shape as ``pc_control._create_pending``: eight
        # uppercase hex characters, short enough to read off a console and
        # retype, random enough that guessing inside the TTL is not a strategy.
        # (Attempt limiting belongs with the endpoint that consumes it -- 4.13D
        # -- where there are attempts to count.)
        approval_token = secrets.token_hex(4).upper()
        expires_at = now + ttl_seconds
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_actions(
                    id, created_at, expires_at, source_text, kind, target,
                    message, tts_text, status, approval_token
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    action_id,
                    now,
                    expires_at,
                    source_text,
                    kind,
                    target,
                    message,
                    tts_text,
                    approval_token,
                ),
            )
        self.audit(
            action_id=action_id,
            decision="requested",
            source_text=source_text,
            kind=kind,
            target=target,
            detail={"expires_at": expires_at},
        )
        # Out-of-band delivery, following ``pc_control._create_pending``. The
        # console and the log are the one channel the HTTP caller that staged
        # this action cannot read, which is the only thing that makes the code
        # worth having. WARNING because an operator has to actually see it.
        logger.warning(
            "Local action %s requires confirmation: %s (%s). Approval code: %s "
            "(expires in %ds)",
            action_id,
            source_text,
            kind,
            approval_token,
            ttl_seconds,
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

    def approval_token(self, action_id: str) -> str | None:
        """The out-of-band code bound to *action_id*, or ``None`` if no such row.

        Deliberately the only way to read the column: every other projection
        enumerates its columns and omits it, so a caller has to ask for the
        credential by name rather than receive it with a row.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT approval_token FROM pending_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
        return str(row["approval_token"]) if row else None

    def failed_attempts(self, action_id: str) -> int | None:
        """How many wrong codes *action_id* has absorbed, or ``None`` if absent.

        Read through its own accessor for the same reason as the code itself:
        every row projection omits it, so nothing hands it to an HTTP caller by
        accident.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT failed_attempts FROM pending_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
        return int(row["failed_attempts"]) if row else None

    def attempts_exhausted(self, action_id: str) -> bool:
        """Whether *action_id* has spent its guessing budget."""
        attempts = self.failed_attempts(action_id)
        return attempts is not None and attempts >= MAX_APPROVAL_ATTEMPTS

    def _record_failed_attempt(self, action_id: str) -> None:
        """Consume one attempt, atomically and without overshooting the cap.

        The increment is a single conditional statement rather than a
        read-modify-write, so concurrent guesses cannot race the counter past
        its own ceiling.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE pending_actions SET failed_attempts = failed_attempts + 1 "
                "WHERE id = ? AND failed_attempts < ?",
                (action_id, MAX_APPROVAL_ATTEMPTS),
            )

    def authorize_approval(self, action_id: str, token: str) -> bool:
        """Whether *token* authorises approving *action_id*, spending an attempt.

        Order matters. A row that is missing, expired or already decided is
        refused on its status *before* any credential is weighed, so guessing at
        one action cannot drain another's budget and a stale row cannot lock a
        live one. A legacy row -- no code was ever bound to it -- is refused
        outright for the same reason: there is nothing to guess, so nothing is
        counted.

        Only a wrong or missing code against a live, bound, un-exhausted row
        consumes an attempt. Success consumes none and resets none: a row that
        reached the cap stays refused even when the right code arrives.
        """
        row = self.get_pending(action_id)
        if row is None or row["status"] != "pending":
            return False
        if not self.is_token_bound(action_id):
            return False
        if self.attempts_exhausted(action_id):
            return False
        if self.verify_approval_token(action_id, token):
            return True
        self._record_failed_attempt(action_id)
        return False

    def claim_pending(self, action_id: str, decision: str) -> bool:
        """Transition *action_id* out of ``pending``, exactly once.

        Returns True only for the caller that won. The conditional
        ``WHERE ... AND status = 'pending'`` plus a ``rowcount`` check is the
        pattern ``pc_control._mark_pending_decision`` already uses; nothing new
        is locked here.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE pending_actions SET status = ? "
                "WHERE id = ? AND status = 'pending'",
                (decision, action_id),
            )
            return cursor.rowcount == 1

    def is_token_bound(self, action_id: str) -> bool:
        """Whether *action_id* carries a code at all.

        False for a row staged before the migration, and for one staged without
        a code. Distinguishing the two cases is what lets an approval path
        refuse an unbound row explicitly instead of comparing against ``""``.
        """
        return bool(self.approval_token(action_id))

    def verify_approval_token(self, action_id: str, token: str) -> bool:
        """Whether *token* is the code bound to *action_id*.

        An unbound row is refused whatever is presented, including an empty
        string: absent binding means "not approvable this way", never "no code
        required". The comparison is constant-time because the code is short
        enough for timing to matter.
        """
        expected = self.approval_token(action_id)
        if not expected or not token:
            return False
        return secrets.compare_digest(str(token), expected)

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
        # Claim atomically rather than trusting the read above: two concurrent
        # approvals could both have seen "pending". The loser gets the row as it
        # actually stands, and audits nothing.
        if not self.claim_pending(action_id, decision):
            return self.get_pending(action_id)
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
