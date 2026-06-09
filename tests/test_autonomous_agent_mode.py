from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.agents.goal_mode import (
    AgentGoalStore,
    agent_goal_diagnostics,
    cancel_goal,
    continue_goal,
    create_goal,
    goal_events,
)
from grandpa.server.api_routes import agent_runtime_router


def test_goal_creation_and_safe_completion(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_AGENT_GOALS_DB", str(tmp_path / "goals.db"))

    goal = create_goal("check Grandpa readiness and report issues")

    assert goal.goal_id.startswith("goal_")
    assert goal.status in {"completed", "failed"}
    assert goal.observations
    assert goal.steps
    assert goal.actions_taken
    assert goal.result_summary


def test_approval_needed_goal_pauses(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_AGENT_GOALS_DB", str(tmp_path / "goals.db"))

    goal = create_goal("organize my downloads folder")

    assert goal.status == "waiting_approval"
    assert goal.approvals_needed
    assert any(item["risk_level"] == "MEDIUM" for item in goal.approvals_needed)


def test_browser_research_plan(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_AGENT_GOALS_DB", str(tmp_path / "goals.db"))

    goal = create_goal("research Python tutorials and summarize them")

    assert goal.status == "completed"
    skills = [step["skill"] for step in goal.steps]
    assert "browser.search_plan" in skills
    assert any(action["skill"] == "browser.search_plan" for action in goal.actions_taken)


def test_memory_writeback_and_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_AGENT_GOALS_DB", str(tmp_path / "goals.db"))
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))

    goal = create_goal("prepare my coding workspace")
    events = goal_events(goal.goal_id)

    assert goal.memory_updates
    assert any(event["phase"] == "reflecting" for event in events)


def test_cancel_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_AGENT_GOALS_DB", str(tmp_path / "goals.db"))
    store = AgentGoalStore(tmp_path / "goals.db")

    goal = create_goal("prepare my coding workspace", execute=False, store=store)
    cancelled = cancel_goal(goal.goal_id, store=store)

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert continue_goal(goal.goal_id, store=store).status == "cancelled"


def test_diagnostics(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_AGENT_GOALS_DB", str(tmp_path / "goals.db"))
    create_goal("check Grandpa readiness and report issues")

    diagnostics = agent_goal_diagnostics()

    assert diagnostics["status"] == "ready"
    assert diagnostics["goal_count"] >= 1
    assert diagnostics["local_only"] is True


def test_agent_goal_api(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_AGENT_GOALS_DB", str(tmp_path / "goals.db"))
    app = FastAPI()
    app.include_router(agent_runtime_router)
    client = TestClient(app)

    created = client.post(
        "/v1/agent/goals",
        json={"user_request": "research Python tutorials and summarize them"},
    )
    assert created.status_code == 200
    goal = created.json()
    assert goal["goal_id"].startswith("goal_")

    listed = client.get("/v1/agent/goals")
    assert listed.status_code == 200
    assert listed.json()["goals"]

    detail = client.get(f"/v1/agent/goals/{goal['goal_id']}")
    events = client.get(f"/v1/agent/goals/{goal['goal_id']}/events")
    diagnostics = client.get("/v1/agent/diagnostics")

    assert detail.status_code == 200
    assert events.status_code == 200
    assert events.json()["events"]
    assert diagnostics.status_code == 200
