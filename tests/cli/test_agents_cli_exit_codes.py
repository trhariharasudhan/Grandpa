"""Agent CLI commands must exit non-zero when they fail.

`agents run` printed "Tick complete. Status: error" and exited 0 when its tick
failed, and nine other `grandpa agents` commands printed a red error (or
"Agent not found") and exited 0. `grandpa agent rollback` printed
"No backups found" and exited 0 when every restore failed.
"""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

import grandpa.agents as agents_package
from grandpa.agents.executor import AgentExecutor
from grandpa.agents.manager import AgentManager
from grandpa.cli import cli
from grandpa.core.events import EventBus

agent_cmd = importlib.import_module("grandpa.cli.agent_cmd")


# --------------------------------------------------------------------------
# agents run — same shape as tests/cli/test_agents_ask_tick.py
# --------------------------------------------------------------------------


@pytest.fixture
def wired(monkeypatch, tmp_path):
    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": "tick output",
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        "model": "test-model",
        "finish_reason": "stop",
    }
    executor = AgentExecutor(
        manager=manager,
        event_bus=EventBus(),
        system=SimpleNamespace(engine=engine, model="test-model"),
    )
    # See tests/cli/test_agents_ask_tick.py: force the executor's own
    # load_builtin_agents() to re-register the builtin agents.
    monkeypatch.setattr(agents_package, "_builtins_loaded", False)
    for name in agents_package._BUILTINS:
        monkeypatch.delitem(sys.modules, f"grandpa.agents.{name}", raising=False)
    monkeypatch.setattr("grandpa.agents.executor.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(agent_cmd, "_get_manager", lambda: manager)
    monkeypatch.setattr(
        agent_cmd,
        "_get_scheduler_and_executor",
        lambda system=None: (None, executor, None),
    )
    yield SimpleNamespace(manager=manager, engine=engine)
    manager.close()


def test_agents_run_reports_a_completed_tick(wired) -> None:
    agent = wired.manager.create_agent(name="probe", agent_type="simple")

    result = CliRunner().invoke(cli, ["agents", "run", agent["id"]])

    assert result.exit_code == 0, result.output
    assert "Tick complete" in result.output
    assert wired.engine.generate.called


def test_agents_run_exits_nonzero_when_the_tick_fails(wired) -> None:
    agent = wired.manager.create_agent(name="broken", agent_type="no_such_agent_type")

    result = CliRunner().invoke(cli, ["agents", "run", agent["id"]])

    assert result.exit_code != 0, result.output
    assert "Tick failed" in result.output
    assert "no_such_agent_type" in result.output
    assert "Tick complete" not in result.output


# --------------------------------------------------------------------------
# Commands that printed a red error and exited 0
# --------------------------------------------------------------------------

_MANAGER_COMMANDS = [
    ["agents", "list"],
    ["agents", "create", "--name", "probe"],
    ["agents", "info", "agent-1"],
    ["agents", "tasks", "agent-1"],
    ["agents", "pause", "agent-1"],
    ["agents", "resume", "agent-1"],
    ["agents", "delete", "agent-1"],
    ["agents", "search", "agent-1", "query"],
]


@pytest.mark.parametrize("args", _MANAGER_COMMANDS, ids=lambda a: a[1])
def test_agents_command_exits_nonzero_when_it_errors(monkeypatch, args) -> None:
    def _unavailable():
        raise RuntimeError("agent database unavailable")

    monkeypatch.setattr(agent_cmd, "_get_manager", _unavailable)

    result = CliRunner().invoke(cli, args)

    assert result.exit_code != 0, result.output
    assert "agent database unavailable" in result.output


def test_agents_templates_exits_nonzero_when_it_errors(monkeypatch) -> None:
    def _unreadable():
        raise RuntimeError("templates unreadable")

    monkeypatch.setattr(AgentManager, "list_templates", staticmethod(_unreadable))

    result = CliRunner().invoke(cli, ["agents", "templates"])

    assert result.exit_code != 0, result.output
    assert "templates unreadable" in result.output


@pytest.mark.parametrize(
    "args",
    [["agents", "info", "missing"], ["agents", "search", "missing", "query"]],
    ids=lambda a: a[1],
)
def test_agents_command_exits_nonzero_for_an_unknown_agent(
    monkeypatch, tmp_path, args
) -> None:
    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    monkeypatch.setattr(agent_cmd, "_get_manager", lambda: manager)
    try:
        result = CliRunner().invoke(cli, args)
    finally:
        manager.close()

    assert result.exit_code != 0, result.output
    assert "Agent not found" in result.output


# --------------------------------------------------------------------------
# grandpa agent rollback
# --------------------------------------------------------------------------


def test_agent_rollback_exits_nonzero_when_a_restore_fails(
    monkeypatch, tmp_path
) -> None:
    (tmp_path / "module.py.bak").write_text("backup", encoding="utf-8")

    def _locked(*_args, **_kwargs):
        raise PermissionError("file is locked")

    monkeypatch.setattr("shutil.copy2", _locked)

    result = CliRunner().invoke(
        cli, ["agent", "rollback", "exec-1", "--workspace", str(tmp_path)]
    )

    assert result.exit_code != 0, result.output
    assert "file is locked" in result.output
    assert "No backups found" not in result.output
