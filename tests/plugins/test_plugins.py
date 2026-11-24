"""G2: plugins reach Grandpa only through the manifest and the action layer's gate."""

from __future__ import annotations

import shutil
import textwrap
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
from grandpa.plugins import host as host_mod
from grandpa.plugins.host import PluginContext, PluginHost
from grandpa.plugins.manifest import (
    ManifestError,
    check_code,
    parse_manifest,
    read_manifest,
)

SAMPLE = Path(__file__).resolve().parents[2] / "plugins" / "hello"

CODE = """
from grandpa.plugins import ActionResult

CALLS = []


def echo(ctx, text):
    CALLS.append(text)
    return f"{ctx.config['prefix']}{text}"


def nested(ctx):
    return ctx.run_action("file_delete", path="C:/important.txt")


def sneaky(ctx):
    return ctx.run_action("process_kill", name="explorer.exe")


def on_end(ctx, data):
    CALLS.append(("event", data.get("workflow")))
    CALLS.append(("nested", ctx.run_action("file_delete", path="x").error))
"""


def _manifest(permissions=(), risk="low", extra=""):
    perms = ", ".join(f'"{p}"' for p in permissions)
    return textwrap.dedent(
        f"""
        [plugin]
        name = "demo"
        version = "1.0.0"
        description = "Test plugin."
        permissions = [{perms}]

        [config.prefix]
        default = "> "

        [[tools]]
        name = "echo"
        description = "Echo text."
        risk = "{risk}"
        required = ["text"]

        [tools.parameters]
        text = {{ type = "string" }}

        [[tools]]
        name = "nested"
        description = "Tries to delete a file through Grandpa."

        [[tools]]
        name = "sneaky"
        description = "Tries an action it did not declare."

        [[events]]
        on = "workflow_end"
        handler = "on_end"
        """
    ) + textwrap.dedent(extra)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("GRANDPA_PLUGINS_DIR", str(tmp_path / "plugins"))
    monkeypatch.delenv("GRANDPA_PLUGINS_OFF", raising=False)
    monkeypatch.setattr(host_mod, "user_config_path", lambda: tmp_path / "p.toml")
    (tmp_path / "plugins").mkdir()
    host = PluginHost()
    host_mod.reset_host(host)
    yield tmp_path
    host_mod.reset_host(None)


def _write(base: Path, manifest: str, code: str = CODE) -> Path:
    folder = base / "plugins" / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.toml").write_text(manifest, encoding="utf-8")
    (folder / "plugin.py").write_text(code, encoding="utf-8")
    return folder


def _request(action, **parameters):
    spec = catalogue.get(action)
    return ActionRequest(
        action=action,
        parameters=parameters,
        origin=Origin.MODEL,
        risk=spec.risk,
        requires_confirmation=spec.requires_confirmation,
    )


def _module():
    return host_mod.get_host()._module(host_mod.get_host().find("demo"))


# --- the sample ------------------------------------------------------------------


def test_sample_plugin_is_valid():
    manifest = read_manifest(SAMPLE)
    check_code(manifest)
    assert manifest.name == "hello"
    assert {t.name for t in manifest.tools} == {"greet", "greet_with_time"}
    assert manifest.allowed_actions == {"datetime_now"}


def test_sample_plugin_greets_once_enabled(sandbox):
    shutil.copytree(SAMPLE, sandbox / "plugins" / "hello")
    with pytest.raises(KeyError):
        catalogue.get("plugin__hello__greet")
    host_mod.get_host().enable("hello")
    spec = catalogue.get("plugin__hello__greet")
    assert spec.risk is RiskLevel.LOW and spec.binding is Binding.PLUGIN_TOOL
    result = execute(_request("plugin__hello__greet", name="Captain"))
    assert result.success and result.message == "Vanakkam, Captain!"


@pytest.mark.real_actions(reason="reads the system clock only; nothing is changed")
def test_sample_plugin_runs_a_declared_action(sandbox):
    shutil.copytree(SAMPLE, sandbox / "plugins" / "hello")
    host_mod.get_host().enable("hello")
    result = execute(_request("plugin__hello__greet_with_time"))
    assert result.success, result.message
    assert result.message.startswith("Vanakkam, Captain! ")


# --- enabling and pinning --------------------------------------------------------


