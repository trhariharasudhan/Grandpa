"""Planner-driven skill selection for local-first Grandpa execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any, Literal

RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "BLOCKED"]


@dataclass(frozen=True)
class PlannerStep:
    id: str
    title: str
    skill: str
    params: dict[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()
    risk_level: RiskLevel = "LOW"
    approval_required: bool = False
    retry_count: int = 0
    rollback_safe: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "skill": self.skill,
            "params": self.params,
            "dependencies": list(self.dependencies),
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
            "retry_count": self.retry_count,
            "rollback_safe": self.rollback_safe,
        }


@dataclass(frozen=True)
class ExecutionNode:
    id: str
    skill: str
    params: dict[str, Any]
    dependencies: tuple[str, ...] = ()
    risk_level: RiskLevel = "LOW"
    approval_required: bool = False
    status: str = "queued"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "skill": self.skill,
            "params": self.params,
            "dependencies": list(self.dependencies),
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
            "status": self.status,
        }


@dataclass(frozen=True)
class ExecutionGraph:
    nodes: tuple[ExecutionNode, ...]
    workflow_suitable: bool = False
    handoff_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "workflow_suitable": self.workflow_suitable,
            "handoff_reason": self.handoff_reason,
        }


@dataclass(frozen=True)
class PlannerAnalysis:
    request: str
    intent: str
    goal_class: str
    required_skills: tuple[str, ...]
    dependencies: dict[str, tuple[str, ...]]
    estimated_risk: RiskLevel
    approval_needed_steps: tuple[str, ...]
    workflow_suitable: bool
    confidence: float
    reasoning_summary: str
    steps: tuple[PlannerStep, ...]
    graph: ExecutionGraph
    memory_context: dict[str, Any] = field(default_factory=dict)
    unsupported_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "intent": self.intent,
            "goal_class": self.goal_class,
            "required_skills": list(self.required_skills),
            "dependencies": {
                key: list(value) for key, value in self.dependencies.items()
            },
            "estimated_risk": self.estimated_risk,
            "approval_needed_steps": list(self.approval_needed_steps),
            "workflow_suitable": self.workflow_suitable,
            "confidence": self.confidence,
            "reasoning_summary": self.reasoning_summary,
            "steps": [step.to_dict() for step in self.steps],
            "graph": self.graph.to_dict(),
            "memory_context": self.memory_context,
            "unsupported_reason": self.unsupported_reason,
        }


def classify_goal(request: str) -> str:
    clean = _clean(request)
    if any(
        word in clean for word in ("research", "summarize", "summarise", "tutorial")
    ):
        return "browser_research"
    if any(word in clean for word in ("organize", "organise", "downloads", "archive")):
        return "file_organization"
    if any(
        word in clean
        for word in (
            "coding workspace",
            "code workspace",
            "developer workspace",
            "coding setup",
        )
    ):
        return "developer_startup"
    if any(word in clean for word in ("diagnostic", "status", "readiness")):
        return "diagnostics"
    if any(
        word in clean
        for word in ("delete", "wipe", "format", "shutdown", "payment", "purchase")
    ):
        return "dangerous"
    return "general"


def estimate_risk(
    steps: list[PlannerStep] | tuple[PlannerStep, ...], goal_class: str = ""
) -> RiskLevel:
    if goal_class == "dangerous" or any(step.risk_level == "BLOCKED" for step in steps):
        return "BLOCKED"
    if any(step.risk_level == "HIGH" for step in steps):
        return "HIGH"
    if any(step.risk_level == "MEDIUM" for step in steps):
        return "MEDIUM"
    return "LOW"


def decompose_multi_step_task(request: str) -> list[PlannerStep]:
    clean = _clean(request)
    goal = classify_goal(clean)
    if goal == "developer_startup":
        return [
            PlannerStep(
                "step_1",
                "Check desktop readiness",
                "desktop.summary",
                {
                    "desktop_service": "diagnostics",
                    "supported_environments": ["windows"],
                },
            ),
            PlannerStep(
                "step_2",
                "Check workflow runtime",
                "automation.workflow_status",
                {"desktop_service": "automation"},
                dependencies=("step_1",),
            ),
        ]
    if goal == "browser_research":
        return [
            PlannerStep("step_1", "Check browser adapter", "browser.diagnostics"),
            PlannerStep(
                "step_2",
                "Prepare browser search plan",
                "browser.search_plan",
                {"query": request},
                dependencies=("step_1",),
            ),
            PlannerStep(
                "step_3",
                "Prepare local research workflow handoff",
                "automation.workflow_status",
                dependencies=("step_2",),
            ),
        ]
    if goal == "file_organization":
        return [
            PlannerStep(
                "step_1",
                "Check workflow runtime",
                "automation.workflow_status",
                {"desktop_service": "automation"},
            ),
            PlannerStep(
                "step_2",
                "Require approval before file organization",
                "desktop.keyboard_type",
                {
                    "text": "file organization placeholder",
                    "desktop_service": "automation",
                    "approval_reason": "file organization needs explicit user confirmation",
                },
                dependencies=("step_1",),
                risk_level="MEDIUM",
                approval_required=True,
                rollback_safe=False,
            ),
        ]
    if goal == "diagnostics":
        return [
            PlannerStep(
                "step_1",
                "Check desktop diagnostics",
                "desktop.diagnostics",
                {"desktop_service": "diagnostics"},
            ),
            PlannerStep(
                "step_2",
                "Check browser diagnostics",
                "browser.diagnostics",
                dependencies=("step_1",),
            ),
            PlannerStep(
                "step_3",
                "Check visual diagnostics",
                "vision.visual_diagnostics",
                dependencies=("step_2",),
            ),
        ]
    if goal == "dangerous":
        return [
            PlannerStep(
                "step_1",
                "Blocked dangerous request",
                "safety.blocked",
                risk_level="BLOCKED",
                approval_required=False,
                rollback_safe=False,
            )
        ]
    matched = _match_runtime_skill(clean)
    if matched:
        return [PlannerStep("step_1", f"Run {matched}", matched)]
    return []


def build_execution_plan(request: str) -> ExecutionGraph:
    steps = decompose_multi_step_task(request)
    nodes = tuple(
        ExecutionNode(
            id=step.id,
            skill=step.skill,
            params=step.params,
            dependencies=step.dependencies,
            risk_level=step.risk_level,
            approval_required=step.approval_required,
        )
        for step in steps
    )
    workflow_suitable = len(steps) > 1 or classify_goal(request) in {
        "developer_startup",
        "browser_research",
        "file_organization",
    }
    reason = (
        "Multi-step request can be tracked by the workflow runtime."
        if workflow_suitable
        else ""
    )
    return ExecutionGraph(
        nodes=nodes, workflow_suitable=workflow_suitable, handoff_reason=reason
    )


def analyze_request(request: str) -> PlannerAnalysis:
    clean = request.strip()
    goal = classify_goal(clean)
    steps = tuple(decompose_multi_step_task(clean))
    graph = build_execution_plan(clean)
    risk = estimate_risk(steps, goal)
    confidence = _confidence(goal, steps)
    approval_steps = tuple(step.id for step in steps if step.approval_required)
    required = tuple(step.skill for step in steps)
    dependencies = {step.id: step.dependencies for step in steps if step.dependencies}
    memory = _memory_context(clean)
    unsupported = (
        ""
        if steps and risk != "BLOCKED"
        else "No safe local plan is available."
        if risk != "BLOCKED"
        else "Dangerous requests are blocked."
    )
    return PlannerAnalysis(
        request=clean,
        intent=goal.replace("_", " "),
        goal_class=goal,
        required_skills=required,
        dependencies=dependencies,
        estimated_risk=risk,
        approval_needed_steps=approval_steps,
        workflow_suitable=graph.workflow_suitable,
        confidence=confidence,
        reasoning_summary=_summary(goal, risk, steps),
        steps=steps,
        graph=graph,
        memory_context=memory,
        unsupported_reason=unsupported,
    )


def planner_diagnostics() -> dict[str, Any]:
    from grandpa.skills.registry import (
        ensure_default_skills_registered,
        registry_diagnostics,
    )

    ensure_default_skills_registered()
    runtime = registry_diagnostics()
    return {
        "status": "ready",
        "planner": "deterministic-local",
        "skill_count": runtime["skill_count"],
        "categories": runtime["categories"],
        "workflow_handoff_ready": True,
        "mcp_bridge_ready": True,
        "local_only": True,
        "updated_at": time(),
    }


def _match_runtime_skill(clean: str) -> str:
    try:
        from grandpa.skills.registry import (
            ensure_default_skills_registered,
            match_skill,
        )

        ensure_default_skills_registered()
        skill = match_skill(clean)
        return skill.name if skill else ""
    except Exception:
        return ""


def _memory_context(request: str) -> dict[str, Any]:
    try:
        from grandpa.memory.intelligence import ranked_memory_context

        data = ranked_memory_context(request, limit=3)
        context = {
            "available": True,
            "matches": data.get("matches", [])[:3],
            "confidence": data.get("confidence", 0.0),
            "source": "memory_intelligence",
        }
        try:
            from grandpa.knowledge.engine import planner_knowledge_context

            context["knowledge"] = planner_knowledge_context(request, limit=3)
        except Exception:
            context["knowledge"] = {"available": False, "results": []}
        return context
    except Exception:
        return {"available": False, "matches": []}


def _summary(goal: str, risk: RiskLevel, steps: tuple[PlannerStep, ...]) -> str:
    if risk == "BLOCKED":
        return "The request matches a blocked action class and will not be executed."
    if not steps:
        return "No confident local skill plan was found; Grandpa should fall back to normal chat."
    return f"Grandpa found {len(steps)} local skill step(s) for {goal.replace('_', ' ')} with {risk.lower()} risk."


def _confidence(goal: str, steps: tuple[PlannerStep, ...]) -> float:
    if goal == "dangerous":
        return 0.98
    if steps:
        return 0.82 if len(steps) > 1 else 0.72
    return 0.25


def _clean(text: str) -> str:
    return " ".join(text.lower().strip().split())


__all__ = [
    "ExecutionGraph",
    "ExecutionNode",
    "PlannerAnalysis",
    "PlannerStep",
    "analyze_request",
    "build_execution_plan",
    "classify_goal",
    "decompose_multi_step_task",
    "estimate_risk",
    "planner_diagnostics",
]
