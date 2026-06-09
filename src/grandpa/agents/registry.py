"""Deterministic specialized-agent registry for Grandpa."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from grandpa.agents.context import SharedAgentContext

AgentExecutor = Callable[[SharedAgentContext], dict[str, Any]]


@dataclass(frozen=True)
class AgentSpec:
    """Description and executor for a built-in local agent."""

    agent_id: str
    name: str
    capabilities: tuple[str, ...]
    supported_goals: tuple[str, ...]
    executor: AgentExecutor
    description: str = ""

    def diagnostics(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "capabilities": list(self.capabilities),
            "supported_goals": list(self.supported_goals),
            "description": self.description,
            "ready": True,
            "local_only": True,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("executor", None)
        payload["capabilities"] = list(self.capabilities)
        payload["supported_goals"] = list(self.supported_goals)
        return payload


_AGENTS: dict[str, AgentSpec] = {}


def register_agent(spec: AgentSpec, *, replace: bool = False) -> AgentSpec:
    if spec.agent_id in _AGENTS and not replace:
        raise ValueError(f"Agent already registered: {spec.agent_id}")
    _AGENTS[spec.agent_id] = spec
    return spec


def get_agent(agent_id: str) -> AgentSpec | None:
    _ensure_builtin_agents()
    return _AGENTS.get(agent_id)


def list_agents() -> list[dict[str, Any]]:
    _ensure_builtin_agents()
    return [spec.to_dict() for spec in sorted(_AGENTS.values(), key=lambda item: item.agent_id)]


def select_agents_for_goal(user_request: str) -> list[AgentSpec]:
    """Select a small deterministic collaboration team for a request."""

    _ensure_builtin_agents()
    clean = user_request.lower()
    selected: list[str] = ["memory_agent"]
    if any(word in clean for word in ("research", "tutorial", "webpage", "page", "browser", "youtube", "search")):
        selected.extend(["research_agent", "browser_agent"])
    if any(word in clean for word in ("desktop", "pc", "workspace", "coding", "vscode", "health", "diagnostic", "readiness")):
        selected.extend(["desktop_agent", "coding_agent"])
    if any(word in clean for word in ("mobile", "phone", "android", "notification")):
        selected.append("mobile_agent")
    if len(selected) == 1:
        selected.extend(["research_agent", "desktop_agent"])
    ordered: list[AgentSpec] = []
    seen: set[str] = set()
    for agent_id in selected:
        spec = _AGENTS.get(agent_id)
        if spec and agent_id not in seen:
            ordered.append(spec)
            seen.add(agent_id)
    return ordered


def agent_registry_diagnostics() -> dict[str, Any]:
    _ensure_builtin_agents()
    agents = list_agents()
    return {
        "status": "ready",
        "registered_count": len(agents),
        "agents": agents,
        "capabilities": sorted({cap for item in agents for cap in item["capabilities"]}),
        "local_only": True,
        "approval_bypass_allowed": False,
    }


def _ensure_builtin_agents() -> None:
    if _AGENTS:
        return
    register_agent(
        AgentSpec(
            "research_agent",
            "Research Agent",
            ("research_planning", "query_decomposition", "source_plan"),
            ("research Python tutorials", "collect diagnostics report"),
            _execute_research_agent,
            "Plans local-first research tasks and summarizes planner output.",
        )
    )
    register_agent(
        AgentSpec(
            "browser_agent",
            "Browser Agent",
            ("visible_page_summary", "visible_links", "visible_buttons", "search_plans"),
            ("summarize current webpage", "research Python tutorials"),
            _execute_browser_agent,
            "Uses the visible-page browser snapshot and safe browser plans.",
        )
    )
    register_agent(
        AgentSpec(
            "desktop_agent",
            "Desktop Agent",
            ("desktop_diagnostics", "monitor_info", "workspace_readiness"),
            ("prepare coding environment", "analyze Grandpa health"),
            _execute_desktop_agent,
            "Reads desktop diagnostics without performing risky actions.",
        )
    )
    register_agent(
        AgentSpec(
            "memory_agent",
            "Memory Agent",
            ("ranked_memory", "preferences", "completion_summary"),
            ("all_goals",),
            _execute_memory_agent,
            "Retrieves ranked local memory context and stores task summaries.",
        )
    )
    register_agent(
        AgentSpec(
            "coding_agent",
            "Coding Agent",
            ("developer_workspace_plan", "workflow_readiness", "project_diagnostics"),
            ("prepare coding environment", "collect diagnostics report"),
            _execute_coding_agent,
            "Plans deterministic coding workspace and diagnostic workflows.",
        )
    )
    register_agent(
        AgentSpec(
            "mobile_agent",
            "Mobile Agent",
            ("mobile_diagnostics", "device_status", "pairing_readiness"),
            ("mobile companion diagnostics", "notification sync"),
            _execute_mobile_agent,
            "Reports mobile companion readiness when available.",
        )
    )


def _execute_research_agent(context: SharedAgentContext) -> dict[str, Any]:
    from grandpa.browser.agent import search_web_plan
    from grandpa.planner.engine import analyze_request

    analysis = analyze_request(context.user_request).to_dict()
    data: dict[str, Any] = {"planner": analysis}
    if any(word in context.user_request.lower() for word in ("research", "search", "tutorial", "youtube")):
        data["browser_plan"] = search_web_plan(context.user_request)
    return _ok("Prepared a research plan using planner and browser search context.", data)


def _execute_browser_agent(context: SharedAgentContext) -> dict[str, Any]:
    from grandpa.browser.agent import extract_visible_buttons, extract_visible_links, summarize_current_page

    clean = context.user_request.lower()
    data: dict[str, Any] = {"diagnostics": context.browser_observations}
    if "link" in clean:
        data["links"] = extract_visible_links()
        message = data["links"].get("message", "Collected visible links.")
    elif "button" in clean:
        data["buttons"] = extract_visible_buttons()
        message = data["buttons"].get("message", "Collected visible buttons.")
    elif any(word in clean for word in ("summarize", "summarise", "webpage", "page")):
        data["summary"] = summarize_current_page()
        message = data["summary"].get("message", "Summarized the visible page.")
    else:
        message = "Checked browser context and visible-page readiness."
    return _ok(message, data)


def _execute_desktop_agent(context: SharedAgentContext) -> dict[str, Any]:
    return _ok(
        context.desktop_observations.get("message", "Collected desktop diagnostics."),
        {"desktop": context.desktop_observations},
    )


def _execute_memory_agent(context: SharedAgentContext) -> dict[str, Any]:
    return _ok(
        "Retrieved ranked memory and knowledge context for this task.",
        {"memory": context.memory_context, "knowledge": context.knowledge_context},
    )


def _execute_coding_agent(context: SharedAgentContext) -> dict[str, Any]:
    return _ok(
        "Prepared a coding workspace readiness plan.",
        {
            "planner": context.planner_output,
            "workflow": context.workflow_references,
            "desktop": context.desktop_observations,
            "knowledge": context.knowledge_context,
        },
    )


def _execute_mobile_agent(context: SharedAgentContext) -> dict[str, Any]:
    try:
        from grandpa.mobile_integration import mobile_diagnostics

        diagnostics = mobile_diagnostics()
    except Exception as exc:
        diagnostics = {"available": False, "status": "pending_validation", "error": exc.__class__.__name__}
    return _ok("Checked mobile companion readiness.", {"mobile": diagnostics})


def _ok(message: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "status": "completed", "message": message, "data": data}


__all__ = [
    "AgentSpec",
    "agent_registry_diagnostics",
    "get_agent",
    "list_agents",
    "register_agent",
    "select_agents_for_goal",
]
