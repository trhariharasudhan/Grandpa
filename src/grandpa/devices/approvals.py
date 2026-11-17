"""Remote actions that wait for a yes at the PC (D4).

Before D4 an action the phone asked for that needs confirmation was simply
refused. Now it is **kept** as a pending request instead, and someone at the
PC decides:

* ``grandpa devices pending``        -- what is waiting, from which phone.
* ``grandpa devices approve <id>``   -- runs it through the executor with the
  same interactive "Run it? [y/N]" prompt ``grandpa chat`` uses. The yes is
  given at the PC, at the moment it runs, never by the phone.
* ``grandpa devices deny <id>``      -- drops it.

What keeps it safe:

* The phone cannot approve anything. There is no route for it, and the device
  token's allow-list only gains a read-only ``GET /v1/devices/pending``.
* The exact action and arguments the model chose are stored and shown, and the
  same ones run: nothing is re-planned between the request and the yes.
* A request expires after ``PENDING_TTL_SECONDS``; an expired, denied or
  already-run request cannot be approved again.
* A request from a phone that was revoked since cannot be approved.
* At most ``MAX_PENDING_PER_DEVICE`` requests wait per phone; older ones are
  expired to make room.
* Every step is in the device log (``grandpa devices log``):
  ``action_queued``, ``action_approved``, ``action_denied``,
  ``action_expired``, ``action_done``. The executor also writes its own
  audit record, as for any action.
* The phone gets the outcome as a notification (D3 outbox).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Mapping

PENDING_TTL_SECONDS = 10 * 60
MAX_PENDING_PER_DEVICE = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT NOT NULL,
    action      TEXT NOT NULL,
    parameters  TEXT NOT NULL,
    command     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    decided_at  REAL,
    outcome     TEXT
);
"""

#: Every status a request can end in. Only ``pending`` can be approved.
PENDING, APPROVED, DENIED, EXPIRED, DONE, FAILED = (
    "pending",
    "approved",
    "denied",
    "expired",
    "done",
    "failed",
)


class ApprovalError(Exception):
    """A request cannot be approved or denied. The message is safe to print."""


@dataclass(frozen=True, slots=True)
class PendingAction:
    id: int
    device_id: str
    action: str
    parameters: dict[str, Any]
    command: str
    created_at: float
    expires_at: float
    status: str
    outcome: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "parameters": self.parameters,
            "command": self.command,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status,
            "outcome": self.outcome,
        }


def _row(row: Any) -> PendingAction:
    try:
        parameters = json.loads(row["parameters"])
    except (TypeError, ValueError):
        parameters = {}
    return PendingAction(
        id=row["id"],
        device_id=row["device_id"],
        action=row["action"],
        parameters=parameters if isinstance(parameters, dict) else {},
        command=row["command"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        status=row["status"],
        outcome=row["outcome"],
    )


def _expire(store: Any, conn: Any, now: float) -> None:
    rows = conn.execute(
        "SELECT id, device_id, action FROM pending_actions "
        "WHERE status = ? AND expires_at <= ?",
        (PENDING, now),
    ).fetchall()
    for r in rows:
        conn.execute(
            "UPDATE pending_actions SET status = ?, decided_at = ? WHERE id = ?",
            (EXPIRED, now, r["id"]),
        )
        store._log(
            conn,
            "action_expired",
            device_id=r["device_id"],
            detail=f"#{r['id']} {r['action']}",
            now=now,
        )


def queue(
    store: Any,
    *,
    device_id: str,
    action: str,
    parameters: Mapping[str, Any],
    command: str,
    now: float | None = None,
) -> int:
    """Keep one action a phone asked for until someone at the PC decides."""
    now = time.time() if now is None else now
    with store._connect() as conn:
        _expire(store, conn, now)
        waiting = conn.execute(
            "SELECT id, action FROM pending_actions "
            "WHERE device_id = ? AND status = ? ORDER BY id",
            (device_id, PENDING),
        ).fetchall()
        for r in waiting[: max(0, len(waiting) - MAX_PENDING_PER_DEVICE + 1)]:
            conn.execute(
                "UPDATE pending_actions SET status = ?, decided_at = ? WHERE id = ?",
                (EXPIRED, now, r["id"]),
            )
            store._log(
                conn,
                "action_expired",
                device_id=device_id,
                detail=f"#{r['id']} {r['action']} (too many waiting)",
                now=now,
            )
        cur = conn.execute(
            "INSERT INTO pending_actions"
            "(device_id, action, parameters, command, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                device_id,
                action,
                json.dumps(dict(parameters), ensure_ascii=True, default=str),
                command[:500],
                now,
                now + PENDING_TTL_SECONDS,
            ),
        )
        new_id = int(cur.lastrowid)
        store._log(
            conn,
            "action_queued",
            device_id=device_id,
            detail=f"#{new_id} {action}",
            now=now,
        )
    return new_id


