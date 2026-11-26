"""The desktop app's Skills, Connectors and Models & API keys pages (backend)."""

from __future__ import annotations

import pytest

from grandpa.app import manage


class MemoryStore:
    """A secret store backend that keeps values in a dict."""

    label = "test"
    secure = True

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        return self.values.pop(name, None) is not None

    def names(self):
        return list(self.values)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))
    monkeypatch.setenv("GRANDPA_MCP_CONFIG", str(tmp_path / "mcp.toml"))
    backend = MemoryStore()
    monkeypatch.setattr(
        "grandpa.security.secret_store.default_backend", lambda: backend
    )
    return backend


# --- skills -------------------------------------------------------------------------


def test_a_skill_is_a_claude_style_skill_md(tmp_path) -> None:
    result = manage.save_skill(
        "Email Polish", "Polish an email", "Make it short and kind."
    )
    assert result == {"ok": True, "name": "email-polish"}
    text = (tmp_path / "prompt-skills" / "email-polish" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert text.startswith("---\nname: email-polish\ndescription: Polish an email\n")
    listed = manage.list_skills()
    assert [s["name"] for s in listed["yours"]] == ["email-polish"]
    assert listed["yours"][0]["instructions"].strip() == "Make it short and kind."
    assert listed["builtin"]  # Grandpa's own tool skills are listed too
    assert (
        manage.skill_instructions("email-polish").strip() == "Make it short and kind."
    )
    assert manage.delete_skill("email-polish") is True
    assert manage.list_skills()["yours"] == []


def test_skill_names_cannot_escape_the_folder() -> None:
    assert manage.save_skill("../../evil", "", "x")["name"] == "evil"
    assert manage.save_skill("", "", "x")["ok"] is False
    assert manage.save_skill("ok", "", "")["ok"] is False
    assert manage.delete_skill("..") is False


def test_a_skill_is_imported_only_from_a_picked_file(tmp_path) -> None:
    source = tmp_path / "SKILL.md"
    source.write_text(
        "---\nname: code-review\ndescription: Review code\n---\nBe strict.",
        encoding="utf-8",
    )
    assert manage.import_skill(source, allowed=set())["ok"] is False
    result = manage.import_skill(source, allowed={str(source.resolve())})
    assert result["ok"] and result["name"] == "code-review"


# --- connectors ----------------------------------------------------------------------


def test_a_connector_keeps_its_key_out_of_the_file(tmp_path, _home) -> None:
    result = manage.mcp_save_server(
        "github",
        "npx -y @modelcontextprotocol/server-github",
        "search_repositories, get_issue",
        {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_secret"},
    )
    assert result == {"ok": True}
    text = (tmp_path / "mcp.toml").read_text(encoding="utf-8")
    assert "ghp_secret" not in text
    assert "secret:mcp.github.GITHUB_PERSONAL_ACCESS_TOKEN" in text
    assert _home.values["mcp.github.GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_secret"

    status = manage.mcp_status()
    server = status["servers"][0]
    assert server["command"].startswith("npx -y @modelcontextprotocol/server-github")
    assert server["allow"] == ["search_repositories", "get_issue"]
    assert server["env"] == ["GITHUB_PERSONAL_ACCESS_TOKEN"]

    # the key reaches the server's environment only when it starts
    from grandpa.mcp.servers import load_settings, server_environment

    env = server_environment(load_settings().servers["github"])
    assert env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_secret"

    assert manage.mcp_toggle_server("github", False) is True
    assert manage.mcp_status()["servers"][0]["enabled"] is False
    assert manage.mcp_remove_server("github") is True
    assert "mcp.github.GITHUB_PERSONAL_ACCESS_TOKEN" not in _home.values


def test_bad_connector_input_is_refused() -> None:
    assert manage.mcp_save_server("bad name!", "npx x", "", {})["ok"] is False
    assert manage.mcp_save_server("ok", "", "", {})["ok"] is False
    assert manage.mcp_save_server("ok", "npx x", "", {"BAD-NAME": "v"})["ok"] is False


def test_a_missing_key_stops_the_server_with_a_clear_message(tmp_path) -> None:
    (tmp_path / "mcp.toml").write_text(
        '[servers.gh]\ncommand = "npx"\nenv = { TOKEN = "secret:mcp.gh.TOKEN" }\n',
        encoding="utf-8",
    )
    from grandpa.mcp.servers import load_settings, server_environment

    with pytest.raises(RuntimeError, match="missing"):
        server_environment(load_settings().servers["gh"])


# --- models & API keys -----------------------------------------------------------------


def test_a_provider_key_goes_to_the_secret_store(tmp_path, _home) -> None:
    result = manage.provider_save("groq", "", "gsk_secret", "llama-3.3-70b-versatile")
    assert result == {"ok": True}
    text = (tmp_path / "providers.toml").read_text(encoding="utf-8")
    assert "gsk_secret" not in text and "api.groq.com" in text
    status = manage.providers_status()
    groq = status["providers"][0]
    assert groq["has_key"] is True and "api_key" not in groq  # the key never comes back

    from grandpa.engine.cloud import client_for, cloud_model_names

    assert cloud_model_names() == ["@groq/llama-3.3-70b-versatile"]
    client, name = client_for("@groq/llama-3.3-70b-versatile")
    assert name == "llama-3.3-70b-versatile"
    assert client._client.headers["authorization"] == "Bearer gsk_secret"

    assert manage.provider_remove("groq") is True
    assert "provider.groq.api_key" not in _home.values


def test_provider_addresses_must_be_https_or_this_pc() -> None:
    assert (
        manage.provider_save("mine", "http://example.com/v1", "k", "m")["ok"] is False
    )
    assert (
        manage.provider_save("mine", "http://127.0.0.1:8080/v1", "", "m")["ok"] is True
    )
    assert manage.provider_save("BAD ID", "https://x.dev/v1", "", "m")["ok"] is False
