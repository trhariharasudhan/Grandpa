"""D4: remote actions wait for a yes at the PC, and every step is logged.

A phone asks for something that needs confirmation: nothing runs, the exact
action and arguments are kept as a pending request, and only someone at the
PC (``grandpa devices approve``, with chat's own y/N prompt) can run it. The
phone can see its requests but has no way to approve one.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi", reason="grandpa[server] not installed")

from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.action_layer.catalogue import get
from grandpa.cli import devices_cmd
from grandpa.devices import DeviceStore, approvals
from grandpa.server.auth_middleware import AuthMiddleware
from grandpa.server.device_routes import router as device_router

API_KEY = "gp_sk_test_master"


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    return tmp_path / "actions.jsonl"


def _call(name: str, arguments: dict) -> dict:
    return {"id": "call_0", "name": name, "arguments": json.dumps(arguments)}


class ScriptedModel:
    engine_id = "scripted"
    supports_streaming = False

    def __init__(self, *turns):
        self.turns = list(turns)

    def supports_tools(self, model: str) -> bool:
        return True

    def health(self) -> bool:
        return True

    def generate(self, messages, *, model, tools=None, temperature=0.0, **kwargs):
        if not self.turns:
            return {"content": "Nothing further."}
        return self.turns.pop(0)


class _Response:
    def __init__(self, message: str = "done"):
        self.ok = True
        self.status = "completed"
        self.message = message
        self.evidence = {}
        self.error = None


def _patch_impl(monkeypatch: pytest.MonkeyPatch, action: str) -> MagicMock:
    mock = MagicMock(return_value=_Response(f"{action} done"))
    monkeypatch.setattr(get(action).implementation, mock, raising=True)
    return mock


@pytest.fixture
def store(tmp_path, monkeypatch):
    db = tmp_path / "devices.db"
    monkeypatch.setattr(devices_cmd, "DeviceStore", lambda: DeviceStore(db))
    return DeviceStore(db)


def _client(store, engine):
    app = FastAPI()
    app.state.device_store = store
    app.state.engine = engine
    app.state.model = "scripted-model"
    app.include_router(device_router)
    app.add_middleware(AuthMiddleware, api_key=API_KEY, device_store=store)
    return TestClient(app)


def _token(store, client) -> str:
    code = store.start_pairing().code
    resp = client.post("/v1/devices/pair", json={"code": code, "name": "Pixel"})
    return resp.json()["token"]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _ask_to_kill(monkeypatch, store):
    """The phone asks to end notepad.exe; returns (client, token, kill mock, body)."""
    kill = _patch_impl(monkeypatch, "process_kill")
    engine = ScriptedModel(
        {"content": "", "tool_calls": [_call("process_kill", {"name": "notepad.exe"})]},
        {"content": "I need a yes for that."},
    )
    client = _client(store, engine)
    token = _token(store, client)
    resp = client.post(
        "/v1/devices/command", json={"text": "close notepad"}, headers=_bearer(token)
    )
    assert resp.status_code == 200, resp.text
    return client, token, kill, resp.json()


def _approve(answer: str | None, monkeypatch, request_id: int):
    monkeypatch.setattr(
        "grandpa.cli._tty.stdin_is_interactive", lambda: answer is not None
    )
    return CliRunner().invoke(
        devices_cmd.devices, ["approve", str(request_id)], input=answer or ""
    )


def test_a_confirmable_action_waits_with_its_exact_arguments(monkeypatch, store):
    client, token, kill, body = _ask_to_kill(monkeypatch, store)

    kill.assert_not_called()
    assert body["needs_pc_confirmation"] == ["process_kill"]
    [waiting] = body["pending"]
    assert waiting["action"] == "process_kill"
    assert waiting["parameters"] == {"name": "notepad.exe"}
    assert f"#{waiting['id']} process_kill" in body["reply"]
    assert "grandpa devices approve" in body["reply"]

    seen = client.get("/v1/devices/pending", headers=_bearer(token)).json()
    assert seen["pending"][0]["status"] == "pending"
    assert seen["pending"][0]["command"] == "close notepad"
    assert "action_queued" in [e["event"] for e in store.events()]


def test_approve_at_the_pc_asks_then_runs_once(monkeypatch, store):
    client, token, kill, body = _ask_to_kill(monkeypatch, store)
    request_id = body["pending"][0]["id"]

    listed = CliRunner().invoke(devices_cmd.devices, ["pending"])
    assert f"#{request_id}  process_kill name='notepad.exe'" in listed.output
    assert "from Pixel" in listed.output

    result = _approve("y\n", monkeypatch, request_id)
    assert result.exit_code == 0, result.output
    assert "Run it?" in result.output
    kill.assert_called_once()

    again = _approve("y\n", monkeypatch, request_id)
    assert again.exit_code != 0 and "done, not waiting" in again.output
    kill.assert_called_once()

    status = client.get("/v1/devices/pending", headers=_bearer(token)).json()
    assert status["pending"][0]["status"] == "done"
    notes = client.get("/v1/devices/notifications", headers=_bearer(token)).json()
    assert notes["notifications"][-1]["kind"] == "action"
    assert "process_kill: done" in notes["notifications"][-1]["title"]
    events = [e["event"] for e in store.events()]
    assert "action_approved" in events and "action_done" in events


def test_saying_no_at_the_pc_runs_nothing(monkeypatch, store):
    client, token, kill, body = _ask_to_kill(monkeypatch, store)
    result = _approve("n\n", monkeypatch, body["pending"][0]["id"])
    assert result.exit_code != 0
    kill.assert_not_called()
    status = client.get("/v1/devices/pending", headers=_bearer(token)).json()
    assert status["pending"][0]["status"] == "failed"


def test_no_terminal_means_no_yes(monkeypatch, store):
    """Approve run from a script (no console) is refused by the executor."""
    _client_, _token_, kill, body = _ask_to_kill(monkeypatch, store)
    result = _approve(None, monkeypatch, body["pending"][0]["id"])
    assert result.exit_code != 0
    kill.assert_not_called()


def test_deny_drops_it_and_tells_the_phone(monkeypatch, store):
    client, token, kill, body = _ask_to_kill(monkeypatch, store)
    request_id = body["pending"][0]["id"]
    result = CliRunner().invoke(devices_cmd.devices, ["deny", str(request_id)])
    assert result.exit_code == 0, result.output
    assert _approve("y\n", monkeypatch, request_id).exit_code != 0
    kill.assert_not_called()
    notes = client.get("/v1/devices/notifications", headers=_bearer(token)).json()
    assert "not done" in notes["notifications"][-1]["title"]
    assert "action_denied" in [e["event"] for e in store.events()]


def test_an_expired_request_cannot_be_approved(monkeypatch, store):
    _c, _t, kill, body = _ask_to_kill(monkeypatch, store)
    request_id = body["pending"][0]["id"]
    later = approvals.time.time() + approvals.PENDING_TTL_SECONDS + 1
    with pytest.raises(approvals.ApprovalError, match="expired"):
        approvals.claim(store, request_id, now=later)
    kill.assert_not_called()
    assert "action_expired" in [e["event"] for e in store.events()]


def test_a_revoked_phones_request_cannot_be_approved(monkeypatch, store):
    _c, _t, kill, body = _ask_to_kill(monkeypatch, store)
    store.revoke(store.list_devices()[0].device_id)
    result = _approve("y\n", monkeypatch, body["pending"][0]["id"])
    assert result.exit_code != 0 and "revoked" in result.output
    kill.assert_not_called()


def test_the_phone_has_no_way_to_approve(monkeypatch, store):
    client, token, kill, body = _ask_to_kill(monkeypatch, store)
    request_id = body["pending"][0]["id"]
    for path in (
        "/v1/devices/pending",
        f"/v1/devices/pending/{request_id}",
        f"/v1/devices/pending/{request_id}/approve",
        "/v1/devices/approve",
    ):
        resp = client.post(path, json={"id": request_id}, headers=_bearer(token))
        assert resp.status_code in (401, 403, 404, 405), (path, resp.status_code)
    kill.assert_not_called()
    assert approvals.list_pending(store)[0].status == "pending"


def test_pending_needs_a_live_device_token(store):
    client = _client(store, ScriptedModel())
    assert client.get("/v1/devices/pending").status_code == 401
    assert (
        client.get("/v1/devices/pending", headers=_bearer("gp_dev_fake")).status_code
        == 401
    )


def test_a_phone_sees_only_its_own_requests(store):
    first = store.complete_pairing(store.start_pairing().code, "A").device.device_id
    second = store.complete_pairing(store.start_pairing().code, "B").device.device_id
    approvals.queue(
        store, device_id=first, action="system_shutdown", parameters={}, command="x"
    )
    assert approvals.list_pending(store, device_id=second) == []
    assert len(approvals.list_pending(store, device_id=first)) == 1


def test_too_many_waiting_expires_the_oldest(store):
    device = store.complete_pairing(store.start_pairing().code, "A").device.device_id
    ids = [
        approvals.queue(
            store,
            device_id=device,
            action="system_shutdown",
            parameters={},
            command="x",
        )
        for _ in range(approvals.MAX_PENDING_PER_DEVICE + 1)
    ]
    waiting = [p.id for p in approvals.list_pending(store, device_id=device)]
    assert len(waiting) == approvals.MAX_PENDING_PER_DEVICE
    assert ids[0] not in waiting and ids[-1] in waiting