def list_pending(
    store: Any,
    *,
    device_id: str | None = None,
    include_decided: bool = False,
    limit: int = 50,
    now: float | None = None,
) -> list[PendingAction]:
    now = time.time() if now is None else now
    sql = "SELECT * FROM pending_actions"
    where, args = [], []
    if device_id is not None:
        where.append("device_id = ?")
        args.append(device_id)
    if not include_decided:
        where.append("status = ?")
        args.append(PENDING)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with store._connect() as conn:
        _expire(store, conn, now)
        rows = conn.execute(sql, args).fetchall()
    return [_row(r) for r in rows]


def _waiting_row(conn: Any, request_id: int) -> tuple[Any, str | None]:
    row = conn.execute(
        "SELECT * FROM pending_actions WHERE id = ?", (request_id,)
    ).fetchone()
    if row is None:
        return None, f"No request #{request_id}."
    if row["status"] != PENDING:
        return row, f"Request #{request_id} is {row['status']}, not waiting."
    return row, None


def claim(store: Any, request_id: int, *, now: float | None = None) -> PendingAction:
    """Take a waiting request for approval, so it can only ever run once.

    Refuses one that expired, was decided already, or came from a phone that
    has since been revoked. A refusal is raised only after the transaction
    commits, so the expiry or denial it records is kept.
    """
    now = time.time() if now is None else now
    with store._connect() as conn:
        _expire(store, conn, now)
        row, problem = _waiting_row(conn, request_id)
        if problem is None:
            device = conn.execute(
                "SELECT revoked FROM devices WHERE device_id = ?", (row["device_id"],)
            ).fetchone()
            if device is None or device["revoked"]:
                conn.execute(
                    "UPDATE pending_actions SET status = ?, decided_at = ?, "
                    "outcome = ? WHERE id = ?",
                    (DENIED, now, "phone was revoked", request_id),
                )
                store._log(
                    conn,
                    "action_denied",
                    device_id=row["device_id"],
                    detail=f"#{request_id} {row['action']} (phone revoked)",
                    now=now,
                )
                problem = f"Request #{request_id} came from a phone that was revoked."
        if problem is None:
            # Only a row still 'pending' flips, so two approvals cannot both run it.
            cur = conn.execute(
                "UPDATE pending_actions SET status = ?, decided_at = ? "
                "WHERE id = ? AND status = ?",
                (APPROVED, now, request_id, PENDING),
            )
            if cur.rowcount:
                store._log(
                    conn,
                    "action_approved",
                    device_id=row["device_id"],
                    detail=f"#{request_id} {row['action']}",
                    now=now,
                )
            else:  # pragma: no cover - a race with another approval
                problem = f"Request #{request_id} was just taken."
    if problem is not None:
        raise ApprovalError(problem)
    return _row(row)


def finish(store: Any, pending: PendingAction, *, success: bool, outcome: str) -> None:
    """Record what running an approved request did, and tell the phone."""
    status = DONE if success else FAILED
    with store._connect() as conn:
        conn.execute(
            "UPDATE pending_actions SET status = ?, outcome = ? WHERE id = ?",
            (status, outcome[:300], pending.id),
        )
        store._log(
            conn,
            "action_done",
            device_id=pending.device_id,
            detail=f"#{pending.id} {pending.action}={'ok' if success else 'failed'}",
        )
    store.push_notification(
        f"#{pending.id} {pending.action}: {'done' if success else 'not done'}",
        outcome,
        kind="action",
    )


def deny(store: Any, request_id: int, *, now: float | None = None) -> PendingAction:
    now = time.time() if now is None else now
    with store._connect() as conn:
        _expire(store, conn, now)
        row, problem = _waiting_row(conn, request_id)
        if problem is None:
            conn.execute(
                "UPDATE pending_actions SET status = ?, decided_at = ?, outcome = ? "
                "WHERE id = ?",
                (DENIED, now, "denied at the PC", request_id),
            )
            store._log(
                conn,
                "action_denied",
                device_id=row["device_id"],
                detail=f"#{request_id} {row['action']}",
                now=now,
            )
    if problem is not None:
        raise ApprovalError(problem)
    pending = _row(row)
    store.push_notification(
        f"#{pending.id} {pending.action}: not done",
        "Denied at the PC.",
        kind="action",
    )
    return pending


def run_approved(pending: PendingAction, confirm_callback: Any) -> Any:
    """Run a claimed request through the executor, exactly as the model asked.

    ``confirm_callback`` is the PC's own interactive prompt. With ``None`` (no
    terminal) the executor refuses, as it would in chat.
    """
    from grandpa.action_layer.catalogue import get
    from grandpa.action_layer.executor import execute
    from grandpa.action_layer.model import ActionRequest, Origin

    spec = get(pending.action)
    request = ActionRequest(
        action=spec.name,
        parameters=pending.parameters,
        origin=Origin.HTTP,
        risk=spec.risk,
        requires_confirmation=True,
    )
    return execute(request, confirm_callback)
