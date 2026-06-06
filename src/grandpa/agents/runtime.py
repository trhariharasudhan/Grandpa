"""Native agent runtime for planner-driven local skill execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from time import time
from typing import Any, Literal

from grandpa.planner import PlannerAnalysis, analyze_request
from grandpa.skills.registry import ensure_default_skills_registered, execute_skill
from grandpa.skills.runtime import SkillExecutionContext

AgentTaskStatus = Literal["planned", "running", "waiting_approval", "completed", "failed", "cancelled", "unsupported"]


@dataclass
class AgentTask:
    task_id: str
    request: str
    status: AgentTaskStatus
    analysis: PlannerAnalysis
    results: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    workflow_handoff: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "request": self.request,
            "status": self.status,
            "analysis": self.analysis.to_dict(),
            "results": self.results,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "workflow_handoff": self.workflow_handoff,
        }


_TASKS: dict[str, AgentTask] = {}


def run_agent_goal(request: str, *, execute: bool = False, source: str = "agent-api") -> AgentTask:
    """Plan and optionally execute a local agent goal."""
    ensure_default_skills_registered()
    analysis = analyze_request(request)
    status: AgentTaskStatus = "planned"
    if analysis.estimated_risk == "BLOCKED":
        status = "unsupported"
    elif not analysis.steps:
        status = "unsupported"
    elif analysis.approval_needed_steps and execute:
        status = "waiting_approval"
    elif execute:
        status = "running"
    task = AgentTask(
        task_id=f"agt_{uuid.uuid4().hex[:12]}",
        request=request,
        status=status,
        analysis=analysis,
    )
    _TASKS[task.task_id] = task

    if execute and status == "running":
        _execute_task(task, source=source)
    elif analysis.workflow_suitable:
        task.workflow_handoff = _workflow_handoff(request, analysis)
        task.updated_at = time()
    return task


def continue_agent_task(task_id: str, *, execute: bool = True) -> AgentTask | None:
    task = _TASKS.get(task_id)
    if task is None or task.status in {"completed", "cancelled"}:
        return task
    if execute and not task.analysis.approval_needed_steps:
        _execute_task(task, source="agent-continue")
    return task


def cancel_agent_task(task_id: str) -> AgentTask | None:
    task = _TASKS.get(task_id)
    if task is None:
        return None
    task.status = "cancelled"
    task.updated_at = time()
    return task


def explain_plan(request: str) -> dict[str, Any]:
    return analyze_request(request).to_dict()


def list_agent_tasks(limit: int = 50) -> list[dict[str, Any]]:
    tasks = sorted(_TASKS.values(), key=lambda item: item.updated_at, reverse=True)
    return [task.to_dict() for task in tasks[: max(1, min(limit, 200))]]


def agent_diagnostics() -> dict[str, Any]:
    return {
        "status": "ready",
        "task_count": len(_TASKS),
        "local_only": True,
        "planner_connected": True,
        "skill_runtime_connected": True,
    }


def _execute_task(task: AgentTask, *, source: str) -> None:
    task.status = "running"
    for step in task.analysis.steps:
        if step.approval_required:
            task.status = "waiting_approval"
            task.results.append({"step_id": step.id, "status": "approval_required", "skill": step.skill})
            task.updated_at = time()
            return
        result = execute_skill(
            step.skill,
            step.params,
            SkillExecutionContext(
                workflow_id=task.task_id,
                user_request=task.request,
                source=source,
                dry_run=True,
            ),
        )
        task.results.append({"step_id": step.id, "skill": step.skill, "result": result.to_dict()})
        if not result.ok and result.status not in {"unsupported", "approval_required"}:
            task.status = "failed"
            task.updated_at = time()
            return
    task.status = "completed"
    task.updated_at = time()


def _workflow_handoff(request: str, analysis: PlannerAnalysis) -> dict[str, Any]:
    return {
        "suitable": analysis.workflow_suitable,
        "reason": analysis.graph.handoff_reason,
        "request": request,
        "safe_to_create": analysis.estimated_risk in {"LOW", "MEDIUM"},
        "approval_required": bool(analysis.approval_needed_steps),
    }


__all__ = [
    "AgentTask",
    "agent_diagnostics",
    "cancel_agent_task",
    "continue_agent_task",
    "explain_plan",
    "list_agent_tasks",
    "run_agent_goal",
]
