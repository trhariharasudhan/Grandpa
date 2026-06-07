"""Local-first Android companion bridge for Grandpa."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_MOBILE_DB = DEFAULT_CONFIG_DIR / "mobile_integration.db"
PAIRING_TTL_SECONDS = 600
ONLINE_WINDOW_SECONDS = 90


@dataclass(frozen=True)
class MobileResult:
    status: str
    message: str
    data: dict[str, Any]


class MobileBridgeStore:
    """SQLite store for local LAN companion pairing, heartbeats, and events."""

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
                    pairing_expires_at REAL,
                    token_hash TEXT NOT NULL DEFAULT '',
                    permissions_json TEXT NOT NULL DEFAULT '{}',
                    last_seen_at REAL,
                    status_json TEXT NOT NULL DEFAULT '{}',
                    trusted INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            _ensure_columns(
                conn,
                "mobile_devices",
                {
                    "pairing_expires_at": "REAL",
                    "token_hash": "TEXT NOT NULL DEFAULT ''",
                    "permissions_json": "TEXT NOT NULL DEFAULT '{}'",
                    "trusted": "INTEGER NOT NULL DEFAULT 0",
                },
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
                    approval_required INTEGER NOT NULL DEFAULT 0,
                    response_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            _ensure_columns(
                conn,
                "mobile_commands",
                {"response_json": "TEXT NOT NULL DEFAULT '{}'"},
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mobile_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    device_id TEXT,
                    event_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mobile_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    device_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    delivered_at REAL
                )
                """
            )

    def create_pairing(self, name: str) -> dict[str, Any]:
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = time.time()
        device_id = hashlib.sha256(f"{name}:{now}:{code}".encode()).hexdigest()[:16]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mobile_devices(
                    device_id, created_at, name, paired, pairing_hash,
                    pairing_expires_at, status_json, permissions_json
                )
                VALUES (?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    now,
                    name.strip() or "Android device",
                    _hash_secret(code),
                    now + PAIRING_TTL_SECONDS,
                    "{}",
                    json.dumps(_default_permissions()),
                ),
            )
            _record_event(
                conn,
                device_id,
                "pairing_created",
                "Pairing code created for local Android companion.",
                {"device_name": name, "expires_at": now + PAIRING_TTL_SECONDS},
            )
        return {
            "device_id": device_id,
            "pairing_code": code,
            "expires_in_seconds": PAIRING_TTL_SECONDS,
            "local_only": True,
            "websocket_path": "/v1/mobile/ws",
            "qr_payload": pairing_qr_payload(device_id, code),
        }

    def confirm_pairing(
        self,
        device_id: str,
        code: str,
        *,
        status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        token = secrets.token_urlsafe(32)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT pairing_hash, pairing_expires_at, paired FROM mobile_devices WHERE device_id=?",
                (device_id,),
            ).fetchone()
            if not row:
                return {"ok": False, "message": "Pairing request was not found."}
            if row["paired"]:
                return {"ok": False, "message": "This device is already paired."}
            if row["pairing_expires_at"] and now > float(row["pairing_expires_at"]):
                return {"ok": False, "message": "Pairing code expired."}
            if row["pairing_hash"] != _hash_secret(code):
                return {"ok": False, "message": "Pairing code did not match."}
            conn.execute(
                """
                UPDATE mobile_devices
                SET paired=1, trusted=1, token_hash=?, last_seen_at=?,
                    status_json=?, pairing_hash='', pairing_expires_at=NULL
                WHERE device_id=?
                """,
                (_hash_secret(token), now, json.dumps(_safe_status(status or {})), device_id),
            )
            _record_event(
                conn,
                device_id,
                "paired",
                "Android companion paired over local LAN.",
                {"local_only": True},
            )
        return {
            "ok": True,
            "device_id": device_id,
            "trusted_token": token,
            "message": "Device paired with Grandpa.",
            "local_only": True,
        }

    def authenticate(self, device_id: str, token: str) -> bool:
        if not device_id or not token:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT token_hash, paired, trusted FROM mobile_devices WHERE device_id=?",
                (device_id,),
            ).fetchone()
        return bool(
            row
            and row["paired"]
            and row["trusted"]
            and row["token_hash"]
            and secrets.compare_digest(row["token_hash"], _hash_secret(token))
        )

    def update_status(self, device_id: str, status: dict[str, Any]) -> dict[str, Any]:
        safe = _safe_status(status)
        permissions = _safe_permissions(status.get("permissions") if isinstance(status.get("permissions"), dict) else status)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE mobile_devices SET last_seen_at=?, status_json=?, permissions_json=? WHERE device_id=?",
                (now, json.dumps(safe), json.dumps(permissions), device_id),
            )
            _record_event(
                conn,
                device_id,
                "heartbeat",
                "Device heartbeat received.",
                {
                    "battery": safe.get("battery"),
                    "charging": safe.get("charging"),
                    "websocket_state": safe.get("websocket_state"),
                    "background_heartbeat": safe.get("background_heartbeat"),
                },
            )
        return {"ok": True, "device_id": device_id, "status": safe, "permissions": permissions, "online": True}

    def expire_stale_heartbeats(self) -> dict[str, Any]:
        """Return heartbeat health without mutating trusted pairing records."""
        devices = self.devices()
        return {
            "checked_at": time.time(),
            "online_devices": sum(1 for device in devices if device["online"]),
            "offline_devices": sum(1 for device in devices if device["paired"] and not device["online"]),
            "online_window_seconds": ONLINE_WINDOW_SECONDS,
        }

    def devices(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT device_id, created_at, name, paired, trusted,
                       last_seen_at, status_json, permissions_json
                FROM mobile_devices ORDER BY created_at DESC
                """
            ).fetchall()
        devices: list[dict[str, Any]] = []
        for row in rows:
            last_seen = row["last_seen_at"]
            devices.append(
                {
                    "device_id": row["device_id"],
                    "created_at": row["created_at"],
                    "name": row["name"],
                    "paired": bool(row["paired"]),
                    "trusted": bool(row["trusted"]),
                    "online": bool(last_seen and now - float(last_seen) <= ONLINE_WINDOW_SECONDS),
                    "last_seen_at": last_seen,
                    "status": _loads(row["status_json"]),
                    "permissions": _loads(row["permissions_json"]),
                }
            )
        return devices

    def record_notification(
        self,
        device_id: str,
        kind: str,
        app: str,
        title: str,
        summary: str,
    ) -> dict[str, Any]:
        title = _redact(title)
        summary = _redact(summary)
        kind = _safe_label(kind, default="app")
        app = _safe_label(app, default="Android")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO mobile_notifications(
                    created_at, device_id, kind, app, title, summary, redacted
                )
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (time.time(), device_id, kind, app, title, summary),
            )
            _record_event(
                conn,
                device_id,
                "notification",
                f"Redacted {kind} notification synced.",
                {"app": app, "notification_id": cursor.lastrowid},
            )
        return {
            "id": cursor.lastrowid,
            "kind": kind,
            "app": app,
            "title": title,
            "summary": summary,
            "redacted": True,
        }

    def notifications(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, device_id, kind, app, title, summary, redacted
                FROM mobile_notifications ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def record_remote_command(
        self,
        device_id: str,
        command: str,
        result: MobileResult,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO mobile_commands(
                    created_at, device_id, command, status, approval_required, response_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    device_id,
                    _redact(command),
                    result.status,
                    int(bool(result.data.get("approval_required"))),
                    json.dumps(result.data),
                ),
            )
            _record_event(
                conn,
                device_id,
                "remote_command",
                result.message,
                {"command_id": cursor.lastrowid, "status": result.status},
            )
        return {"id": cursor.lastrowid, "status": result.status, "message": result.message, **result.data}

    def commands(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, device_id, command, status,
                       approval_required, response_json
                FROM mobile_commands ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "device_id": row["device_id"],
                "command": row["command"],
                "status": row["status"],
                "approval_required": bool(row["approval_required"]),
                "response": _loads(row["response_json"]),
            }
            for row in rows
        ]

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, device_id, event_type, summary, payload_json
                FROM mobile_events ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "device_id": row["device_id"],
                "event_type": row["event_type"],
                "summary": row["summary"],
                "payload": _loads(row["payload_json"]),
            }
            for row in rows
        ]

    def queue_push_notification(
        self,
        device_id: str,
        title: str,
        body: str,
        *,
        event_type: str = "assistant_notification",
    ) -> dict[str, Any]:
        payload = {
            "title": _redact(title),
            "body": _redact(body),
            "local_only": True,
        }
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO mobile_outbox(created_at, device_id, event_type, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (time.time(), device_id, event_type, json.dumps(payload)),
            )
            _record_event(
                conn,
                device_id,
                "push_queued",
                "Assistant notification queued for paired mobile device.",
                {"outbox_id": cursor.lastrowid},
            )
        return {"id": cursor.lastrowid, "event_type": event_type, "payload": payload}

    def pending_outbox(self, device_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, event_type, payload_json
                FROM mobile_outbox
                WHERE delivered_at IS NULL AND (device_id = ? OR device_id = '')
                ORDER BY created_at ASC LIMIT ?
                """,
                (device_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "event_type": row["event_type"],
                "payload": _loads(row["payload_json"]),
            }
            for row in rows
        ]

    def mark_outbox_delivered(self, outbox_ids: list[int]) -> int:
        if not outbox_ids:
            return 0
        placeholders = ",".join("?" for _ in outbox_ids)
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE mobile_outbox SET delivered_at=? WHERE id IN ({placeholders})",
                (time.time(), *outbox_ids),
            )
            return int(cursor.rowcount or 0)


