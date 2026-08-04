"""Session-owned chat and voice bridge for deterministic multi-step goals."""

from __future__ import annotations

from grandpa.planner.decomposer import DeterministicDecomposer, normalize_goal
from grandpa.planner.executive import ExecutivePlanner
from grandpa.planner.formatter import format_plan
from grandpa.planner.models import Goal, PlannerLimits, PlanStatus

_PLANNERS: dict[str, ExecutivePlanner] = {}


def handle_executive_goal(
    text: str,
    *,
    automation_service=None,
    source: str = "chat",
) -> str | None:
    session_id = f"{source}:{id(automation_service)}"
    planner = _PLANNERS.get(session_id)
    current = planner.current() if planner is not None else None
    decision = text.strip().casefold()
    if current is not None and current.status == PlanStatus.WAITING_FOR_CONFIRMATION:
        if decision in {"yes", "confirm", "continue", "resume"}:
            return planner.resume(confirmed=True).message
        if decision in {"no", "cancel", "stop"}:
            return planner.cancel().message
        return (
            current.confirmation.message
            if current.confirmation
            else "Confirmation is required."
        )
    if current is not None and current.status == PlanStatus.WAITING_FOR_CLARIFICATION:
        return planner.clarify(text).message
    steps = DeterministicDecomposer().decompose(
        Goal(text, normalize_goal(text), session_id), PlannerLimits()
    )
    if steps is None or len(steps) < 2:
        return None
    if planner is None:
        planner = ExecutivePlanner(
            session_id=session_id,
            executor=_executor(session_id, automation_service),
        )
        _PLANNERS[session_id] = planner
    result = planner.execute(text)
    if result.status in {"confirmation_required", "clarification_required"}:
        return f"Planning your task.\n{format_plan(result.plan)}\n\n{result.message}"
    return result.message


def clear_planner_sessions() -> None:
    _PLANNERS.clear()


def _executor(session_id: str, automation_service):
    from grandpa.planner.executor import PlannerStepExecutor

    return PlannerStepExecutor(
        session_id=session_id,
        automation_service=automation_service,
    )


__all__ = ["clear_planner_sessions", "handle_executive_goal"]
