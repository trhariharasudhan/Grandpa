"""G1: external MCP servers reach Grandpa only through the action layer's gate."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from grandpa.action_layer import catalogue
from grandpa.action_layer.catalogue import Binding, Confirmation
from grandpa.action_layer.executor import (
    CONFIRMATION_DECLINED,
    CONFIRMATION_REQUIRED,
    UNKNOWN_ACTION,
    execute,
)
from grandpa.action_layer.model import ActionRequest, Origin, RiskLevel
from grandpa.mcp import servers
from grandpa.mcp.protocol import MCPResponse
from grandpa.mcp.servers import MCPHub, parse_settings
from tests.mcp.fake_stdio_server import TOOLS

FAKE_SERVER = str(Path(__file__).with_name("fake_stdio_server.py"))


class FakeTransport:
    """Answers like the fake server, in-process, and records tool calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def send(self, request):
        if request.method == "initialize":
            result = {"capabilities": {}, "serverInfo": {"name": "fake"}}
        elif request.method == "tools/list":
            result = {"tools": TOOLS}
        elif request.method == "tools/call":
            name = request.params["name"]
            args = request.params.get("arguments", {})
            self.calls.append((name, args))
            if name == "fail":
                result = {
                    "content": [{"type": "text", "text": "nope"}],
                    "isError": True,
                }
            else:
                result = {
                    "content": [{"type": "text", "text": f"{name}:{args.get('text')}"}]
                }
        else:
            return MCPResponse.error_response(request.id, -32601, "no")
        return MCPResponse(result=result, id=request.id)

    def send_notification(self, request) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def _settings(allow=("echo", "fail"), **extra):
    table = {"command": "fake", "allow": list(allow), **extra}
    return parse_settings({"servers": {"fake": table}}, Path("mcp.toml"))


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("GRANDPA_MCP_OFF", raising=False)
    return tmp_path


@pytest.fixture
def fake(runtime):
    transport = FakeTransport()
    hub = MCPHub(_settings(), transport_factory=lambda _server: transport)
    servers.reset_hub(hub)
    yield transport
    servers.reset_hub(None)


def _request(action, **parameters):
    spec = catalogue.get(action)
    return ActionRequest(
        action=action,
        parameters=parameters,
        origin=Origin.MODEL,
        risk=spec.risk,
        requires_confirmation=spec.requires_confirmation,
    )


# --- config --------------------------------------------------------------------


def test_parse_settings_reads_a_server():
    settings = _settings(timeout=5, args=["-y", "pkg"])
    server = settings.servers["fake"]
    assert server.command == ("fake", "-y", "pkg")
    assert server.timeout == 5.0
    assert server.allows("echo") and not server.allows("secret")
    assert settings.problems == ()


def test_missing_allow_list_allows_nothing():
    settings = parse_settings({"servers": {"s": {"command": "x"}}})
    assert settings.servers["s"].allow == ()
    assert not settings.servers["s"].allows("anything")


@pytest.mark.parametrize(
    "table, problem",
    [
        ({}, "'command' is required"),
        ({"command": "x", "timeout": 0}, "'timeout'"),
        ({"command": "x", "allow": "*", "args": "oops"}, None),
        ({"command": "x", "args": [1]}, "'args'"),
        ({"command": "x", "enabled": "yes"}, "'enabled'"),
    ],
)
def test_bad_server_tables_are_skipped(table, problem):
    settings = parse_settings({"servers": {"s": table}})
    if problem is None:
        assert "s" in settings.servers  # a single string is a one-item list
    else:
        assert "s" not in settings.servers
        assert any(problem in p for p in settings.problems)


def test_server_names_cannot_contain_the_separator():
    settings = parse_settings({"servers": {"a__b": {"command": "x"}}})
    assert settings.servers == {}


def test_load_settings_missing_file_is_empty(tmp_path):
    settings = servers.load_settings(tmp_path / "none.toml")
    assert settings.enabled and settings.servers == {}


def test_unreadable_file_turns_mcp_off(tmp_path):
    path = tmp_path / "mcp.toml"
    path.write_text("this is = = not toml", encoding="utf-8")
    settings = servers.load_settings(path)
    assert not settings.enabled and settings.problems


# --- the catalogue and the gate --------------------------------------------------


