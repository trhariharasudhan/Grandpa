"""Safe communication workflow foundation for Grandpa."""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR


DEFAULT_COMM_DB = DEFAULT_CONFIG_DIR / "communication_integration.db"
SERVICES = ("whatsapp_web", "telegram", "discord", "slack", "gmail", "teams")


@dataclass(frozen=True)
class CommunicationResult:
    status: str
    message: str
    data: dict[str, Any]


class CommunicationStore:
    def __init__(self, db_path: Path | str = DEFAULT_COMM_DB) -> None:
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
                CREATE TABLE IF NOT EXISTS communication_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    service TEXT NOT NULL,
                    sender TEXT,
                    subject TEXT,
                    summary TEXT NOT NULL,
                    unread INTEGER NOT NULL DEFAULT 1,
                    redacted INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_replies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    service TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    draft TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending_approval'
                )
                """
            )

    def add_notification(self, service: str, sender: str, subject: str, summary: str) -> dict[str, Any]:
        service = _service(service)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO communication_notifications(created_at, service, sender, subject, summary, unread, redacted) VALUES (?, ?, ?, ?, ?, 1, 1)",
                (time.time(), service, _redact(sender), _redact(subject), _redact(summary)),
            )
        return {"id": cursor.lastrowid, "service": service, "summary": _redact(summary), "redacted": True}

    def notifications(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, service, sender, subject, summary, unread, redacted FROM communication_notifications ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def add_reply_draft(self, service: str, recipient: str, draft: str) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO pending_replies(created_at, service, recipient, draft) VALUES (?, ?, ?, ?)",
                (time.time(), _service(service), _redact(recipient), _redact(draft)),
            )
        return {"id": cursor.lastrowid, "service": _service(service), "recipient": _redact(recipient), "approval_required": True}

    def pending_replies(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, service, recipient, draft, status FROM pending_replies ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]


def inbox_summary(service: str, *, store: CommunicationStore | None = None) -> CommunicationResult:
    store = store or CommunicationStore()
    service = _service(service)
    items = [item for item in store.notifications() if item["service"] == service]
    unread = sum(1 for item in items if item["unread"])
    return CommunicationResult(
        "handled",
        f"{service.replace('_', ' ').title()} has {unread} unread local notification(s).",
        {"service": service, "unread": unread, "notifications": items[:10]},
    )


def reply_plan(service: str, recipient: str, intent: str, *, store: CommunicationStore | None = None) -> CommunicationResult:
    store = store or CommunicationStore()
    draft = f"Hi {recipient},\n\n{intent.strip()}\n\n"
    pending = store.add_reply_draft(service, recipient, draft)
    return CommunicationResult(
        "requires_confirmation",
        f"Prepared a {service} reply draft. Approval is required before sending.",
        {"pending_reply": pending, "draft_preview": _redact(draft[:400])},
    )


def aggregate_notifications(*, store: CommunicationStore | None = None) -> CommunicationResult:
    store = store or CommunicationStore()
    items = store.notifications()
    counts = {service: 0 for service in SERVICES}
    for item in items:
        if item["unread"]:
            counts[item["service"]] = counts.get(item["service"], 0) + 1
    return CommunicationResult("handled", "Aggregated local communication notifications.", {"unread_counts": counts, "notifications": items[:20]})


def diagnostics(store: CommunicationStore | None = None) -> dict[str, Any]:
    store = store or CommunicationStore()
    aggregate = aggregate_notifications(store=store).data
    return {
        "status": "ready",
        "services": [
            {"id": "whatsapp_web", "mode": "browser visible-tab workflow", "send_requires_approval": True},
            {"id": "telegram", "mode": "foundation", "send_requires_approval": True},
            {"id": "discord", "mode": "notification bridge foundation", "send_requires_approval": True},
            {"id": "slack", "mode": "notification bridge foundation", "send_requires_approval": True},
            {"id": "gmail", "mode": "draft and inbox-summary helpers", "send_requires_approval": True},
            {"id": "teams", "mode": "notification summary foundation", "send_requires_approval": True},
        ],
        "unread_counts": aggregate["unread_counts"],
        "pending_replies": store.pending_replies(),
        "workflow_suggestions": ["summarize Gmail notifications", "draft WhatsApp reply", "review Teams-style alerts"],
        "safety": {"no_hidden_account_access": True, "reply_approval_required": True, "logs_redacted": True, "local_first": True},
        "storage": {"backend": "sqlite", "path": str(store.db_path), "local_only": True},
    }


def _service(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    aliases = {"whatsapp": "whatsapp_web", "teams_style": "teams"}
    return aliases.get(clean, clean if clean in SERVICES else "gmail")


def _redact(text: str) -> str:
    if any(word in text.lower() for word in ("password", "otp", "token", "secret", "card")):
        return "[redacted sensitive communication content]"
    return text


__all__ = [
    "CommunicationResult",
    "CommunicationStore",
    "aggregate_notifications",
    "diagnostics",
    "inbox_summary",
    "reply_plan",
]
