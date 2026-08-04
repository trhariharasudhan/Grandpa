"""Planner Engine for Project Engineer Mode V1."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from grandpa.agent.development.models import ProjectState, Task


class EngineeringPlanner:
    """Generates structured work packages, plans milestones, and recommends engineering tasks."""

    def __init__(self, state: ProjectState) -> None:
        self.state = state

    def analyze_milestone_and_task(self) -> Tuple[Optional[str], Optional[Task], str]:
        """Prioritizes next action: legacy check > blockers > current milestone > dependencies > planned roadmap."""
        from grandpa.agent.development.roadmap_generator import is_legacy_roadmap

        if is_legacy_roadmap(self.state):
            reason = "Legacy roadmap detected. Run `grandpa roadmap migrate --preview`."
            return None, None, reason

        # 1. Check for Blockers
        blocked_milestones = self.state.roadmap.blocked_milestones
        if blocked_milestones:
            reason = f"Resolving blocker on milestone '{blocked_milestones[0]}'."
            return blocked_milestones[0], None, reason

        blocked_tasks = [t for t in self.state.tasks if t.status == "blocked"]
        if blocked_tasks:
            reason = f"Resolving blocked task: ({blocked_tasks[0].task_id}) '{blocked_tasks[0].title}'."
            return self.state.current_milestone, blocked_tasks[0], reason

        # 2. Check Current Milestone
        current_m = self.state.current_milestone or self.state.roadmap.current_milestone

        # 3. Resolve Next Task ensuring dependency checks
        completed_ids = {t.task_id for t in self.state.tasks if t.completion_state}

        priority_map = {"high": 0, "medium": 1, "low": 2}
        pending_tasks = [t for t in self.state.tasks if not t.completion_state]

        # Filter dependency-free ready tasks
        ready_tasks = []
        for t in pending_tasks:
            # Task dependencies checking
            if all(dep in completed_ids for dep in t.dependencies):
                ready_tasks.append(t)

        if ready_tasks:
            ready_tasks.sort(key=lambda t: priority_map.get(t.priority, 1))
            recommended_task = ready_tasks[0]
            reason = (
                f"Milestone '{current_m or 'Default'}' is active. "
                f"Task ({recommended_task.task_id}) has all dependencies met and is prioritized."
            )
            return current_m or recommended_task.milestone, recommended_task, reason

        # 4. Check Planned Roadmap milestones
        planned = self.state.roadmap.planned_milestones
        if planned:
            # Find first incomplete milestone
            for pm in planned:
                if pm not in self.state.roadmap.completed_milestones:
                    # Let's see if there are tasks for this milestone
                    ms_tasks = [
                        t
                        for t in self.state.tasks
                        if t.milestone == pm and not t.completion_state
                    ]
                    if ms_tasks:
                        # Recommend first task whose deps are satisfied
                        ready_ms_tasks = [
                            t
                            for t in ms_tasks
                            if all(dep in completed_ids for dep in t.dependencies)
                        ]
                        if ready_ms_tasks:
                            ready_ms_tasks.sort(
                                key=lambda t: priority_map.get(t.priority, 1)
                            )
                            reason = f"Activating planned milestone '{pm}' with ready task '{ready_ms_tasks[0].task_id}'."
                            return pm, ready_ms_tasks[0], reason
                    else:
                        reason = f"Transitioning to planned roadmap milestone: '{pm}'."
                        return pm, None, reason

        # If everything is complete, default to the first roadmap milestone if tasks exist
        if planned:
            reason = "Reviewing completed milestones."
            return planned[0], None, reason

        return None, None, "All tasks and milestones are fully completed."

    def generate_work_package(self) -> Dict[str, Any]:
        """Construct the engineering work package details."""
        milestone, task, reason = self.analyze_milestone_and_task()

        if milestone is None and task is None and "Legacy roadmap" in reason:
            return {
                "project_name": self.state.project_name,
                "current_state": "Legacy",
                "active_branch": self.state.active_branch,
                "repository_health": self.state.repository_health,
                "recommended_milestone": "None",
                "recommended_task": None,
                "reason": reason,
                "task_breakdown": ["Run `grandpa roadmap migrate --preview`"],
                "acceptance_criteria": [],
                "affected_areas": [],
                "expected_artifacts": [],
                "validation_plan": [],
                "risk_level": "HIGH",
            }

        # Determine risk level
        risk_level = "LOW"
        if task and getattr(task, "risk_level", None):
            risk_level = task.risk_level.upper()

        if milestone in self.state.roadmap.blocked_milestones or (
            task and task.status == "blocked"
        ):
            risk_level = "HIGH"
        elif task and len(task.dependencies) > 1:
            risk_level = "MEDIUM"

        # Plan task breakdown
        breakdown = []
        acceptance_criteria = []
        affected_areas = []
        expected_artifacts = []
        validation_plan = [
            "pytest tests/",
            "uv run ruff check src tests",
            "python -m compileall -q src tests scripts",
        ]

        if task:
            breakdown = [
                f"Verify dependencies: {task.dependencies or 'None'}",
                f"Implement core functionality for '{task.title}'",
                "Run focused validation checks",
            ]
            if getattr(task, "acceptance_criteria", None):
                acceptance_criteria = task.acceptance_criteria
            if getattr(task, "affected_areas", None):
                affected_areas = task.affected_areas
            if getattr(task, "expected_artifacts", None):
                expected_artifacts = task.expected_artifacts
            if getattr(task, "validation_commands", None) and task.validation_commands:
                validation_plan = task.validation_commands
        else:
            breakdown = ["Define milestone goals", "Establish milestone task list"]
            # Look up milestone criteria if milestone exists
            if milestone and milestone in self.state.roadmap.milestones:
                m = self.state.roadmap.milestones[milestone]
                if getattr(m, "acceptance_criteria", None):
                    acceptance_criteria = m.acceptance_criteria
                if getattr(m, "validation_strategy", None) and m.validation_strategy:
                    validation_plan = m.validation_strategy

        return {
            "project_name": self.state.project_name,
            "current_state": self.state.current_milestone or milestone or "None",
            "active_branch": self.state.active_branch,
            "repository_health": self.state.repository_health,
            "recommended_milestone": milestone or "None",
            "recommended_task": task,
            "reason": reason,
            "task_breakdown": breakdown,
            "acceptance_criteria": acceptance_criteria,
            "affected_areas": affected_areas,
            "expected_artifacts": expected_artifacts,
            "validation_plan": validation_plan,
            "risk_level": risk_level,
        }

    def format_work_package_text(self, wp: Dict[str, Any]) -> str:
        """Format the work package dictionary into standard text layout."""
        lines = []
        lines.append(f"Project: {wp['project_name']}")
        lines.append(f"Current State: {wp['current_state']} / {wp['active_branch']}")
        lines.append(f"Repository Health: {wp['repository_health'].upper()}")
        lines.append("")
        lines.append(f"Recommended Milestone: {wp['recommended_milestone']}")
        lines.append("")
        lines.append("Reason:")
        lines.append(wp["reason"])
        lines.append("")

        # Affected Areas
        if wp["affected_areas"]:
            lines.append("Affected Areas:")
            for area in wp["affected_areas"]:
                lines.append(f"  - {area}")
            lines.append("")

        # Expected Artifacts
        if wp["expected_artifacts"]:
            lines.append("Expected Artifacts:")
            for art in wp["expected_artifacts"]:
                lines.append(f"  - {art}")
            lines.append("")

        lines.append("Tasks:")
        task = wp["recommended_task"]
        if task:
            lines.append(
                f"1. ({task.task_id}) {task.title} (Priority: {task.priority.upper()}, Status: {task.status})"
            )
            for idx, step in enumerate(wp["task_breakdown"], 2):
                lines.append(f"{idx}. {step}")
        else:
            for idx, step in enumerate(wp["task_breakdown"], 1):
                lines.append(f"{idx}. {step}")
        lines.append("")

        # Acceptance Criteria
        if wp["acceptance_criteria"]:
            lines.append("Acceptance Criteria:")
            for ac in wp["acceptance_criteria"]:
                lines.append(f"- {ac}")
            lines.append("")

        lines.append("Validation:")
        for v in wp["validation_plan"]:
            lines.append(f"- {v}")
        lines.append("")
        lines.append("Risk:")
        lines.append(wp["risk_level"])
        return "\n".join(lines)
