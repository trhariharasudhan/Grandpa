"""The Odin registry lists every role, reports status honestly, and sets up
missing Ollama roles only when asked."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.intelligence import odin_registry as reg

REPO_MODELS = Path(__file__).resolve().parents[2] / "models"


class FakeOllama:
    def __init__(self, tags: set[str] | None = None, fail: set[str] | None = None):
        self.tags = set(tags or ())
        self.fail = set(fail or ())
        self.calls: list[tuple[str, ...]] = []

    def list_tags(self) -> set[str]:
        return set(self.tags)

    def create(self, name: str, modelfile: Path) -> None:
        self.calls.append(("create", name, modelfile.name))
        if name in self.fail:
            raise RuntimeError(f"create {name} failed")
        self.tags.add(name)

    def copy(self, source: str, destination: str) -> None:
        self.calls.append(("copy", source, destination))
        if destination in self.fail:
            raise RuntimeError("copy failed")
        self.tags.add(destination)

    def pull(self, name: str) -> None:
        self.calls.append(("pull", name))
        self.tags.add(name)


def _statuses(tags, **kw):
    kw.setdefault("module_available", lambda name: True)
    kw.setdefault("speech_model", lambda: "small")
    kw.setdefault("tts_backend", lambda: "pyttsx3")
    return {s.role.role: s for s in reg.role_statuses(tags, **kw)}


def test_every_role_is_listed():
    roles = {r.role for r in reg.ODIN_ROLES}
    assert roles == {
        "brain",
        "fast",
        "mini",
        "coder",
        "eyes",
        "guard",
        "memory",
        "ears",
        "voice",
    }
    assert reg.llm_roles_without_odin_row() == set()


def test_every_modelfile_role_has_a_modelfile_in_the_repo():
    for role in reg.ODIN_ROLES:
        if role.modelfile:
            assert (REPO_MODELS / role.modelfile).is_file(), role.modelfile


def test_status_installed_missing_and_fallback():
    statuses = _statuses({"grandpa-brain:latest", "nomic-embed-text"})
    assert statuses["brain"].status == reg.INSTALLED
    assert statuses["fast"].status == reg.MISSING
    assert statuses["memory"].status == reg.FALLBACK
    assert "nomic-embed-text" in statuses["memory"].detail
    assert statuses["ears"].status == reg.INSTALLED
    assert "small" in statuses["ears"].detail
    assert "pyttsx3" in statuses["voice"].detail


def test_ollama_unreachable_marks_ollama_roles_missing():
    statuses = _statuses(None)
    assert statuses["brain"].status == reg.MISSING
    assert "not reachable" in statuses["brain"].detail
    assert statuses["ears"].status == reg.INSTALLED


def test_ears_and_voice_missing_when_package_absent():
    statuses = _statuses(set(), module_available=lambda name: False)
    assert statuses["ears"].status == reg.MISSING
    assert statuses["voice"].status == reg.MISSING


def test_memory_tag_resolution_falls_back():
    assert reg.resolve_memory_embedding_tag(["nomic-embed-text:latest"]) == (
        "nomic-embed-text:latest"
    )
    assert reg.resolve_memory_embedding_tag(["grandpa-memory"]) == (
        "grandpa-memory:latest"
    )


def test_plan_covers_only_missing_ollama_roles():
    plan = reg.plan_setup(
        {"grandpa-brain:latest", "nomic-embed-text:latest"}, REPO_MODELS
    )
    by_role = {s.role: s for s in plan.steps}
    assert "brain" not in by_role
    assert by_role["fast"].action == "create"
    assert "ollama create grandpa-fast -f" in by_role["fast"].command
    assert by_role["guard"].action == "create"
    assert by_role["memory"].action == "copy"
    assert by_role["memory"].command == "ollama cp nomic-embed-text grandpa-memory"
    assert "ears" not in by_role and "voice" not in by_role


def test_plan_pulls_embedding_source_when_absent():
    plan = reg.plan_setup(set(), REPO_MODELS)
    memory = next(s for s in plan.steps if s.role == "memory")
    assert memory.action == "pull+copy"


def test_missing_modelfile_is_skipped(tmp_path):
    plan = reg.plan_setup(set(), tmp_path)
    assert all(s.action == "skip" for s in plan.steps if s.role != "memory")


def test_run_setup_creates_and_copies_and_survives_one_failure():
    client = FakeOllama({"nomic-embed-text:latest"}, fail={"grandpa-coder:latest"})
    plan = reg.plan_setup(client.list_tags(), REPO_MODELS)
    reg.run_setup(plan, client, REPO_MODELS)
    done = {s.role for s in plan.runnable if s.done}
    failed = {s.role for s in plan.runnable if not s.done}
    assert failed == {"coder"}
    assert {"brain", "fast", "mini", "eyes", "guard", "memory"} <= done
    assert ("copy", "nomic-embed-text:latest", "grandpa-memory:latest") in client.calls


def test_memory_copy_failure_reports_fallback():
    client = FakeOllama({"nomic-embed-text:latest"}, fail={"grandpa-memory:latest"})
    plan = reg.plan_setup(client.list_tags(), REPO_MODELS)
    reg.run_setup(plan, client, REPO_MODELS)
    memory = next(s for s in plan.steps if s.role == "memory")
    assert not memory.done
    assert "falling back to nomic-embed-text" in memory.detail


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeOllama({"grandpa-brain:latest"})
    monkeypatch.setattr("grandpa.cli.model._ollama_client", lambda: client)
    return client


def test_cli_models_lists_roles(fake_client):
    result = CliRunner(env={"COLUMNS": "250"}).invoke(cli, ["models"])
    assert result.exit_code == 0, result.output
    for role in ("brain", "guard", "memory", "ears", "voice"):
        assert role in result.output
    assert "installed" in result.output and "missing" in result.output


def test_cli_roles_json(fake_client):
    import json

    result = CliRunner().invoke(cli, ["models", "roles", "--json"])
    assert result.exit_code == 0, result.output
    rows = {row["role"]: row for row in json.loads(result.output)}
    assert rows["brain"]["status"] == "installed"
    assert rows["guard"]["status"] == "missing"


def test_cli_setup_is_a_dry_run_by_default(fake_client):
    result = CliRunner(env={"COLUMNS": "250"}).invoke(cli, ["models", "setup"])
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert fake_client.calls == []


def test_cli_setup_yes_runs(fake_client):
    fake_client.tags.add("nomic-embed-text:latest")
    result = CliRunner(env={"COLUMNS": "250"}).invoke(cli, ["models", "setup", "--yes"])
    assert result.exit_code == 0, result.output
    assert (
        "copy",
        "nomic-embed-text:latest",
        "grandpa-memory:latest",
    ) in fake_client.calls
    assert any(call[0] == "create" for call in fake_client.calls)


@pytest.mark.parametrize(
    ("configured", "env", "expected"),
    [
        ("", None, "http://127.0.0.1:11434"),
        ("", "0.0.0.0:11434", "http://0.0.0.0:11434"),
        ("http://192.168.1.5:11434/", "ignored:1", "http://192.168.1.5:11434"),
    ],
)
def test_models_uses_the_same_ollama_host_as_chat(
    monkeypatch, configured, env, expected
):
    """engine.ollama.host defaults to "". It used to reach "/api/tags", so
    `grandpa models` said "Ollama not reachable" while chat worked (issue on
    Captain's Vivobook, 2026-11-17)."""
    from types import SimpleNamespace

    from grandpa.cli import model as model_cmd

    config = SimpleNamespace(
        engine=SimpleNamespace(ollama=SimpleNamespace(host=configured))
    )
    monkeypatch.setattr(model_cmd, "load_config", lambda: config)
    if env is None:
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
    else:
        monkeypatch.setenv("OLLAMA_HOST", env)

    assert model_cmd._ollama_client().host == expected