def test_plugins_are_off_until_enabled(sandbox):
    _write(sandbox, _manifest())
    (info,) = host_mod.get_host().discover()
    assert info.state == "disabled"
    result = execute(
        ActionRequest(action="plugin__demo__echo", parameters={"text": "hi"})
    )
    assert result.error == UNKNOWN_ACTION
    assert _module_calls_never_imported()


def _module_calls_never_imported() -> bool:
    return not host_mod.get_host()._modules


def test_enabled_low_tool_runs_with_config(sandbox):
    _write(sandbox, _manifest())
    (sandbox / "p.toml").write_text('[demo]\nprefix = "# "\n', encoding="utf-8")
    host_mod.get_host().enable("demo")
    result = execute(_request("plugin__demo__echo", text="hi"))
    assert result.success and result.message == "# hi"


def test_changed_files_disable_the_plugin(sandbox):
    folder = _write(sandbox, _manifest())
    host_mod.get_host().enable("demo")
    (folder / "plugin.py").write_text(CODE + "\n# edited\n", encoding="utf-8")
    (info,) = host_mod.get_host().discover()
    assert info.state == "changed"
    with pytest.raises(KeyError, match="changed"):
        catalogue.get("plugin__demo__echo")


def test_disable_and_kill_switch(sandbox, monkeypatch):
    _write(sandbox, _manifest())
    host = host_mod.get_host()
    host.enable("demo")
    monkeypatch.setenv("GRANDPA_PLUGINS_OFF", "1")
    with pytest.raises(KeyError, match="off"):
        catalogue.get("plugin__demo__echo")
    monkeypatch.delenv("GRANDPA_PLUGINS_OFF")
    assert catalogue.get("plugin__demo__echo")
    assert host.disable("demo")
    with pytest.raises(KeyError, match="disabled"):
        catalogue.get("plugin__demo__echo")


# --- confirmation and permissions --------------------------------------------------


def test_permissions_raise_risk_and_force_asking(sandbox):
    _write(sandbox, _manifest(permissions=["network"]))
    host_mod.get_host().enable("demo")
    spec = catalogue.get("plugin__demo__echo")
    assert spec.risk is RiskLevel.MEDIUM
    assert spec.confirmation is Confirmation.LAYER

    nobody = execute(_request("plugin__demo__echo", text="a"))
    assert nobody.error == CONFIRMATION_REQUIRED
    declined = execute(
        _request("plugin__demo__echo", text="b"), confirm_callback=lambda *_: False
    )
    assert declined.error == CONFIRMATION_DECLINED
    assert _module_calls_never_imported()
    yes = execute(
        _request("plugin__demo__echo", text="c"), confirm_callback=lambda *_: True
    )
    assert yes.success
    assert _module().CALLS == ["c"]


def test_declared_risk_cannot_go_below_its_actions(sandbox):
    _write(sandbox, _manifest(permissions=["actions:file_delete"], risk="low"))
    host_mod.get_host().enable("demo")
    assert catalogue.get("plugin__demo__echo").risk is RiskLevel.HIGH


def test_undeclared_action_is_refused(sandbox):
    _write(sandbox, _manifest(permissions=["actions:file_delete"]))
    host_mod.get_host().enable("demo")
    result = execute(_request("plugin__demo__sneaky"), confirm_callback=lambda *_: True)
    assert not result.success
    assert result.error == "plugin_permission_denied"


def test_nested_action_asks_again_and_cannot_be_answered_by_the_plugin(sandbox):
    _write(sandbox, _manifest(permissions=["actions:file_delete"]))
    host_mod.get_host().enable("demo")
    asked: list[str] = []

    def answer(action, _params, _risk):
        asked.append(action)
        return action != "file_delete"  # yes to the plugin, no to the delete

    result = execute(_request("plugin__demo__nested"), confirm_callback=answer)
    assert asked == ["plugin__demo__nested", "file_delete"]
    assert result.error == CONFIRMATION_DECLINED


def test_context_is_read_only():
    manifest = parse_manifest({"plugin": {"name": "demo"}}, Path("/nowhere/demo"))
    ctx = PluginContext(manifest, {}, None)
    with pytest.raises(AttributeError):
        ctx.run_action = lambda *a, **k: None  # type: ignore[method-assign]
    assert not hasattr(ctx, "__dict__")


# --- events -------------------------------------------------------------------------


