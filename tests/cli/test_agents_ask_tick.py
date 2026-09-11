"""`grandpa agents ask` must reach a real agent, and fail loudly when it cannot.

Before the fix, AgentExecutor looked agent types up in AgentRegistry without
loading the builtin agents, so every tick failed after 30s of retries while the
CLI printed "(No response from agent)" and exited 0.
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


@pytest.fixture
def wired(monkeypatch, tmp_path):
    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": "pong from the agent",
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        "model": "test-model",
        "finish_reason": "stop",
    }
    executor = AgentExecutor(
        manager=manager,
        event_bus=EventBus(),
        system=SimpleNamespace(engine=engine, model="test-model"),
    )

    # conftest's autouse fixture empties AgentRegistry before every test.
    # Builtin agents register as an import side effect, so if another test
    # already imported them, load_builtin_agents() cannot repopulate the
    # registry. Reset its flag and evict the modules so the executor's own
    # load_builtin_agents() call re-imports them, exactly as in a fresh CLI.
    monkeypatch.setattr(agents_package, "_builtins_loaded", False)
    for name in agents_package._BUILTINS:
        monkeypatch.delitem(sys.modules, f"grandpa.agents.{name}", raising=False)
    # The executor retries failed ticks after 10s and 20s; don't wait in tests.
    monkeypatch.setattr("grandpa.agents.executor.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(agent_cmd, "_get_manager", lambda: manager)
    monkeypatch.setattr(
        agent_cmd,
        "_get_scheduler_and_executor",
        lambda system=None: (None, executor, None),
    )
    yield SimpleNamespace(manager=manager, engine=engine)
    manager.close()


def test_agents_ask_reaches_a_real_agent(wired) -> None:
    agent = wired.manager.create_agent(name="probe", agent_type="simple")

    result = CliRunner().invoke(cli, ["agents", "ask", agent["id"], "ping"])

    assert result.exit_code == 0, result.output
    assert "Agent: pong from the agent" in result.output
    assert wired.engine.generate.called, "the agent never called the engine"


def test_agents_ask_exits_nonzero_when_the_tick_fails(wired) -> None:
    agent = wired.manager.create_agent(name="broken", agent_type="no_such_agent_type")

    result = CliRunner().invoke(cli, ["agents", "ask", agent["id"], "ping"])

    assert result.exit_code != 0, result.output
    assert "Agent tick failed" in result.output
    assert "no_such_agent_type" in result.output
    assert "(No response from agent)" not in result.output
    assert not wired.engine.generate.called
