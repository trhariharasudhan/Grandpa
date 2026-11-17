"""Notifications for paired phones (D3).

Grandpa keeps a small outbox in ``devices.db``. Something on the PC puts a
notification in (a reminder firing, or ``grandpa devices notify``), and each
paired phone asks ``GET /v1/devices/notifications?after=<last id it saw>``
for anything newer. Polling over the LAN keeps the phone side simple: no
push service, no account, nothing leaves the home network.

What keeps it private:

* A phone sees only notifications made after it was paired, so pairing a new
  phone does not hand it the old ones.
* A revoked phone's token stops working, so it stops getting them.
* Only the newest ``MAX_KEPT`` notifications are kept, and none older than
  ``MAX_AGE_SECONDS``; titles and bodies are length-capped.
* Nothing is queued while no phone is paired.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

MAX_KEPT = 200
MAX_AGE_SECONDS = 7 * 24 * 3600
MAX_TITLE_CHARS = 80
MAX_BODY_CHARS = 500
MAX_PER_REQUEST = 50

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    at    REAL NOT NULL,
    kind  TEXT NOT NULL,
    title TEXT NOT NULL,
    body  TEXT NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class PhoneNotification:
    id: int
    at: float
    kind: str
    title: str
    body: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "at": self.at,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
        }


def _clean(text: str, limit: int) -> str:
    kept = (" " if ch.isspace() else ch for ch in (text or ""))
    cleaned = " ".join("".join(ch for ch in kept if ch.isprintable()).split())
    return cleaned[:limit]


class PhoneReminderNotifier:
    """A reminder notifier that also tells paired phones.

    Wraps the PC notifier (toast, then console). The PC result is what decides
    whether the reminder counts as delivered; queueing for phones is best
    effort and never turns a delivered reminder into a failed one.
    """

    def __init__(self, inner: Any = None, store: Any = None) -> None:
        if inner is None:
            from grandpa.reminders import FirstWorkingNotifier

            inner = FirstWorkingNotifier()
        self.inner = inner
        self._store = store

    def _devices(self):
        if self._store is None:
            from grandpa.devices import DeviceStore

            self._store = DeviceStore()
        return self._store

    def notify(self, reminder: Any):
        result = self.inner.notify(reminder)
        try:
            self._devices().push_notification(
                "Reminder", getattr(reminder, "message", ""), kind="reminder"
            )
        except Exception:  # pragma: no cover - a locked or read-only devices.db
            import logging

            logging.getLogger(__name__).debug(
                "Could not queue reminder for phones", exc_info=True
            )
        return result


def push(store: Any, title: str, body: str, *, kind: str, now: float | None = None):
    """Queue one notification. Returns its id, or None when no phone is paired."""
    now = time.time() if now is None else now
    title = _clean(title, MAX_TITLE_CHARS) or "Grandpa"
    body = _clean(body, MAX_BODY_CHARS)
    kind = _clean(kind, 20) or "info"
    with store._connect() as conn:
        live = conn.execute(
            "SELECT 1 FROM devices WHERE revoked = 0 LIMIT 1"
        ).fetchone()
        if live is None:
            return None
        cur = conn.execute(
            "INSERT INTO notifications(at, kind, title, body) VALUES (?, ?, ?, ?)",
            (now, kind, title, body),
        )
        new_id = cur.lastrowid
        conn.execute("DELETE FROM notifications WHERE at < ?", (now - MAX_AGE_SECONDS,))
        conn.execute("DELETE FROM notifications WHERE id <= ?", (new_id - MAX_KEPT,))
    return new_id


def since(
    store: Any,
    device: Any,
    after: int = 0,
    *,
    limit: int = MAX_PER_REQUEST,
) -> list[PhoneNotification]:
    """Notifications newer than ``after`` that this device may see, oldest first."""
    limit = max(1, min(int(limit), MAX_PER_REQUEST))
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT id, at, kind, title, body FROM notifications "
            "WHERE id > ? AND at >= ? ORDER BY id LIMIT ?",
            (max(0, int(after)), device.created_at, limit),
        ).fetchall()
    return [
        PhoneNotification(r["id"], r["at"], r["kind"], r["title"], r["body"])
        for r in rows
    ]
