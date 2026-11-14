"""Adapters between the intent router and legacy local action result shape."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from grandpa.local_action_result import LocalActionResult
    from grandpa.skills.runtime import SkillResult


def skill_result_to_local_action(
    route, skill_result: "SkillResult"
) -> "LocalActionResult":
    """Convert a runtime skill result into the existing local action contract."""
    from grandpa.local_action_result import LocalActionResult

    status = (
        "handled"
        if skill_result.ok
        else (
            "unsupported"
            if skill_result.status == "unsupported"
            else "blocked"
            if skill_result.status == "blocked"
            else "error"
        )
    )
    kind = (
        "browser"
        if route.category == "browser"
        else "screen"
        if route.category == "vision"
        else "pc_control"
    )
    return LocalActionResult(
        status=status,
        kind=kind,
        target=route.skill_name or route.intent,
        message=skill_result.message,
        tts_text=skill_result.message,
        permission="allowed"
        if not skill_result.approval_required
        else "requires_confirmation",
    )


def planner_task_to_local_action(route, task) -> "LocalActionResult":
    """Convert a native agent planner task into a local action response."""
    from grandpa.local_action_result import LocalActionResult

    # A plan is internal. What reaches the user is a sentence about what was
    # done or what is waited on -- never the phase, the confidence, the risk
    # label or the dotted skill names, which used to be printed in chat where
    # an answer belonged.
    if hasattr(task, "goal_id"):
        from grandpa.agents.goal_mode import describe_goal

        spoken = describe_goal(task)
        return LocalActionResult(
            status="handled"
            if task.status not in {"failed", "cancelled"}
            else "unsupported",
            kind="agent_plan",
            target=task.goal_id,
            message=spoken,
            tts_text=spoken,
            permission="allowed",
        )

    analysis = task.analysis
    spoken = (
        analysis.unsupported_reason.strip()
        or analysis.reasoning_summary.strip()
        or "I prepared a safe local plan."
    )
    if analysis.approval_needed_steps:
        spoken = f"{spoken} I need your approval before I go any further."
    return LocalActionResult(
        status="handled" if task.status != "unsupported" else "unsupported",
        kind="agent_plan",
        target=task.task_id,
        message=spoken,
        tts_text=spoken,
        permission="allowed",
    )


__all__ = ["planner_task_to_local_action", "skill_result_to_local_action"]
