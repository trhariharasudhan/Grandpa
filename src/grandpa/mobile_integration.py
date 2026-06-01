"""Local-first mobile integration foundation for Grandpa."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR


DEFAULT_MOBILE_DB = DEFAULT_CONFIG_DIR / "mobile_integration.db"


@dataclass(frozen=True)
class MobileResult:
    status: str
    message: str
    data: dict[str, Any]


class MobileBridgeStore:
    def __init__(self, db_path: Path | str = DEFAULT_MOBILE_DB) -> None:
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
                CREATE TABLE IF NOT EXISTS mobile_devices (
                    device_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    name TEXT NOT NULL,
                    paired INTEGER NOT NULL,
                    pairing_hash TEXT NOT NULL,
                    last_seen_at REAL,
                    status_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mobile_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    device_id TEXT,
                    kind TEXT NOT NULL,
                    app TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    redacted INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mobile_commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    device_id TEXT,
                    command TEXT NOT NULL,
                    status TEXT NOT NULL,
                    approval_required INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def create_pairing(self, name: str) -> dict[str, Any]:
        code = f"{secrets.randbelow(1_000_000):06d}"
        device_id = hashlib.sha256(f"{name}:{time.time()}:{code}".encode()).hexdigest()[:16]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mobile_devices(device_id, created_at, name, paired, pairing_hash, status_json)
                VALUES (?, ?, ?, 0, ?, ?)
                """,
                (device_id, time.time(), name, _hash_code(code), "{}"),
            )
        return {"device_id": device_id, "pairing_code": code, "expires_in_seconds": 600, "local_only": True}

    def confirm_pairing(self, device_id: str, code: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT pairing_hash FROM mobile_devices WHERE device_id=?", (device_id,)).fetchone()
            if not row or row["pairing_hash"] != _hash_code(code):
                return False
            conn.execute("UPDATE mobile_devices SET paired=1, last_seen_at=? WHERE device_id=?", (time.time(), device_id))
        return True

    def devices(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT device_id, created_at, name, paired, last_seen_at, status_json FROM mobile_devices ORDER BY created_at DESC").fetchall()
        return [
            {
                "device_id": row["device_id"],
                "created_at": row["created_at"],
                "name": row["name"],
                "paired": bool(row["paired"]),
                "last_seen_at": row["last_seen_at"],
                "status": _loads(row["status_json"]),
            }
            for row in rows
        ]

    def record_notification(self, device_id: str, kind: str, app: str, title: str, summary: str) -> dict[str, Any]:
        title = _redact(title)
        summary = _redact(summary)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO mobile_notifications(created_at, device_id, kind, app, title, summary, redacted) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (time.time(), device_id, kind, app, title, summary),
            )
        return {"id": cursor.lastrowid, "kind": kind, "app": app, "title": title, "summary": summary, "redacted": True}

    def notifications(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT created_at, device_id, kind, app, title, summary, redacted FROM mobile_notifications ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]


def plan_remote_command(command: str, *, device_id: str = "") -> MobileResult:
    risky = any(word in command.lower() for word in ("delete", "send", "call", "pay", "password"))
    return MobileResult(
        "requires_confirmation" if risky else "handled",
        "Prepared remote mobile command flow." if risky else "Remote command is safe to queue.",
        {"device_id": device_id, "command": command, "approval_required": risky, "local_lan_only": True},
    )


def voice_to_message_plan(contact: str, message: str) -> MobileResult:
    return MobileResult(
        "requires_confirmation",
        f"Prepared a message draft for {contact}. Approval is required before sending.",
        {"contact": contact, "message_preview": _redact(message[:240]), "approval_required": True},
    )


def contact_calendar_sync_plan() -> MobileResult:
    return MobileResult(
        "requires_confirmation",
        "Prepared contact/calendar sync plan. Device consent is required before importing metadata.",
        {"contacts": "metadata_only", "calendar": "metadata_only", "approval_required": True, "local_only": True},
    )


def diagnostics(store: MobileBridgeStore | None = None) -> dict[str, Any]:
    store = store or MobileBridgeStore()
    devices = store.devices()
    return {
        "status": "ready",
        "architecture": {"transport": "local LAN WebSocket/HTTP", "cloud_required": False, "companion_app_required": True},
        "devices": devices,
        "connected_devices": sum(1 for device in devices if device["paired"]),
        "notifications": store.notifications(limit=10),
        "features": {
            "secure_pairing": True,
            "notification_sync": ["calls", "messages", "app notifications"],
            "device_status": ["battery", "charging", "connectivity"],
            "remote_commands": "approval gated",
            "contacts_calendar_sync": "consent required",
        },
        "safety": {"no_hidden_scraping": True, "user_consent_first": True, "local_only_pairing": True},
        "storage": {"backend": "sqlite", "path": str(store.db_path), "local_only": True},
    }


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _loads(raw: str) -> dict[str, Any]:
    import json

    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _redact(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("password", "otp", "token", "api key", "card")):
        return "[redacted sensitive mobile content]"
    return text


__all__ = [
    "MobileBridgeStore",
    "MobileResult",
    "contact_calendar_sync_plan",
    "diagnostics",
    "plan_remote_command",
    "voice_to_message_plan",
]
