"""Adapters between the intent router and legacy local action result shape."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from grandpa.local_actions import LocalActionResult
    from grandpa.skills.runtime import SkillResult


def skill_result_to_local_action(route, skill_result: "SkillResult") -> "LocalActionResult":
    """Convert a runtime skill result into the existing local action contract."""
    from grandpa.local_actions import LocalActionResult

    status = "handled" if skill_result.ok else (
        "unsupported" if skill_result.status == "unsupported" else "blocked" if skill_result.status == "blocked" else "error"
    )
    kind = "browser" if route.category == "browser" else "screen" if route.category == "vision" else "pc_control"
    return LocalActionResult(
        status=status,
        kind=kind,
        target=route.skill_name or route.intent,
        message=skill_result.message,
        tts_text=skill_result.message,
        permission="allowed" if not skill_result.approval_required else "requires_confirmation",
    )


def planner_task_to_local_action(route, task) -> "LocalActionResult":
    """Convert a native agent planner task into a local action response."""
    from grandpa.local_actions import LocalActionResult

    if hasattr(task, "goal_id"):
        analysis = getattr(task, "plan", {}) or {}
        lines = [
            f"Agent plan goal {task.status}: {analysis.get('intent', route.intent)}.",
            f"- Phase: {task.current_phase}",
            f"- Confidence: {float(analysis.get('confidence', route.confidence)):.0%}",
            f"- Risk: {analysis.get('estimated_risk', 'LOW')}",
            f"- Skills: {', '.join(analysis.get('required_skills', [])) or 'none'}",
            f"- Actions taken: {len(task.actions_taken)}",
        ]
        if task.approvals_needed:
            lines.append(f"- Approval needed: {', '.join(str(item.get('step_id', '')) for item in task.approvals_needed)}")
        if task.result_summary:
            lines.append(task.result_summary)
        else:
            lines.append(str(analysis.get("reasoning_summary", "Grandpa prepared a safe local goal plan.")))
        return LocalActionResult(
            status="handled" if task.status not in {"failed", "cancelled"} else "unsupported",
            kind="agent_plan",
            target=task.goal_id,
            message="\n".join(lines),
            tts_text="I processed the autonomous goal safely.",
            permission="allowed",
        )

    analysis = task.analysis
    lines = [
        f"Agent plan: {analysis.intent}.",
        f"- Confidence: {analysis.confidence:.0%}",
        f"- Risk: {analysis.estimated_risk}",
        f"- Skills: {', '.join(analysis.required_skills) or 'none'}",
        f"- Workflow handoff: {'ready' if analysis.workflow_suitable else 'not needed'}",
    ]
    if analysis.approval_needed_steps:
        lines.append(f"- Approval needed: {', '.join(analysis.approval_needed_steps)}")
    if analysis.unsupported_reason:
        lines.append(f"- Note: {analysis.unsupported_reason}")
    lines.append(analysis.reasoning_summary)
    return LocalActionResult(
        status="handled" if task.status != "unsupported" else "unsupported",
        kind="agent_plan",
        target=task.task_id,
        message="\n".join(lines),
        tts_text="I prepared a safe local execution plan.",
        permission="allowed",
    )


__all__ = ["planner_task_to_local_action", "skill_result_to_local_action"]