def test_event_handler_runs_and_has_nobody_to_ask(sandbox):
    from grandpa.core.events import EventType, get_event_bus

    _write(sandbox, _manifest(permissions=["actions:file_delete"]))
    host = host_mod.get_host()
    host.enable("demo")
    assert host.start_events() == 1
    get_event_bus().publish(EventType.WORKFLOW_END, {"workflow": "morning"})
    host._events.join()
    assert _module().CALLS == [
        ("event", "morning"),
        ("nested", CONFIRMATION_REQUIRED),
    ]
    host.stop_events()


# --- manifest and code checks ----------------------------------------------------------


@pytest.mark.parametrize(
    "data, problem",
    [
        ({}, "table is required"),
        ({"plugin": {"name": "other"}}, "must match its folder"),
        ({"plugin": {"name": "demo", "permissions": ["root"]}}, "unknown permission"),
        (
            {"plugin": {"name": "demo"}, "tools": [{"name": "a", "risk": "none"}]},
            "risk",
        ),
        ({"plugin": {"name": "demo"}, "tools": [{"name": "a__b"}]}, "cannot contain"),
        (
            {"plugin": {"name": "demo"}, "events": [{"on": "nope", "handler": "f"}]},
            "not a Grandpa event",
        ),
        ({"plugin": {"name": "demo", "module": "../x.py"}}, "inside the plugin"),
    ],
)
def test_bad_manifests_are_refused(data, problem):
    with pytest.raises(ManifestError, match=problem):
        parse_manifest(data, Path("/nowhere/demo"))


@pytest.mark.parametrize(
    "source, problem",
    [
        ("from grandpa.action_layer import executor\n", "only grandpa.plugins"),
        ("import subprocess\n", "'system' permission"),
        ("import os as o\no.system('x')\n", "'system' permission"),
        ("import os\ngetattr(os, 'popen')\n", "'system' permission"),
        ("import urllib.request\n", "'network' permission"),
        ("import shutil\n", "'files' permission"),
        ("import importlib\n", "not allowed"),
        ("eval('1')\n", "eval is not allowed"),
        ("def f(ctx):\n    return ctx.run_action.__closure__\n", "__closure__"),
        ("def f(ctx, n):\n    return getattr(ctx, n)\n", "literal, public"),
        ("from . import x\n", "relative imports"),
    ],
)
def test_code_check_refuses(source, problem):
    manifest = parse_manifest({"plugin": {"name": "demo"}}, Path("/nowhere/demo"))
    with pytest.raises(ManifestError, match=problem):
        check_code(manifest, source)


def test_code_check_accepts_declared_permissions():
    manifest = parse_manifest(
        {"plugin": {"name": "demo", "permissions": ["system", "network"]}},
        Path("/nowhere/demo"),
    )
    check_code(manifest, "import subprocess\nimport urllib.request\n")


def test_missing_tool_function_is_refused(sandbox):
    _write(sandbox, _manifest(), code="def echo(ctx, text):\n    return text\n")
    (info,) = host_mod.get_host().discover()
    assert info.state == "broken"
    assert "nested" in info.problem
    with pytest.raises(ManifestError):
        host_mod.get_host().enable("demo")


# --- the CLI ----------------------------------------------------------------------------


def test_cli_list_enable_call_disable(sandbox, monkeypatch):
    from grandpa.cli import plugin_cmd

    _write(sandbox, _manifest())
    runner = CliRunner()
    listed = runner.invoke(plugin_cmd.plugin, ["list"])
    assert listed.exit_code == 0, listed.output
    assert "demo 1.0.0: disabled" in listed.output
    assert "plugin__demo__echo" in listed.output

    monkeypatch.setattr(plugin_cmd, "confirm_destructive", lambda _p: None)
    nobody = runner.invoke(plugin_cmd.plugin, ["enable", "demo"])
    assert nobody.exit_code != 0 and "nothing was enabled" in nobody.output

    monkeypatch.setattr(plugin_cmd, "confirm_destructive", lambda _p: True)
    enabled = runner.invoke(plugin_cmd.plugin, ["enable", "demo"])
    assert enabled.exit_code == 0 and "is enabled" in enabled.output

    called = runner.invoke(
        plugin_cmd.plugin, ["call", "plugin__demo__echo", "--arg", "text=hi"]
    )
    assert called.exit_code == 0 and "> hi" in called.output

    disabled = runner.invoke(plugin_cmd.plugin, ["disable", "demo"])
    assert "demo is disabled" in disabled.output
