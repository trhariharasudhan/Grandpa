"""Session-owned chat and voice bridge for deterministic multi-step goals."""

from __future__ import annotations

from grandpa.planner.decomposer import DeterministicDecomposer, normalize_goal
from grandpa.planner.executive import ExecutivePlanner
from grandpa.planner.formatter import format_plan
from grandpa.planner.models import Goal, PlannerLimits, PlanResult, PlanStatus

_PLANNERS: dict[str, ExecutivePlanner] = {}


def handle_executive_goal(
    text: str,
    *,
    automation_service=None,
    source: str = "chat",
    action_runner=None,
    origin: str = "direct",
) -> str | None:
    """Run *text* as a multi-step goal, or return None if it is not one.

    ``action_runner`` and ``origin`` follow the goal all the way to the
    actuator: a caller that substituted the actuator gets its substitution
    honoured by plan steps too, and a goal spoken by a person is audited as
    voice rather than as an anonymous direct call.
    """
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
            executor=_executor(session_id, automation_service, action_runner, origin),
        )
        _PLANNERS[session_id] = planner
    result = planner.execute(text)
    if result.status in {"confirmation_required", "clarification_required"}:
        return f"Planning your task.\n{format_plan(result.plan)}\n\n{result.message}"
    return plan_result_message(result)


#: Plan outcomes that describe a finished run, and so have step evidence worth
#: reporting. Everything else -- waiting for confirmation or clarification,
#: paused, cancelled, blocked -- is either not finished or is already saying
#: something the user needs to hear unaltered.
_REPORTABLE_STATUSES = frozenset({"completed", "partially_completed", "failed"})


def plan_result_message(result: PlanResult) -> str:
    """The plan's message, phrased according to what its steps confirmed.

    A plan used to say "Task completed." whether or not anything took effect:
    the per-step verification evidence existed but stopped at
    ``PlanStep.result_metadata`` and never reached a sentence. Someone
    operating by voice has no screen to check against, so that difference was
    invisible to exactly the person who needed it.

    Blocked plans are returned untouched. A refusal is not an unconfirmed
    action, and re-describing one as "I could not confirm it took effect" would
    turn a safety decision into a shrug.

    Only the wording changes. ``PlanResult.status`` and the plan's own status
    are left exactly as the executive planner set them.
    """
    if result.status not in _REPORTABLE_STATUSES:
        return result.message
    from grandpa.desktop.control.verification import (
        aggregate_plan_verification,
        verification_sentence,
    )

    steps = getattr(result.plan, "steps", None) or ()
    outcome = aggregate_plan_verification(step.result_metadata for step in steps)
    return verification_sentence(outcome.status, outcome.detail, result.message)


def clear_planner_sessions() -> None:
    _PLANNERS.clear()


def _executor(
    session_id: str,
    automation_service,
    action_runner=None,
    origin: str = "direct",
):
    from grandpa.planner.executor import PlannerStepExecutor

    return PlannerStepExecutor(
        session_id=session_id,
        automation_service=automation_service,
        action_runner=action_runner,
        origin=origin,
    )


__all__ = [
    "clear_planner_sessions",
    "handle_executive_goal",
    "plan_result_message",
]
