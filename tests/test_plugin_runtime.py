from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.plugins import (
    disable_plugin,
    enable_plugin,
    list_plugins,
    load_enabled_plugins,
    plugin_diagnostics,
)
from grandpa.server.api_routes import plugins_router
from grandpa.skills.registry import (
    clear_skills,
    ensure_default_skills_registered,
    execute_skill,
    get_skill,
)
from grandpa.skills.registry.core import unregister_skill


@pytest.fixture()
def plugin_workspace(tmp_path, monkeypatch):
    root = tmp_path / "plugin-root"
    package = root / "sample-tools"
    package.mkdir(parents=True)
    (package / "plugin.json").write_text(
        json.dumps(
            {
                "name": "sample-tools",
                "version": "1.2.3",
                "description": "Sample safe plugin.",
                "permissions": ["diagnostics.read"],
                "skills": [
                    {
                        "name": "sample.echo",
                        "description": "Echo a safe plugin response.",
                        "category": "sample",
                        "risk_level": "LOW",
                        "approval_required": False,
                        "aliases": ["sample echo"],
                        "kind": "static_response",
                        "response": "Sample plugin skill executed.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GRANDPA_PLUGIN_PATH", str(root))
    monkeypatch.setenv("GRANDPA_PLUGIN_STATE", str(tmp_path / "plugin_state.json"))
    clear_skills()
    yield root
    clear_skills()


def test_plugin_discovery_and_skill_registration(plugin_workspace):
    plugins = list_plugins()

    assert any(item["name"] == "sample-tools" for item in plugins)
    summary = load_enabled_plugins(force=True)
    assert "sample-tools" in summary["loaded"]

    skill = get_skill("sample echo")
    assert skill.name == "sample.echo"
    result = execute_skill("sample.echo")
    assert result.ok is True
    assert result.message == "Sample plugin skill executed."


def test_plugin_enable_disable_unregisters_skill(plugin_workspace):
    load_enabled_plugins(force=True)
    assert get_skill("sample.echo").name == "sample.echo"

    disabled = disable_plugin("sample-tools")
    assert disabled["plugin"]["enabled"] is False
    with pytest.raises(KeyError):
        get_skill("sample.echo")

    enabled = enable_plugin("sample-tools")
    assert enabled["plugin"]["enabled"] is True
    assert get_skill("sample.echo").name == "sample.echo"


def test_invalid_plugin_permissions_are_rejected(tmp_path, monkeypatch):
    root = tmp_path / "plugin-root"
    package = root / "bad-tools"
    package.mkdir(parents=True)
    (package / "plugin.json").write_text(
        json.dumps(
            {
                "name": "bad-tools",
                "version": "1.0.0",
                "description": "Invalid permission plugin.",
                "permissions": ["shell.execute"],
                "skills": [
                    {
                        "name": "bad.echo",
                        "description": "Bad skill.",
                        "category": "bad",
                        "risk_level": "LOW",
                        "kind": "static_response",
                        "response": "bad",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GRANDPA_PLUGIN_PATH", str(root))
    monkeypatch.setenv("GRANDPA_PLUGIN_STATE", str(tmp_path / "plugin_state.json"))
    clear_skills()

    summary = load_enabled_plugins(force=True)

    assert "bad-tools" not in summary["loaded"]
    assert any(item["name"] == "bad-tools" for item in summary["rejected"])
    assert plugin_diagnostics()["invalid_count"] == 1


def test_plugin_api_lists_reload_and_toggles(plugin_workspace):
    app = FastAPI()
    app.include_router(plugins_router)
    client = TestClient(app)

    listed = client.get("/v1/plugins")
    assert listed.status_code == 200
    assert any(item["name"] == "sample-tools" for item in listed.json()["plugins"])

    reloaded = client.post("/v1/plugins/reload")
    assert reloaded.status_code == 200
    assert reloaded.json()["diagnostics"]["enabled_count"] >= 1

    disabled = client.post("/v1/plugins/sample-tools/disable")
    assert disabled.status_code == 200
    assert disabled.json()["plugin"]["enabled"] is False

    enabled = client.post("/v1/plugins/sample-tools/enable")
    assert enabled.status_code == 200
    assert enabled.json()["plugin"]["enabled"] is True


def test_default_skill_registration_loads_builtin_plugin(monkeypatch, tmp_path):
    monkeypatch.delenv("GRANDPA_PLUGIN_PATH", raising=False)
    monkeypatch.setenv("GRANDPA_PLUGIN_STATE", str(tmp_path / "plugin_state.json"))
    clear_skills()
    unregister_skill("plugins.diagnostics")

    ensure_default_skills_registered()

    result = execute_skill("plugins diagnostics")
    assert result.ok is True
    assert "Plugin runtime is ready" in result.message
