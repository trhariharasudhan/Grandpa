"""LAN pairing with device auth (D1).

How a phone becomes trusted:

1. On the PC, ``grandpa devices pair`` opens a pairing window: a random
   6-digit code that lives for five minutes and is good for one use.
2. The phone sends that code to ``POST /v1/devices/pair`` on the PC.
3. If the code is right, the PC answers once with a device token. Only a hash
   of the token is kept, so it cannot be read back out of ``devices.db``.

What keeps it safe:

* No window, no pairing: the endpoint refuses everything unless someone at the
  PC opened a window in the last five minutes.
* Five wrong codes close the window, so guessing has a 5-in-a-million chance.
* A code works once; pairing a second phone needs a second code.
* Codes and tokens are stored as SHA-256 hashes and compared in constant time.
* A device token is not the API key. It only opens the routes listed in
  ``grandpa.server.auth_middleware.DEVICE_ALLOWED_PATHS``; D2 widens that list
  one route at a time.
* ``grandpa devices revoke <id>`` stops a token at once.
* Every pairing step is written to the ``events`` table.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

#: Every device token starts with this, so the middleware can tell one from
#: the API key without a database lookup.
DEVICE_TOKEN_PREFIX = "gp_dev_"

PAIRING_TTL_SECONDS = 300
MAX_PAIRING_ATTEMPTS = 5
CODE_DIGITS = 6
MAX_NAME_LENGTH = 40


class PairingError(Exception):
    """A pairing attempt was refused. The message is safe to show the phone."""


@dataclass(frozen=True, slots=True)
class PairingCode:
    code: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class Device:
    device_id: str
    name: str
    created_at: float
    last_seen_at: float | None
    revoked: bool


@dataclass(frozen=True, slots=True)
class PairedDevice:
    device: Device
    token: str


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _clean_name(name: str) -> str:
    cleaned = "".join(ch for ch in (name or "") if ch.isprintable()).strip()
    return cleaned[:MAX_NAME_LENGTH] or "Phone"


def default_db_path() -> Path:
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / "devices.db"


class DeviceStore:
    """Paired devices, the open pairing window, and the pairing log."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id    TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    token_hash   TEXT NOT NULL UNIQUE,
                    created_at   REAL NOT NULL,
                    last_seen_at REAL,
                    revoked      INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS pairing_window (
                    id         INTEGER PRIMARY KEY CHECK (id = 1),
                    code_hash  TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    attempts   INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS events (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    at        REAL NOT NULL,
                    event     TEXT NOT NULL,
                    device_id TEXT,
                    detail    TEXT
                );
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """One transaction: committed on success, rolled back on error, closed
        either way (an open handle keeps the file locked on Windows)."""
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _log(
        conn: sqlite3.Connection,
        event: str,
        device_id: str | None = None,
        detail: str = "",
        now: float | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO events(at, event, device_id, detail) VALUES (?, ?, ?, ?)",
            (time.time() if now is None else now, event, device_id, detail[:200]),
        )

    # -- pairing ----------------------------------------------------------

    def start_pairing(
        self, *, ttl: float = PAIRING_TTL_SECONDS, now: float | None = None
    ) -> PairingCode:
        """Open a pairing window, replacing any earlier one."""
        now = time.time() if now is None else now
        code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
        expires_at = now + ttl
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO pairing_window(id, code_hash, expires_at, "
                "attempts) VALUES (1, ?, ?, 0)",
                (_hash(code), expires_at),
            )
            self._log(conn, "pairing_started", now=now)
        return PairingCode(code=code, expires_at=expires_at)

    def cancel_pairing(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pairing_window")

    def pairing_open(self, *, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._connect() as conn:
            row = conn.execute("SELECT expires_at FROM pairing_window").fetchone()
        return row is not None and row["expires_at"] > now

    def complete_pairing(
        self, code: str, name: str, *, now: float | None = None
    ) -> PairedDevice:
        """Trade a pairing code for a device token, or raise PairingError."""
        now = time.time() if now is None else now
        name = _clean_name(name)
        error: str | None = None
        token = device_id = ""
        # Refusals are committed before raising: an exception inside the
        # ``with`` would roll back the attempt count and the log line.
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT code_hash, expires_at, attempts FROM pairing_window"
            ).fetchone()
            given = (code or "").strip()
            if row is None:
                self._log(conn, "pair_refused", detail="no window", now=now)
                error = "Pairing is not open. Run 'grandpa devices pair' on the PC."
            elif row["expires_at"] <= now:
                conn.execute("DELETE FROM pairing_window")
                self._log(conn, "pair_refused", detail="code expired", now=now)
                error = "That code has expired. Make a new one on the PC."
            elif not hmac.compare_digest(_hash(given), row["code_hash"]):
                attempts = row["attempts"] + 1
                if attempts >= MAX_PAIRING_ATTEMPTS:
                    conn.execute("DELETE FROM pairing_window")
                    detail = "too many wrong codes"
                    error = "Too many wrong codes. Pairing is closed; make a new code."
                else:
                    conn.execute(
                        "UPDATE pairing_window SET attempts = ? WHERE id = 1",
                        (attempts,),
                    )
                    detail = "wrong code"
                    error = "Wrong code."
                self._log(conn, "pair_refused", detail=detail, now=now)
            else:
                # Single use: the window closes the moment it is used.
                conn.execute("DELETE FROM pairing_window")
                token = DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(32)
                device_id = uuid.uuid4().hex[:12]
                conn.execute(
                    "INSERT INTO devices(device_id, name, token_hash, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (device_id, name, _hash(token), now),
                )
                self._log(conn, "paired", device_id=device_id, detail=name, now=now)
        if error is not None:
            raise PairingError(error)
        device = Device(device_id, name, now, None, False)
        return PairedDevice(device=device, token=token)

    # -- auth ---------------------------------------------------------------

    def authenticate(self, token: str, *, now: float | None = None) -> Device | None:
        """The live device this token belongs to, or None."""
        if not token or not token.startswith(DEVICE_TOKEN_PREFIX):
            return None
        now = time.time() if now is None else now
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM devices WHERE token_hash = ? AND revoked = 0",
                (_hash(token),),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
                (now, row["device_id"]),
            )
        return Device(row["device_id"], row["name"], row["created_at"], now, False)

    # -- management ---------------------------------------------------------

    def list_devices(self, *, include_revoked: bool = False) -> list[Device]:
        query = "SELECT * FROM devices"
        if not include_revoked:
            query += " WHERE revoked = 0"
        with self._connect() as conn:
            rows = conn.execute(query + " ORDER BY created_at").fetchall()
        return [
            Device(
                r["device_id"],
                r["name"],
                r["created_at"],
                r["last_seen_at"],
                bool(r["revoked"]),
            )
            for r in rows
        ]

    def revoke(self, device_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE devices SET revoked = 1 WHERE device_id = ? AND revoked = 0",
                (device_id,),
            )
            if cur.rowcount:
                self._log(conn, "revoked", device_id=device_id)
            return bool(cur.rowcount)

    def log_event(
        self, event: str, *, device_id: str | None = None, detail: str = ""
    ) -> None:
        """Add one line to the device log (``grandpa devices log``)."""
        with self._connect() as conn:
            self._log(conn, event, device_id=device_id, detail=detail)

    def events(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT at, event, device_id, detail FROM events "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
