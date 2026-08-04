"""Production-minded local safety helpers for Grandpa."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_SECURITY_DB = DEFAULT_CONFIG_DIR / "security_safety.db"
SENSITIVE_PATTERN = re.compile(
    r"\b(password|secret|token|api[_ -]?key|credential|private key)\b", re.I
)
SUSPICIOUS_PATTERN = re.compile(
    r"\b(delete|format|wipe|shutdown|restart|payment|purchase|password|credential|registry|powershell)\b",
    re.I,
)


@dataclass(frozen=True)
class SecurityResult:
    status: str
    message: str
    data: dict[str, Any]


class SecurityStore:
    def __init__(self, db_path: Path | str = DEFAULT_SECURITY_DB) -> None:
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
                CREATE TABLE IF NOT EXISTS sensitive_memory (
                    key TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    ciphertext TEXT NOT NULL,
                    salt TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    detail_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS safety_policy (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                )
                """
            )

    def record_event(
        self, event_type: str, severity: str, detail: dict[str, Any]
    ) -> None:
        redacted = redact_sensitive(detail)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO security_events(created_at, event_type, severity, detail_json) VALUES (?, ?, ?, ?)",
                (time.time(), event_type, severity, json.dumps(redacted)),
            )

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT created_at, event_type, severity, detail_json FROM security_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = {key: row[key] for key in row.keys()}
            try:
                item["detail"] = json.loads(item.pop("detail_json") or "{}")
            except json.JSONDecodeError:
                item["detail"] = {}
            result.append(item)
        return result

    def set_policy(self, key: str, value: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO safety_policy(key, value_json) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (key, json.dumps(value)),
            )

    def policies(self) -> dict[str, Any]:
        defaults = default_policies()
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value_json FROM safety_policy").fetchall()
        for row in rows:
            try:
                defaults[row["key"]] = json.loads(row["value_json"])
            except json.JSONDecodeError:
                continue
        return defaults

    def store_sensitive(self, key: str, value: str, passphrase: str) -> None:
        salt = os.urandom(16)
        encrypted = _xor_cipher(value.encode("utf-8"), _derive_key(passphrase, salt))
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sensitive_memory(key, created_at, updated_at, ciphertext, salt)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    ciphertext = excluded.ciphertext,
                    salt = excluded.salt
                """,
                (
                    key,
                    now,
                    now,
                    base64.b64encode(encrypted).decode("ascii"),
                    base64.b64encode(salt).decode("ascii"),
                ),
            )
        self.record_event(
            "sensitive_memory_store", "info", {"key": key, "value": "[encrypted]"}
        )

    def load_sensitive(self, key: str, passphrase: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT ciphertext, salt FROM sensitive_memory WHERE key=?", (key,)
            ).fetchone()
        if not row:
            return None
        salt = base64.b64decode(row["salt"])
        raw = base64.b64decode(row["ciphertext"])
        return _xor_cipher(raw, _derive_key(passphrase, salt)).decode(
            "utf-8", errors="replace"
        )


def default_policies() -> dict[str, Any]:
    return {
        "automation": {
            "medium_requires_approval": True,
            "high_blocked": True,
            "max_chain_steps": 20,
        },
        "browser": {
            "forms_require_approval": True,
            "payments_blocked": True,
            "localhost_snapshots_only": True,
        },
        "file": {
            "delete_requires_approval": True,
            "protected_paths_blocked": True,
            "bulk_requires_approval": True,
        },
        "admin": {"enabled": False, "pin_hash": None, "lock_sensitive_actions": True},
    }


def suspicious_action_score(text: str) -> dict[str, Any]:
    matches = sorted(
        set(match.group(0).lower() for match in SUSPICIOUS_PATTERN.finditer(text))
    )
    score = min(1.0, len(matches) * 0.22)
    severity = "critical" if score >= 0.75 else "warning" if score >= 0.35 else "info"
    return {
        "score": round(score, 3),
        "severity": severity,
        "matches": matches,
        "suspicious": bool(matches),
    }


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[redacted]"
                if SENSITIVE_PATTERN.search(str(key))
                else redact_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str) and SENSITIVE_PATTERN.search(value):
        return "[redacted]"
    return value


def set_admin_pin(pin: str, *, store: SecurityStore | None = None) -> SecurityResult:
    store = store or SecurityStore()
    if len(pin) < 4:
        return SecurityResult("blocked", "Admin PIN must be at least 4 characters.", {})
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100_000)
    policies = store.policies()
    policies["admin"] = {
        "enabled": True,
        "pin_hash": base64.b64encode(salt + digest).decode("ascii"),
        "lock_sensitive_actions": True,
    }
    store.set_policy("admin", policies["admin"])
    store.record_event("admin_pin_set", "info", {"pin": "[redacted]"})
    return SecurityResult(
        "handled", "Admin protection is enabled.", {"admin_enabled": True}
    )


def verify_admin_pin(pin: str, *, store: SecurityStore | None = None) -> bool:
    store = store or SecurityStore()
    raw_hash = store.policies().get("admin", {}).get("pin_hash")
    if not raw_hash:
        return False
    raw = base64.b64decode(raw_hash)
    salt, expected = raw[:16], raw[16:]
    actual = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100_000)
    return hmac.compare_digest(actual, expected)


def security_health_score(store: SecurityStore | None = None) -> dict[str, Any]:
    store = store or SecurityStore()
    policies = store.policies()
    score = 65
    if policies.get("admin", {}).get("enabled"):
        score += 10
    if policies.get("file", {}).get("protected_paths_blocked"):
        score += 10
    if policies.get("browser", {}).get("payments_blocked"):
        score += 8
    if policies.get("automation", {}).get("high_blocked"):
        score += 7
    return {
        "score": min(100, score),
        "label": "STRONG" if score >= 85 else "GOOD" if score >= 70 else "NEEDS SETUP",
    }


def export_audit_plan() -> SecurityResult:
    return SecurityResult(
        "requires_confirmation",
        "Prepared safe audit export. Approval is required before writing an export file.",
        {"approval_required": True, "redacted": True, "format": "jsonl"},
    )


def diagnostics(store: SecurityStore | None = None) -> dict[str, Any]:
    store = store or SecurityStore()
    return {
        "status": "ready",
        "policies": store.policies(),
        "health": security_health_score(store),
        "recent_events": store.events(limit=20),
        "suspicious_detection": True,
        "encrypted_sensitive_memory": True,
        "audit_export_requires_approval": True,
        "storage": {
            "backend": "sqlite",
            "path": str(store.db_path),
            "local_only": True,
        },
    }


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 100_000)


def _xor_cipher(data: bytes, key: bytes) -> bytes:
    return bytes(byte ^ key[idx % len(key)] for idx, byte in enumerate(data))


__all__ = [
    "SecurityResult",
    "SecurityStore",
    "default_policies",
    "diagnostics",
    "export_audit_plan",
    "redact_sensitive",
    "security_health_score",
    "set_admin_pin",
    "suspicious_action_score",
    "verify_admin_pin",
]