def plan_remote_command(command: str, *, device_id: str = "") -> MobileResult:
    text = command.strip()
    lowered = text.lower()
    risky = any(word in lowered for word in ("delete", "send", "call", "pay", "password", "clipboard"))
    if not text:
        return MobileResult(
            "unsupported",
            "No mobile command was provided.",
            {"device_id": device_id, "approval_required": False, "local_lan_only": True},
        )
    if risky:
        return MobileResult(
            "requires_confirmation",
            "Remote mobile command needs approval before Grandpa runs it.",
            {"device_id": device_id, "command": _redact(text), "approval_required": True, "local_lan_only": True},
        )
    return MobileResult(
        "queued",
        "Remote mobile command queued for Grandpa.",
        {"device_id": device_id, "command": _redact(text), "approval_required": False, "local_lan_only": True},
    )


def pairing_qr_payload(device_id: str, pairing_code: str, *, host: str = "") -> dict[str, Any]:
    """Return a QR-safe local pairing payload for the Android app."""
    return {
        "type": "grandpa_pairing",
        "version": 1,
        "device_id": device_id,
        "pairing_code": pairing_code,
        "host": host,
        "websocket_path": "/v1/mobile/ws",
        "local_only": True,
        "expires_in_seconds": PAIRING_TTL_SECONDS,
    }