def test_allowed_tool_is_a_high_risk_confirmed_action(fake):
    spec = catalogue.get("mcp__fake__echo")
    assert spec.risk is RiskLevel.HIGH
    assert spec.confirmation is Confirmation.LAYER
    assert spec.requires_confirmation
    assert spec.binding is Binding.MCP_TOOL
    # A list type ("string" or null) is dropped rather than crashing validation.
    assert "type" not in spec.parameters["properties"]["note"]


@pytest.mark.parametrize(
    "name", ["mcp__fake__secret", "mcp__fake__missing", "mcp__other__echo", "mcp__x"]
)
def test_not_allowed_or_unknown_is_not_an_action(fake, name):
    with pytest.raises(KeyError):
        catalogue.get(name)
    result = execute(ActionRequest(action=name, origin=Origin.MODEL))
    assert result.error == UNKNOWN_ACTION
    assert fake.calls == []


def test_no_confirm_callback_means_nothing_runs(fake):
    result = execute(_request("mcp__fake__echo", text="hi"))
    assert result.error == CONFIRMATION_REQUIRED
    assert fake.calls == []


def test_declined_means_nothing_runs(fake):
    result = execute(
        _request("mcp__fake__echo", text="hi"), confirm_callback=lambda *a: False
    )
    assert result.error == CONFIRMATION_DECLINED
    assert fake.calls == []


def test_confirmed_call_reaches_the_server_and_is_audited(fake, runtime):
    asked = []
    result = execute(
        _request("mcp__fake__echo", text="hi"),
        confirm_callback=lambda *a: asked.append(a) or True,
    )
    assert result.success, result
    assert result.message == "echo:hi"
    assert result.data["untrusted"] is True
    assert fake.calls == [("echo", {"text": "hi"})]
    assert asked[0][0] == "mcp__fake__echo"
    assert asked[0][2] is RiskLevel.HIGH
    log = (runtime / "audit.jsonl").read_text(encoding="utf-8")
    assert '"action_type": "mcp__fake__echo"' in log
    assert '"confirmed": true' in log


def test_unknown_parameter_is_refused_before_asking(fake):
    asked = []
    result = execute(
        _request("mcp__fake__echo", text="hi", extra=1),
        confirm_callback=lambda *a: asked.append(a) or True,
    )
    assert result.error == "invalid_parameters"
    assert asked == [] and fake.calls == []


def test_tool_error_is_a_failure(fake):
    result = execute(_request("mcp__fake__fail"), confirm_callback=lambda *a: True)
    assert not result.success
    assert result.error == "mcp_tool_error"


def test_a_caller_cannot_make_an_mcp_action_unconfirmed(fake):
    # requires_confirmation=False on the request does not loosen the catalogue.
    request = ActionRequest(
        action="mcp__fake__echo",
        parameters={"text": "hi"},
        origin=Origin.MODEL,
        risk=RiskLevel.LOW,
        requires_confirmation=False,
    )
    assert execute(request).error == CONFIRMATION_REQUIRED
    assert fake.calls == []


# --- the kill switch -------------------------------------------------------------


def test_env_kill_switch(fake, monkeypatch):
    catalogue.get("mcp__fake__echo")
    monkeypatch.setenv("GRANDPA_MCP_OFF", "1")
    with pytest.raises(KeyError):
        catalogue.get("mcp__fake__echo")
    # Even a spec fetched before the switch cannot run after it.
    result = servers.call_action("mcp__fake__echo", {"text": "hi"})
    assert result.error == "mcp_off"
    assert fake.calls == []


def test_off_command_stops_servers_and_on_restores(fake):
    catalogue.get("mcp__fake__echo")
    servers.set_off(True)
    assert fake.closed
    with pytest.raises(KeyError):
        catalogue.get("mcp__fake__echo")
    servers.set_off(False)
    assert catalogue.get("mcp__fake__echo").name == "mcp__fake__echo"


def test_enabled_false_in_the_file(runtime):
    settings = parse_settings(
        {"enabled": False, "servers": {"fake": {"command": "x", "allow": ["*"]}}}
    )
    hub = MCPHub(settings, transport_factory=lambda _s: FakeTransport())
    with pytest.raises(KeyError):
        hub.spec_for("mcp__fake__echo")


def test_disabled_server(runtime):
    hub = MCPHub(_settings(enabled=False), transport_factory=lambda _s: FakeTransport())
    with pytest.raises(KeyError):
        hub.spec_for("mcp__fake__echo")


# --- workflows can use them, and still ask ---------------------------------------


