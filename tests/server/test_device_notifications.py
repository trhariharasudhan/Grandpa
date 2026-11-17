"""D3: notifications for paired phones.

The outbox in devices.db, the route a phone polls, the reminder hook, and the
privacy rules: a phone sees only what was made after it paired, a revoked
phone sees nothing, and nothing is queued while no phone is paired.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="grandpa[server] not installed")

from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.devices import DeviceStore
from grandpa.devices import notifications as notes
from grandpa.devices.notifications import PhoneReminderNotifier
from grandpa.reminders import NotificationResult, Reminder
from grandpa.server.auth_middleware import AuthMiddleware
from grandpa.server.device_routes import router as device_router

API_KEY = "gp_sk_test_master"


@pytest.fixture
def store(tmp_path: Path) -> DeviceStore:
    return DeviceStore(tmp_path / "devices.db")


def _client(store: DeviceStore) -> TestClient:
    app = FastAPI()
    app.state.device_store = store
    app.include_router(device_router)
    app.add_middleware(AuthMiddleware, api_key=API_KEY, device_store=store)
    return TestClient(app)


def _pair(store: DeviceStore, now: float, name: str = "Pixel") -> str:
    code = store.start_pairing(now=now).code
    return store.complete_pairing(code, name, now=now).token


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_nothing_is_queued_while_no_phone_is_paired(store):
    assert store.push_notification("Grandpa", "hello") is None


def test_phone_polls_new_notifications_with_a_cursor(store):
    client = _client(store)
    token = _pair(store, now=1000.0)
    first = store.push_notification("Reminder", "Drink water", kind="reminder")
    second = store.push_notification("Grandpa", "Backup finished")

    resp = client.get("/v1/devices/notifications", headers=_bearer(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [n["id"] for n in body["notifications"]] == [first, second]
    assert body["notifications"][0] == {
        "id": first,
        "at": body["notifications"][0]["at"],
        "kind": "reminder",
        "title": "Reminder",
        "body": "Drink water",
    }
    assert body["last_id"] == second

    again = client.get(
        f"/v1/devices/notifications?after={body['last_id']}", headers=_bearer(token)
    ).json()
    assert again == {"notifications": [], "last_id": second}


def test_a_new_phone_does_not_get_old_notifications(store):
    _pair(store, now=1000.0)
    store.push_notification("Grandpa", "before the second phone", now=2000.0)
    late_token = _pair(store, now=3000.0, name="Tablet")
    store.push_notification("Grandpa", "after", now=4000.0)

    body = (
        _client(store)
        .get("/v1/devices/notifications", headers=_bearer(late_token))
        .json()
    )
    assert [n["body"] for n in body["notifications"]] == ["after"]


def test_revoked_or_missing_token_gets_nothing(store):
    client = _client(store)
    token = _pair(store, now=1000.0)
    store.push_notification("Grandpa", "secret")
    device_id = store.list_devices()[0].device_id
    store.revoke(device_id)

    assert (
        client.get("/v1/devices/notifications", headers=_bearer(token)).status_code
        == 401
    )
    assert client.get("/v1/devices/notifications").status_code == 401


def test_text_is_cleaned_and_capped(store):
    _pair(store, now=1000.0)
    store.push_notification("T" * 500, "line1\nline2\x07" + "b" * 2000)
    device = store.list_devices()[0]
    [item] = store.notifications_for(device)
    assert item.title == "T" * notes.MAX_TITLE_CHARS
    assert item.body.startswith("line1 line2b")
    assert len(item.body) == notes.MAX_BODY_CHARS


def test_outbox_keeps_only_recent_notifications(store, monkeypatch):
    monkeypatch.setattr(notes, "MAX_KEPT", 3)
    _pair(store, now=1000.0)
    ids = [store.push_notification("G", str(i), now=2000.0 + i) for i in range(5)]
    old = store.push_notification("G", "x", now=2000.0 + notes.MAX_AGE_SECONDS + 10)
    device = store.list_devices()[0]
    kept = [n.id for n in store.notifications_for(device)]
    assert kept == [old]
    assert ids[0] not in kept


def test_limit_is_bounded(store):
    _pair(store, now=1000.0)
    for i in range(notes.MAX_PER_REQUEST + 5):
        store.push_notification("G", str(i))
    device = store.list_devices()[0]
    assert len(store.notifications_for(device, limit=10_000)) == notes.MAX_PER_REQUEST


class _PcNotifier:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.seen: list[str] = []

    def notify(self, reminder):
        self.seen.append(reminder.message)
        return NotificationResult(self.ok, "sent" if self.ok else "failed", "pc")


def _reminder(message: str) -> Reminder:
    now = datetime.now(UTC)
    return Reminder(id="r1", message=message, due_at=now, created_at=now)


def test_reminder_goes_to_the_pc_and_the_phone(store):
    _pair(store, now=1000.0)
    pc = _PcNotifier()
    result = PhoneReminderNotifier(pc, store).notify(_reminder("Call Amma"))

    assert result.ok is True
    assert pc.seen == ["Call Amma"]
    [item] = store.notifications_for(store.list_devices()[0])
    assert (item.kind, item.title, item.body) == ("reminder", "Reminder", "Call Amma")


def test_pc_result_decides_delivery_even_with_a_phone(store):
    _pair(store, now=1000.0)
    result = PhoneReminderNotifier(_PcNotifier(ok=False), store).notify(_reminder("x"))
    assert result.ok is False


def test_reminder_with_no_phone_is_still_delivered_on_the_pc(store):
    pc = _PcNotifier()
    assert PhoneReminderNotifier(pc, store).notify(_reminder("x")).ok is True
    assert pc.seen == ["x"]


def test_cli_notify(monkeypatch, store):
    from grandpa.cli import devices_cmd

    monkeypatch.setattr(devices_cmd, "DeviceStore", lambda: store)
    runner = CliRunner()

    refused = runner.invoke(devices_cmd.devices, ["notify", "hello"])
    assert refused.exit_code != 0
    assert "No paired phone" in refused.output

    _pair(store, now=1000.0)
    ok = runner.invoke(devices_cmd.devices, ["notify", "hello", "--title", "Test"])
    assert ok.exit_code == 0, ok.output
    assert "Queued notification" in ok.output
    [item] = store.notifications_for(store.list_devices()[0])
    assert (item.title, item.body, item.kind) == ("Test", "hello", "manual")
