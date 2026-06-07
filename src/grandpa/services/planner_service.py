"""Service facade for planner, native agent, MCP, and intent-router routes."""

from __future__ import annotations

from typing import Any

from grandpa.services.base import safe_call, summarize_ready


def diagnostics() -> dict[str, Any]:
    from grandpa.agents.runtime import agent_diagnostics
    from grandpa.mcp import tool_diagnostics
    from grandpa.planner import planner_diagnostics

    return {"planner": planner_diagnostics(), "agent": agent_diagnostics(), "mcp": tool_diagnostics()}


def analyze_request(text: str) -> dict[str, Any]:
    from grandpa.planner import analyze_request as planner_analyze

    return planner_analyze(text).to_dict()


def run_agent_goal_from_body(body: dict[str, Any]) -> dict[str, Any]:
    from grandpa.agents.runtime import run_agent_goal

    text = str(body.get("request") or body.get("goal") or "").strip()
    if not text:
        raise ValueError("'request' field is required")
    task = run_agent_goal(
        text,
        execute=bool(body.get("execute", False)),
        source=str(body.get("source") or "api"),
    )
    return task.to_dict()


def list_agent_tasks(limit: int = 50) -> dict[str, Any]:
    from grandpa.agents.runtime import list_agent_tasks as runtime_tasks

    return {"tasks": runtime_tasks(limit=limit)}


def mcp_tools() -> dict[str, Any]:
    from grandpa.mcp import list_tools

    return {"tools": list_tools(), "local_only": True, "networking_enabled": False}


def router_diagnostics() -> dict[str, Any]:
    from grandpa.router import router_diagnostics as runtime_router_diagnostics

    return runtime_router_diagnostics()


def analyze_intent(text: str) -> dict[str, Any]:
    from grandpa.router import analyze_intent as router_analyze

    return router_analyze(text).to_dict()


def health() -> dict[str, Any]:
    payload = safe_call("planner", diagnostics)
    ready = summarize_ready(payload.get("planner", {})) and summarize_ready(payload.get("agent", {}))
    return {
        "name": "planner",
        "ready": ready,
        "status": "ready" if ready else "partial",
        "dependencies": {
            "planner": payload.get("planner", {}).get("status", "unknown") if isinstance(payload.get("planner"), dict) else "unknown",
            "agent": payload.get("agent", {}).get("status", "unknown") if isinstance(payload.get("agent"), dict) else "unknown",
            "mcp": payload.get("mcp", {}).get("status", "unknown") if isinstance(payload.get("mcp"), dict) else "unknown",
        },
    }


def readiness() -> dict[str, Any]:
    payload = safe_call("planner", diagnostics)
    return {"ready": health()["ready"], "diagnostics": payload}