def voice_relay_plan(transcript: str, *, device_id: str = "") -> MobileResult:
    text = transcript.strip()
    if not text:
        return MobileResult(
            "unsupported",
            "No voice transcript was received from the phone.",
            {"device_id": device_id, "voice_relay": True},
        )
    result = plan_remote_command(text, device_id=device_id)
    return MobileResult(
        result.status,
        "Phone voice command received. " + result.message,
        {**result.data, "voice_relay": True, "transcript": _redact(text[:240])},
    )


def clipboard_sync_plan(device_id: str, direction: str) -> MobileResult:
    return MobileResult(
        "requires_confirmation",
        "Clipboard sync requires approval before any clipboard content moves between devices.",
        {
            "device_id": device_id,
            "direction": direction,
            "approval_required": True,
            "content_redacted": True,
            "local_lan_only": True,
        },
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
    notifications = store.notifications(limit=10)
    commands = store.commands(limit=10)
    online = [device for device in devices if device["online"]]
    latest_event = store.events(limit=1)
    heartbeat = store.expire_stale_heartbeats()
    notification_ready = any(device["permissions"].get("notifications") for device in devices)
    mic_ready = any(device["permissions"].get("voice_relay") for device in devices)
    background_ready = any(device["status"].get("background_heartbeat") for device in devices)
    return {
        "status": "ready",
        "architecture": {
            "transport": "local LAN WebSocket + localhost HTTP",
            "websocket_path": "/v1/mobile/ws",
            "cloud_required": False,
            "companion_app_required": True,
            "android_app": "mobile/android_companion",
        },
        "devices": devices,
        "connected_devices": sum(1 for device in devices if device["paired"]),
        "online_devices": len(online),
        "notifications": notifications,
        "commands": commands,
        "events": store.events(limit=12),
        "heartbeat": heartbeat,
        "websocket": {
            "path": "/v1/mobile/ws",
            "status": "online" if online else "waiting_for_device",
            "online_devices": len(online),
            "last_heartbeat_age_seconds": _last_heartbeat_age(devices),
        },
        "permission_state": {
            "notification_listener": "ready" if notification_ready else "needs_android_permission",
            "microphone": "ready" if mic_ready else "needs_android_permission",
            "background_heartbeat": "ready" if background_ready else "foreground_only_or_not_reported",
        },
        "relay_state": {
            "voice_relay": "ready" if mic_ready and online else "waiting_for_online_device",
            "notification_sync": "ready" if notification_ready and online else "waiting_for_permission_or_device",
            "remote_commands": "ready" if online else "waiting_for_online_device",
        },
        "last_mobile_event": latest_event[0] if latest_event else None,
        "features": {
            "secure_pairing": True,
            "trusted_device_tokens": True,
            "heartbeat_tracking": True,
            "notification_sync": ["calls", "messages", "app notifications"],
            "device_status": ["battery", "charging", "connectivity", "device_name"],
            "remote_commands": "approval gated",
            "voice_relay": "phone transcript to Grandpa command pipeline",
            "clipboard_sync": "approval gated",
            "qr_pairing": True,
            "mobile_push_notifications": True,
            "reconnect_recovery": True,
            "contacts_calendar_sync": "consent required",
        },
        "safety": {
            "no_hidden_scraping": True,
            "user_consent_first": True,
            "local_only_pairing": True,
            "cloud_required": False,
            "clipboard_content_logged": False,
            "sensitive_notifications_redacted": True,
        },
        "storage": {"backend": "sqlite", "path": str(store.db_path), "local_only": True},
        "real_device_validation": {
            "adb_required_for_install": True,
            "usb_debugging_required": True,
            "same_lan_required": True,
            "background_limits": "Android may pause background work unless the user allows notification and battery settings.",
        },
    }


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _record_event(
    conn: sqlite3.Connection,
    device_id: str,
    event_type: str,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO mobile_events(created_at, device_id, event_type, summary, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (time.time(), device_id, event_type, summary, json.dumps(_redact_dict(payload or {}))),
    )


def _default_permissions() -> dict[str, bool]:
    return {
        "notifications": False,
        "battery_status": True,
        "remote_commands": True,
        "voice_relay": False,
        "clipboard_sync": False,
    }


def _safe_permissions(raw: dict[str, Any]) -> dict[str, bool]:
    defaults = _default_permissions()
    return {
        **defaults,
        "notifications": bool(
            raw.get("notifications")
            or raw.get("notification_listener_enabled")
            or raw.get("notification_access")
        ),
        "battery_status": True,
        "remote_commands": True,
        "voice_relay": bool(raw.get("voice_relay") or raw.get("microphone_ready") or raw.get("microphone")),
        "clipboard_sync": bool(raw.get("clipboard_sync")),
    }


def _safe_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_name": str(status.get("device_name") or status.get("name") or "")[:80],
        "battery": _safe_number(status.get("battery")),
        "charging": bool(status.get("charging")) if "charging" in status else None,
        "connectivity": _safe_label(str(status.get("connectivity", "unknown")), default="unknown"),
        "platform": _safe_label(str(status.get("platform", "android")), default="android"),
        "app_version": str(status.get("app_version", ""))[:40],
        "websocket_state": _safe_label(str(status.get("websocket_state", "unknown")), default="unknown"),
        "notification_listener_enabled": bool(status.get("notification_listener_enabled")),
        "microphone_ready": bool(status.get("microphone_ready") or status.get("voice_relay")),
        "background_heartbeat": bool(status.get("background_heartbeat")),
        "battery_optimization_ignored": bool(status.get("battery_optimization_ignored")),
        "last_error": _redact(str(status.get("last_error", "")))[:160],
    }


def _safe_number(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, number))


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _loads(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _last_heartbeat_age(devices: list[dict[str, Any]]) -> float | None:
    last_seen_values = [float(device["last_seen_at"]) for device in devices if device.get("last_seen_at")]
    if not last_seen_values:
        return None
    return round(time.time() - max(last_seen_values), 1)


def _safe_label(value: str, *, default: str) -> str:
    cleaned = " ".join(value.strip().split())
    return cleaned[:80] or default


def _redact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if any(token in key.lower() for token in ("token", "password", "secret", "clipboard")):
            redacted[key] = "[redacted]"
        elif isinstance(value, str):
            redacted[key] = _redact(value)
        else:
            redacted[key] = value
    return redacted


def _redact(text: str) -> str:
    lowered = text.lower()
    sensitive = ("password", "otp", "token", "api key", "card", "cvv", "clipboard")
    if any(word in lowered for word in sensitive):
        return "[redacted sensitive mobile content]"
    return text


__all__ = [
    "MobileBridgeStore",
    "MobileResult",
    "clipboard_sync_plan",
    "contact_calendar_sync_plan",
    "diagnostics",
    "pairing_qr_payload",
    "plan_remote_command",
    "voice_relay_plan",
    "voice_to_message_plan",
]
