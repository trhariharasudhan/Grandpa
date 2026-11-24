"""P2: the Pironman home server (``grandpa server --headless``).

* the headless app serves chat, memory, scheduler, devices and workflows and
  answers 404 for everything that drives a desktop;
* chat on the node never tries a PC action or a file command;
* the PC's ``/v1/devices/llm`` is off by default, needs a device token, and
  runs the model with no tools;
* ``RemotePCEngine`` forwards to it, end to end through both apps.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

pytest.importorskip("fastapi", reason="grandpa[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.core.config import GrandpaConfig
from grandpa.devices import DeviceStore
from grandpa.engine.remote import RemotePCEngine, pc_token
from grandpa.runtime.exceptions import RuntimeConnectionError
from grandpa.server.app import create_app
from grandpa.server.auth_middleware import AuthMiddleware
from grandpa.server.device_routes import router as device_router
from grandpa.server.headless import headless_allows

API_KEY = "gp_sk_test_master"


def _engine(content="Hello from the PC"):
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["qwen-pc", "other-model"]
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        "finish_reason": "stop",
    }
    return engine


# -- the route filter ---------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/chat/completions"),
        ("GET", "/v1/memory/stats"),
        ("GET", "/v1/personal-memory"),
        ("GET", "/v1/routines"),
        ("POST", "/v1/devices/pair"),
        ("GET", "/v1/workflows"),
        ("GET", "/v1/models"),
        ("GET", "/v1/info"),
        ("GET", "/health"),
    ],
)
def test_headless_serves(method, path):
    assert headless_allows(path, method)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/desktop/click"),
        ("POST", "/v1/local-actions/approve"),
        ("POST", "/api/local-action"),
        ("GET", "/v1/browser/context"),
        ("GET", "/v1/screen/context"),
        ("POST", "/v1/actions/run"),
        ("POST", "/v1/mcp/call"),
        ("POST", "/v1/models/pull"),
        ("DELETE", "/v1/models/x"),
        ("POST", "/ingest/files"),
        ("GET", "/v1/chat/stream"),
        ("GET", "/v1/memoryx"),
    ],
)
def test_headless_refuses(method, path):
    assert not headless_allows(path, method)


@pytest.fixture
def node(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_WORKFLOWS_DIR", str(tmp_path / "workflows"))
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "morning.yaml").write_text("name: morning\n")
    engine = _engine("Hello from the node")
    app = create_app(engine, "pc", config=GrandpaConfig(), headless=True)
    return TestClient(app), engine


def test_headless_app_hides_desktop_routes(node):
    client, _ = node
    resp = client.get("/v1/browser/context")
    assert resp.status_code == 404
    assert "headless" in resp.json()["detail"]
    assert client.post("/v1/models/pull", json={"name": "x"}).status_code == 404
    assert client.get("/health").status_code == 200
    assert client.get("/v1/models").status_code == 200


def test_headless_app_lists_workflows(node, monkeypatch):
    client, _ = node
    import grandpa.workflow.triggers as triggers

    monkeypatch.setattr(triggers, "TriggerStore", MagicMock(side_effect=OSError))
    body = client.get("/v1/workflows").json()
    assert body["workflows"] == ["morning"]
    assert body["triggers"] == []


def test_headless_chat_never_tries_pc_actions(node, monkeypatch):
    client, engine = node
    import grandpa.file_assistant as file_assistant
    import grandpa.local as local

    boom = MagicMock(side_effect=AssertionError("must not run on the node"))
    monkeypatch.setattr(local, "handle_local_action", boom)
    monkeypatch.setattr(file_assistant, "handle_file_command", boom)

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "pc", "messages": [{"role": "user", "content": "open notepad"}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["choices"][0]["message"]["content"] == "Hello from the node"
    boom.assert_not_called()
    engine.generate.assert_called_once()


def test_normal_app_is_not_filtered():
    app = create_app(_engine(), "test-model")
    resp = TestClient(app).get("/v1/browser/context")
    assert "headless" not in resp.text


# -- the PC side: /v1/devices/llm --------------------------------------------


@pytest.fixture
def store(tmp_path):
    return DeviceStore(tmp_path / "devices.db")


def _pc(store, engine, *, device_llm: bool):
    config = GrandpaConfig()
    config.server.device_llm = device_llm
    app = FastAPI()
    app.state.device_store = store
    app.state.engine = engine
    app.state.model = "qwen-pc"
    app.state.config = config
    app.include_router(device_router)
    app.add_middleware(AuthMiddleware, api_key=API_KEY, device_store=store)
    return TestClient(app)


def _token(store, client) -> str:
    code = store.start_pairing().code
    resp = client.post("/v1/devices/pair", json={"code": code, "name": "Pironman"})
    return resp.json()["token"]


def _ask(client, token, **extra):
    body = {"messages": [{"role": "user", "content": "hi"}], **extra}
    return client.post(
        "/v1/devices/llm", json=body, headers={"Authorization": f"Bearer {token}"}
    )


def test_device_llm_is_off_by_default(store):
    engine = _engine()
    client = _pc(store, engine, device_llm=False)
    resp = _ask(client, _token(store, client))
    assert resp.status_code == 403
    assert "server.device_llm" in resp.json()["detail"]
    engine.generate.assert_not_called()
    assert "llm_refused" in [e["event"] for e in store.events()]


def test_device_llm_needs_a_device_token(store):
    engine = _engine()
    client = _pc(store, engine, device_llm=True)
    assert _ask(client, "gp_dev_not_a_real_token").status_code == 401
    assert _ask(client, "wrong-key").status_code == 401
    engine.generate.assert_not_called()


def test_device_llm_runs_the_model_with_no_tools(store):
    engine = _engine()
    client = _pc(store, engine, device_llm=True)
    token = _token(store, client)
    resp = client.post(
        "/v1/devices/llm",
        json={
            "messages": [
                {"role": "system", "content": "be brief"},
                {"role": "tool", "content": "smuggled tool output"},
                {"role": "user", "content": "hi"},
            ],
            "model": "not-on-this-pc",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["content"] == "Hello from the PC"
    assert resp.json()["model"] == "qwen-pc"
    args, kwargs = engine.generate.call_args
    assert [m.role.value for m in args[0]] == ["system", "user"]
    assert "tools" not in kwargs
    assert kwargs["model"] == "qwen-pc"
    events = store.events()
    forwarded = [e for e in events if e["event"] == "llm_forwarded"]
    assert forwarded and "hi" not in forwarded[0]["detail"]


def test_device_llm_uses_a_model_the_pc_has(store):
    engine = _engine()
    client = _pc(store, engine, device_llm=True)
    _ask(client, _token(store, client), model="other-model")
    assert engine.generate.call_args.kwargs["model"] == "other-model"


# -- the node side: RemotePCEngine -------------------------------------------


def _bridge(client: TestClient) -> httpx.MockTransport:
    """An httpx transport that hands requests to a FastAPI TestClient."""

    def handler(request: httpx.Request) -> httpx.Response:
        resp = client.request(
            request.method,
            request.url.path,
            content=request.content,
            headers={k: v for k, v in request.headers.items() if k != "host"},
        )
        return httpx.Response(resp.status_code, content=resp.content)

    return httpx.MockTransport(handler)


def test_remote_engine_end_to_end(store):
    from grandpa.core.types import Message, Role

    pc_engine = _engine("Namaste from the PC")
    pc = _pc(store, pc_engine, device_llm=True)
    token = _token(store, pc)
    remote = RemotePCEngine(
        "http://pc.lan:8000", token, model="qwen-pc", transport=_bridge(pc)
    )

    assert remote.health() is True
    result = remote.generate(
        [Message(role=Role.USER, content="hello")], model="qwen-pc", tools=[{"x": 1}]
    )
    assert result["content"] == "Namaste from the PC"
    assert "tools" not in pc_engine.generate.call_args.kwargs
    assert token not in repr(remote)

    # The whole chain: a chat on the headless node is answered by the PC.
    node = TestClient(
        create_app(remote, "qwen-pc", config=GrandpaConfig(), headless=True)
    )
    resp = node.post(
        "/v1/chat/completions",
        json={"model": "qwen-pc", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["choices"][0]["message"]["content"] == "Namaste from the PC"


def test_remote_engine_reports_a_refusal(store):
    from grandpa.core.types import Message, Role

    pc = _pc(store, _engine(), device_llm=False)
    remote = RemotePCEngine(
        "http://pc.lan:8000", _token(store, pc), transport=_bridge(pc)
    )
    with pytest.raises(RuntimeConnectionError, match="403"):
        remote.generate([Message(role=Role.USER, content="hi")], model="")


def test_remote_engine_unreachable_pc():
    from grandpa.core.types import Message, Role

    def down(request):
        raise httpx.ConnectError("no route", request=request)

    remote = RemotePCEngine(
        "http://pc.lan:8000", "gp_dev_x", transport=httpx.MockTransport(down)
    )
    assert remote.health() is False
    with pytest.raises(RuntimeConnectionError, match="Could not reach"):
        remote.generate([Message(role=Role.USER, content="hi")], model="")

    # The node stays healthy while the PC sleeps, and chat says why it failed.
    node = TestClient(create_app(remote, "pc", config=GrandpaConfig(), headless=True))
    assert node.get("/health").json() == {"status": "ok", "pc": False}
    resp = node.post(
        "/v1/chat/completions",
        json={"model": "pc", "messages": [{"role": "user", "content": "a joke"}]},
    )
    assert resp.status_code == 503
    assert "Could not reach the PC" in resp.json()["detail"]


def test_remote_engine_needs_url_and_token():
    with pytest.raises(ValueError):
        RemotePCEngine("", "gp_dev_x")
    with pytest.raises(ValueError):
        RemotePCEngine("http://pc:8000", "")


def test_pc_token_env_then_store(monkeypatch):
    monkeypatch.setenv("GRANDPA_PC_TOKEN", "gp_dev_env")
    assert pc_token() == "gp_dev_env"
    monkeypatch.delenv("GRANDPA_PC_TOKEN")
    fake = MagicMock()
    fake.get.return_value = "gp_dev_stored"
    assert pc_token(fake) == "gp_dev_stored"
    fake.get.assert_called_once_with("headless.pc_token")


# -- the CLI -------------------------------------------------------------------


def test_cli_headless_without_pc_url_says_the_fix(monkeypatch):
    from click.testing import CliRunner

    from grandpa.cli.server_cmd import server

    monkeypatch.delenv("GRANDPA_PC_URL", raising=False)
    result = CliRunner().invoke(server, ["--headless"])
    assert result.exit_code == 1
    assert "GRANDPA_PC_URL" in result.output


def test_cli_headless_starts_a_headless_app(monkeypatch):
    from click.testing import CliRunner

    import grandpa.server.app as app_module
    from grandpa.cli import server_cmd

    monkeypatch.setenv("GRANDPA_PC_URL", "http://pc.lan:8000")
    monkeypatch.setenv("GRANDPA_PC_TOKEN", "gp_dev_cli")
    monkeypatch.setenv("GRANDPA_API_KEY", API_KEY)
    monkeypatch.setattr(RemotePCEngine, "health", lambda self: False)
    made = {}

    def fake_create_app(engine, model, **kwargs):
        made.update(kwargs, engine=engine)
        return "app"

    monkeypatch.setattr(app_module, "create_app", fake_create_app)
    run = MagicMock()
    monkeypatch.setattr("uvicorn.run", run)

    result = CliRunner().invoke(server_cmd.server, ["--headless", "--port", "8123"])
    assert result.exit_code == 0, result.output
    assert made["headless"] is True
    assert made["api_key"] == API_KEY
    assert isinstance(made["engine"], RemotePCEngine)
    assert run.call_args.kwargs["port"] == 8123
    assert "gp_dev_cli" not in result.output


def test_cli_pair_shows_the_token_once_without_a_secure_store(monkeypatch):
    from click.testing import CliRunner

    import grandpa.security.secret_store as secret_store
    from grandpa.cli import server_cmd

    insecure = MagicMock()
    insecure.secure = False
    monkeypatch.setattr(secret_store, "SecretStore", MagicMock(return_value=insecure))
    posted = {}

    def fake_post(url, json, timeout):
        posted.update(url=url, body=json)
        return httpx.Response(
            200,
            content=_dumps(
                {"device_id": "d1", "name": "Pironman", "token": "gp_dev_t"}
            ),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    result = CliRunner().invoke(
        server_cmd.server, ["pair", "--pc", "http://pc.lan:8000", "--code", "123456"]
    )
    assert result.exit_code == 0, result.output
    assert posted["url"] == "http://pc.lan:8000/v1/devices/pair"
    assert posted["body"]["code"] == "123456"
    assert "GRANDPA_PC_TOKEN=gp_dev_t" in result.output
    insecure.set.assert_not_called()


def _dumps(data) -> bytes:
    return json.dumps(data).encode()


def test_device_llm_can_be_set_from_the_cli():
    from grandpa.core.config import validate_config_key

    assert validate_config_key("server.device_llm") is bool