def test_workflow_step_on_an_mcp_tool_still_asks(fake, tmp_path):
    from grandpa.workflow.engine import WorkflowEngine
    from grandpa.workflow.loader import load_yaml_workflow

    path = tmp_path / "say.yaml"
    path.write_text(
        "name: say\nsteps:\n  - id: echo\n    action: mcp__fake__echo\n"
        "    params:\n      text: hello\n",
        encoding="utf-8",
    )
    graph = load_yaml_workflow(path)
    refused = WorkflowEngine().run(graph, dry_run=False, confirm_callback=None)
    assert not refused.success and fake.calls == []
    done = WorkflowEngine().run(graph, dry_run=False, confirm_callback=lambda *a: True)
    assert done.success
    assert fake.calls == [("echo", {"text": "hello"})]


# --- a real stdio server -----------------------------------------------------------


def _stdio_settings(tmp_path, timeout=10):
    path = tmp_path / "mcp.toml"
    command = sys.executable.replace("\\", "/")
    script = FAKE_SERVER.replace("\\", "/")
    path.write_text(
        f'[servers.fake]\ncommand = "{command}"\nargs = ["{script}"]\n'
        f'allow = ["echo", "slow"]\ntimeout = {timeout}\n',
        encoding="utf-8",
    )
    return path


@pytest.mark.real_actions(
    reason="starts tests/mcp/fake_stdio_server.py, which only echoes JSON"
)
def test_real_stdio_server_skips_noise_and_answers(tmp_path, runtime, monkeypatch):
    monkeypatch.setenv("GRANDPA_MCP_CONFIG", str(_stdio_settings(tmp_path)))
    hub = MCPHub()
    servers.reset_hub(hub)
    try:
        report = hub.test("fake")
        assert report["tools"] == ["echo", "fail", "secret", "slow"]
        assert report["allowed"] == ["echo", "slow"]
        result = execute(
            _request("mcp__fake__echo", text="hi"), confirm_callback=lambda *a: True
        )
        assert result.success and result.message == "echo:hi"
    finally:
        servers.reset_hub(None)


@pytest.mark.real_actions(
    reason="starts tests/mcp/fake_stdio_server.py, which only sleeps and echoes"
)
def test_timeout_kills_the_server_and_the_next_call_restarts(
    tmp_path, runtime, monkeypatch
):
    monkeypatch.setenv("GRANDPA_MCP_CONFIG", str(_stdio_settings(tmp_path, 1)))
    hub = MCPHub()
    servers.reset_hub(hub)
    try:
        slow = servers.call_action("mcp__fake__slow", {"seconds": 5})
        assert slow.error == "mcp_timeout"
        assert "fake" not in hub._connections
        again = servers.call_action("mcp__fake__echo", {"text": "back"})
        assert again.success and again.message == "echo:back"
    finally:
        servers.reset_hub(None)


@pytest.mark.real_actions(
    reason="starts tests/mcp/fake_stdio_server.py, which only echoes JSON"
)
def test_cli_list_test_off_on(tmp_path, runtime, monkeypatch):
    from grandpa.cli.mcp_cmd import mcp

    monkeypatch.setenv("GRANDPA_MCP_CONFIG", str(_stdio_settings(tmp_path)))
    servers.reset_hub(None)
    runner = CliRunner()
    try:
        listed = runner.invoke(mcp, ["list"])
        assert listed.exit_code == 0, listed.output
        assert "[allowed] mcp__fake__echo" in listed.output
        assert "[blocked] mcp__fake__secret" in listed.output

        tested = runner.invoke(mcp, ["test", "fake"])
        assert tested.exit_code == 0, tested.output
        assert "4 tool(s), 2 allowed" in tested.output

        # No terminal to answer on: the call is refused, not run.
        called = runner.invoke(mcp, ["call", "mcp__fake__echo", "--arg", "text=hi"])
        assert called.exit_code == 1
        assert "Nobody can answer" in called.output

        off = runner.invoke(mcp, ["off"])
        assert off.exit_code == 0 and "OFF" in off.output
        assert "MCP: OFF" in runner.invoke(mcp, ["list"]).output
        blocked = runner.invoke(mcp, ["call", "mcp__fake__echo", "--arg", "text=hi"])
        assert blocked.exit_code != 0 and "not available" in blocked.output
        assert "MCP is on." in runner.invoke(mcp, ["on"]).output
    finally:
        servers.reset_hub(None)
