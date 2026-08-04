"""Safe, concise planner output and trace formatting."""

from __future__ import annotations

import json

from grandpa.planner.models import (
    ExecutionPlan,
    PlanProgress,
    PlanResult,
    model_to_dict,
)
from grandpa.planner.state_store import sanitize_plan_data


def format_plan(plan: ExecutionPlan) -> str:
    lines = ["Goal:", plan.original_goal, "", "Plan:"]
    lines.extend(
        f"{step.order}. {step.description}"
        for step in sorted(plan.steps, key=lambda item: item.order)
    )
    lines.extend(
        [
            "",
            "Risk:",
            plan.safety_classification.value.title(),
            "",
            "Estimated maximum duration:",
            f"{plan.limits.max_duration_seconds:g} seconds",
        ]
    )
    if plan.planner_source != "deterministic":
        lines.extend(["", f"Planner: {plan.planner_source}"])
    return "\n".join(lines)


def format_plan_result(result: PlanResult) -> str:
    """Render a valid plan or a concise failure without an empty plan shell."""

    if result.plan.steps and result.status == "ready":
        return format_plan(result.plan)
    return "\n".join(
        (
            "Goal:",
            result.plan.original_goal,
            "",
            f"Status: {result.status}",
            f"Reason: {result.message}",
            "",
            "Try: Open Chrome and search for FastAPI documentation",
        )
    )


def format_status(plan: ExecutionPlan | None) -> str:
    if plan is None:
        return "No plan exists for this session."
    completed = sum(
        step.status.value in {"completed", "skipped"} for step in plan.steps
    )
    return (
        f"Plan {plan.plan_id}\n"
        f"Status: {plan.status.value}\n"
        f"Progress: {completed}/{len(plan.steps)} steps\n"
        f"Current step: {plan.current_step_id or 'none'}"
    )


def format_trace(plan: ExecutionPlan | None) -> str:
    if plan is None:
        return "No plan trace exists for this session."
    lines = [f"Trace for {plan.plan_id}:"]
    for step in sorted(plan.steps, key=lambda item: item.order):
        lines.append(f"{step.order}. {step.description} [{step.status.value}]")
        for attempt in step.attempts:
            message = _safe_message(attempt.message)
            lines.append(f"   attempt {attempt.attempt}: {attempt.status} - {message}")
            if attempt.recovery:
                lines.append(f"   recovery: {attempt.recovery}")
    return "\n".join(lines)


def format_graph(plan: ExecutionPlan | None, *, mermaid: bool = False) -> str:
    if plan is None:
        return "No plan graph exists for this session."
    if mermaid:
        lines = ["flowchart TD"]
        for step in plan.steps:
            label = step.description.replace('"', "'")
            lines.append(f'    {step.step_id}["{step.order}. {label}"]')
            for dependency in step.dependencies:
                lines.append(f"    {dependency.step_id} --> {step.step_id}")
        return "\n".join(lines)
    return "\n".join(
        f"{step.step_id}: {', '.join(item.step_id for item in step.dependencies) or 'root'} -> {step.action}"
        for step in plan.steps
    )


def format_dump(plan: ExecutionPlan) -> str:
    return json.dumps(
        sanitize_plan_data(model_to_dict(plan)), indent=2, ensure_ascii=True
    )


def format_debug_trace(plan: ExecutionPlan) -> str:
    diagnostics = sanitize_plan_data(plan.metadata.get("diagnostics", []))
    return "Planner diagnostics:\n" + json.dumps(
        diagnostics,
        indent=2,
        ensure_ascii=True,
    )


def progress(plan: ExecutionPlan) -> PlanProgress:
    completed = sum(
        step.status.value in {"completed", "skipped"} for step in plan.steps
    )
    return PlanProgress(
        plan.plan_id,
        completed,
        len(plan.steps),
        plan.current_step_id,
        plan.status.value,
    )


def _safe_message(value: str) -> str:
    if any(
        marker in value.casefold()
        for marker in ("password", "otp", "token", "card number")
    ):
        return "[sensitive details redacted]"
    return value


__all__ = [
    "format_debug_trace",
    "format_dump",
    "format_graph",
    "format_plan",
    "format_plan_result",
    "format_status",
    "format_trace",
    "progress",
]
