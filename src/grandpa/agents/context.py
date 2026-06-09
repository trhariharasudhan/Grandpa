"""Shared deterministic context for Grandpa multi-agent tasks."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SharedAgentContext:
    """Context packet shared across specialized local agents."""

    task_id: str
    user_request: str
    planner_output: dict[str, Any] = field(default_factory=dict)
    memory_context: dict[str, Any] = field(default_factory=dict)
    browser_observations: dict[str, Any] = field(default_factory=dict)
    desktop_observations: dict[str, Any] = field(default_factory=dict)
    knowledge_context: dict[str, Any] = field(default_factory=dict)
    workflow_references: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_shared_context(user_request: str, *, task_id: str | None = None) -> SharedAgentContext:
    """Build local-only context for a multi-agent collaboration run."""

    context = SharedAgentContext(
        task_id=task_id or "mag_" + uuid.uuid4().hex[:12],
        user_request=user_request.strip(),
    )
    context.planner_output = _safe_call(_planner_context, user_request)
    context.memory_context = _safe_call(_memory_context, user_request)
    context.browser_observations = _safe_call(_browser_context)
    context.desktop_observations = _safe_call(_desktop_context)
    context.knowledge_context = _safe_call(_knowledge_context, user_request)
    context.workflow_references = _safe_call(_workflow_context)
    context.updated_at = time.time()
    return context


def _safe_call(func, *args: Any) -> dict[str, Any]:
    try:
        return func(*args)
    except Exception as exc:
        return {"available": False, "error": exc.__class__.__name__}


def _planner_context(user_request: str) -> dict[str, Any]:
    from grandpa.planner.engine import analyze_request

    analysis = analyze_request(user_request)
    data = analysis.to_dict()
    data["available"] = True
    return data


def _memory_context(user_request: str) -> dict[str, Any]:
    from grandpa.memory.intelligence import ranked_memory_context, summarize_memory_profile

    return {
        "available": True,
        "ranked_context": ranked_memory_context(user_request, limit=5),
        "profile": summarize_memory_profile(),
    }


def _browser_context() -> dict[str, Any]:
    from grandpa.browser.agent import browser_agent_diagnostics

    diagnostics = browser_agent_diagnostics()
    diagnostics["available"] = True
    return diagnostics


def _desktop_context() -> dict[str, Any]:
    from grandpa.pc_control import run_local_action

    result = run_local_action({"action_type": "desktop_summary", "target": "desktop", "dry_run": True})
    return {
        "available": True,
        "status": result.status,
        "message": result.message,
        "evidence": result.evidence,
    }


def _workflow_context() -> dict[str, Any]:
    from grandpa.smart_automation import diagnostics as workflow_diagnostics

    diagnostics = workflow_diagnostics()
    diagnostics["available"] = True
    return diagnostics


def _knowledge_context(user_request: str) -> dict[str, Any]:
    from grandpa.knowledge.engine import planner_knowledge_context

    return planner_knowledge_context(user_request, limit=5)


__all__ = ["SharedAgentContext", "build_shared_context"]
