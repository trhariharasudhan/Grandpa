from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.agents.context import build_shared_context
from grandpa.agents.orchestrator import (
    MultiAgentTaskStore,
    get_multi_agent_task,
    list_multi_agent_tasks,
    multi_agent_diagnostics,
    orchestrate_goal,
)
from grandpa.agents.registry import (
    agent_registry_diagnostics,
    list_agents,
    select_agents_for_goal,
)
from grandpa.server.api_routes import agents_router


def test_agent_registry_contains_expected_specialists():
    agents = {agent["agent_id"]: agent for agent in list_agents()}

    assert {"research_agent", "browser_agent", "desktop_agent", "memory_agent", "coding_agent", "mobile_agent"} <= set(agents)
    assert agents["browser_agent"]["capabilities"]
    assert agent_registry_diagnostics()["approval_bypass_allowed"] is False


def test_agent_selection_for_research_goal():
    selected = [agent.agent_id for agent in select_agents_for_goal("research Python tutorials")]

    assert "memory_agent" in selected
    assert "research_agent" in selected
    assert "browser_agent" in selected


def test_shared_context_collects_local_observations(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))

    context = build_shared_context("analyze Grandpa health")

    assert context.task_id.startswith("mag_")
    assert context.planner_output["available"] is True
    assert "ranked_context" in context.memory_context
    assert "status" in context.browser_observations
    assert context.desktop_observations["available"] is True


def test_orchestrator_persists_collaboration_task(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))
    store = MultiAgentTaskStore(tmp_path / "multi_agent.db")

    task = orchestrate_goal("research Python tutorials", store=store)

    assert task.status == "completed"
    assert "research_agent" in task.participating_agents
    assert task.outputs
    assert store.get(task.task_id)["summary"] == task.summary
    assert store.events(task.task_id)


def test_task_list_and_get_helpers_use_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_MULTI_AGENT_DB", str(tmp_path / "multi_agent.db"))
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))

    task = orchestrate_goal("prepare coding environment")

    listed = list_multi_agent_tasks()
    loaded = get_multi_agent_task(task.task_id)

    assert any(item["task_id"] == task.task_id for item in listed)
    assert loaded is not None
    assert loaded["events"]


def test_multi_agent_api_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_MULTI_AGENT_DB", str(tmp_path / "multi_agent.db"))
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))
    app = FastAPI()
    app.include_router(agents_router)
    client = TestClient(app)

    diagnostics = client.get("/v1/agents/diagnostics")
    assert diagnostics.status_code == 200
    assert diagnostics.json()["ready"] is True

    response = client.post("/v1/agents/orchestrate", json={"user_request": "collect diagnostics report"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"].startswith("mag_")
    assert payload["outputs"]

    tasks = client.get("/v1/agents/tasks")
    assert tasks.status_code == 200
    assert tasks.json()["tasks"]

    detail = client.get(f"/v1/agents/tasks/{payload['task_id']}")
    assert detail.status_code == 200
    assert detail.json()["events"]


def test_multi_agent_diagnostics_are_json_serializable(tmp_path):
    diagnostics = multi_agent_diagnostics(store=MultiAgentTaskStore(tmp_path / "multi_agent.db"))

    assert diagnostics["status"] == "ready"
    json.dumps(diagnostics)
