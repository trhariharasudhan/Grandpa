from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.agents.runtime import list_agent_tasks, run_agent_goal
from grandpa.local_actions import handle_local_action
from grandpa.mcp import execute_tool, list_tools
from grandpa.planner import analyze_request, build_execution_plan, classify_goal
from grandpa.server.api_routes import (
    agent_runtime_router,
    mcp_router,
    planner_router,
    skills_router,
)


def test_planner_classifies_and_builds_execution_graph():
    analysis = analyze_request("research Python tutorials and summarize them")

    assert analysis.goal_class == "browser_research"
    assert analysis.workflow_suitable is True
    assert analysis.estimated_risk == "LOW"
    assert "browser.diagnostics" in analysis.required_skills
    assert analysis.graph.nodes[1].dependencies == ["step_1"] or analysis.graph.nodes[
        1
    ].dependencies == ("step_1",)

    graph = build_execution_plan("set up my coding workspace")
    assert graph.workflow_suitable is True
    assert graph.nodes


def test_planner_blocks_dangerous_goal():
    analysis = analyze_request("format my drive")

    assert classify_goal("format my drive") == "dangerous"
    assert analysis.estimated_risk == "BLOCKED"
    assert analysis.unsupported_reason


def test_mcp_bridge_lists_and_executes_runtime_tool(monkeypatch):
    def fake_run_local_action(payload):
        class Response:
            ok = True
            status = "completed"
            message = "Desktop summary ready."
            evidence = {"ready": True}
            action_id = None
            risk_level = "LOW"
            approval_required = False
            error = None

        return Response()

    monkeypatch.setattr("grandpa.pc_control.run_local_action", fake_run_local_action)
    tools = list_tools()
    assert any(tool["name"] == "desktop.summary" for tool in tools)

    result = execute_tool("desktop.summary")
    assert result["ok"] is True
    assert result["message"] == "Desktop summary ready."


def test_agent_runtime_creates_plan_task():
    task = run_agent_goal("organize my downloads folder", execute=False)

    assert task.status == "planned"
    assert task.analysis.workflow_suitable is True
    assert task.analysis.approval_needed_steps
    assert list_agent_tasks()


def test_local_action_routes_multi_step_goal_to_planner():
    result = handle_local_action("set up my coding workspace")

    assert result.status == "handled"
    assert result.kind == "agent_plan"
    assert "Agent plan" in result.message
    assert "desktop.summary" in result.message


def test_planner_agent_mcp_api_routes():
    app = FastAPI()
    app.include_router(skills_router)
    app.include_router(planner_router)
    app.include_router(agent_runtime_router)
    app.include_router(mcp_router)
    client = TestClient(app)

    diagnostics = client.get("/v1/planner/diagnostics")
    assert diagnostics.status_code == 200
    assert diagnostics.json()["planner"]["status"] == "ready"

    analysis = client.post(
        "/v1/planner/analyze", json={"request": "set up my coding workspace"}
    )
    assert analysis.status_code == 200
    assert analysis.json()["workflow_suitable"] is True

    task = client.post(
        "/v1/agent/run",
        json={"request": "research Python tutorials and summarize them"},
    )
    assert task.status_code == 200
    assert task.json()["analysis"]["goal_class"] == "browser_research"

    tasks = client.get("/v1/agent/tasks")
    assert tasks.status_code == 200
    assert tasks.json()["tasks"]

    tools = client.get("/v1/mcp/tools")
    assert tools.status_code == 200
    assert any(tool["name"] == "desktop.summary" for tool in tools.json()["tools"])
