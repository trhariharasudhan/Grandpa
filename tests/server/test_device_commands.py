"""D2: commands and voice from a paired phone.

Through the real routes, middleware and action-layer loop with a scripted
model and mocked actuators: a low-risk action runs, a confirmable one is
refused and named, voice is transcribed then run, every command is logged,
and only a live device token opens these routes.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi", reason="grandpa[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.action_layer.catalogue import get
from grandpa.devices import DeviceStore
from grandpa.devices.commands import RateLimiter
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
        self.goals: list[str] = []

    def supports_tools(self, model: str) -> bool:
        return True

    def health(self) -> bool:
        return True

    def generate(self, messages, *, model, tools=None, temperature=0.0, **kwargs):
        self.goals.append(messages[-1].content)
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


class FakeSpeech:
    backend_id = "fake"

    def __init__(self, text: str):
        self.text = text
        self.received: list[tuple[bytes, str]] = []

    def transcribe(self, audio, *, format="wav", language=None):
        self.received.append((audio, format))
        return SimpleNamespace(text=self.text)


def _patch_impl(monkeypatch: pytest.MonkeyPatch, action: str) -> MagicMock:
    mock = MagicMock(return_value=_Response(f"{action} done"))
    monkeypatch.setattr(get(action).implementation, mock, raising=True)
    return mock


@pytest.fixture
def store(tmp_path):
    return DeviceStore(tmp_path / "devices.db")


def _client(store, engine, speech=None):
    app = FastAPI()
    app.state.device_store = store
    app.state.engine = engine
    app.state.model = "scripted-model"
    app.state.speech_backend = speech
    app.include_router(device_router)
    app.add_middleware(AuthMiddleware, api_key=API_KEY, device_store=store)
    return TestClient(app)


def _token(store, client) -> str:
    code = store.start_pairing().code
    resp = client.post("/v1/devices/pair", json={"code": code, "name": "Pixel"})
    return resp.json()["token"]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_phone_command_runs_a_low_risk_action(monkeypatch, store):
    volume = _patch_impl(monkeypatch, "volume_up")
    engine = ScriptedModel(
        {"content": "", "tool_calls": [_call("volume_up", {})]},
        {"content": "Turned it up."},
    )
    client = _client(store, engine)
    token = _token(store, client)

    resp = client.post(
        "/v1/devices/command", json={"text": "volume up"}, headers=_bearer(token)
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    volume.assert_called_once()
    assert body["reply"] == "Turned it up."
    assert body["actions"][0]["action"] == "volume_up"
    assert body["actions"][0]["success"] is True
    assert body["needs_pc_confirmation"] == []
    assert engine.goals[0] == "volume up"
    logged = [e["event"] for e in store.events()]
    assert "command" in logged and "command_done" in logged


def test_a_confirmable_action_is_refused_and_named(monkeypatch, store):
    shutdown = _patch_impl(monkeypatch, "system_shutdown")
    engine = ScriptedModel(
        {"content": "", "tool_calls": [_call("system_shutdown", {})]},
        {"content": "I could not shut down."},
    )
    client = _client(store, engine)
    token = _token(store, client)

    resp = client.post(
        "/v1/devices/command", json={"text": "shut down the pc"}, headers=_bearer(token)
    )

    assert resp.status_code == 200, resp.text
    shutdown.assert_not_called()
    body = resp.json()
    assert body["needs_pc_confirmation"] == ["system_shutdown"]
    assert body["actions"][0]["error"] == "confirmation_required"
    assert "need a yes on the PC" in body["reply"]


def test_voice_is_transcribed_then_run(monkeypatch, store):
    volume = _patch_impl(monkeypatch, "volume_up")
    engine = ScriptedModel(
        {"content": "", "tool_calls": [_call("volume_up", {})]},
        {"content": "Louder now."},
    )
    speech = FakeSpeech("volume up please")
    client = _client(store, engine, speech)
    token = _token(store, client)

    resp = client.post(
        "/v1/devices/voice?format=wav",
        content=b"RIFFfakeaudio",
        headers={**_bearer(token), "Content-Type": "application/octet-stream"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "volume up please"
    assert speech.received == [(b"RIFFfakeaudio", "wav")]
    assert engine.goals[0] == "volume up please"
    volume.assert_called_once()


def test_voice_without_speech_backend_is_503(store):
    client = _client(store, ScriptedModel())
    token = _token(store, client)
    resp = client.post(
        "/v1/devices/voice",
        content=b"x",
        headers={**_bearer(token), "Content-Type": "application/octet-stream"},
    )
    assert resp.status_code == 503


def test_silent_recording_runs_nothing(store):
    engine = ScriptedModel()
    client = _client(store, engine, FakeSpeech("   "))
    token = _token(store, client)
    resp = client.post(
        "/v1/devices/voice",
        content=b"x",
        headers={**_bearer(token), "Content-Type": "application/octet-stream"},
    )
    assert resp.status_code == 422
    assert engine.goals == []


@pytest.mark.parametrize("path", ["/v1/devices/command", "/v1/devices/voice"])
def test_routes_need_a_live_device_token(store, path):
    engine = ScriptedModel()
    client = _client(store, engine, FakeSpeech("hi"))
    assert client.post(path, json={"text": "hi"}).status_code == 401
    assert (
        client.post(
            path, json={"text": "hi"}, headers=_bearer("gp_dev_fake")
        ).status_code
        == 401
    )
    token = _token(store, client)
    device_id = store.list_devices()[0].device_id
    store.revoke(device_id)
    assert (
        client.post(path, json={"text": "hi"}, headers=_bearer(token)).status_code
        == 401
    )
    # The API key passes the middleware but is not a phone.
    assert (
        client.post(path, json={"text": "hi"}, headers=_bearer(API_KEY)).status_code
        == 401
    )
    assert engine.goals == []


def test_rate_limit(store):
    engine = ScriptedModel()
    client = _client(store, engine)
    client.app.state.device_rate_limiter = RateLimiter(limit=2)
    token = _token(store, client)
    codes = [
        client.post(
            "/v1/devices/command", json={"text": "hello"}, headers=_bearer(token)
        ).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_empty_and_overlong_commands_are_400(store):
    engine = ScriptedModel()
    client = _client(store, engine)
    token = _token(store, client)
    for text in ["   ", "x" * 600]:
        resp = client.post(
            "/v1/devices/command", json={"text": text}, headers=_bearer(token)
        )
        assert resp.status_code == 400
    assert engine.goals == []


def test_rate_limiter_window():
    limiter = RateLimiter(limit=1, window=60)
    assert limiter.allow("a", now=0)
    assert not limiter.allow("a", now=30)
    assert limiter.allow("b", now=30)
    assert limiter.allow("a", now=61)
