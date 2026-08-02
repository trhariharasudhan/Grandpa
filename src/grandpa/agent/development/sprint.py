"""Sprint Runner Engine for Autonomous Sprint Runner V1."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from grandpa.agent.development.planner import EngineeringPlanner
from grandpa.agent.development.tracker import ProjectStateTracker
from grandpa.agent.execution.command_catalog import (
    DiagnosticCommand,
    run_catalog_command,
)


@dataclass
class Sprint:
    project_name: str
    project_path: str
    task_id: str
    milestone_id: str
    status: str = "previewed"  # previewed, running, paused, completed, cancelled
    approval_state: str = "pending"  # pending, approved, rejected
    sprint_plan: List[str] = field(default_factory=list)
    risk_level: str = "LOW"
    validation_commands: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    execution_result: Optional[str] = None
    checkpoint_id: Optional[str] = None
    current_step_idx: int = 0
    retries_left: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Sprint:
        return cls(
            project_name=data["project_name"],
            project_path=data["project_path"],
            task_id=data["task_id"],
            milestone_id=data["milestone_id"],
            status=data.get("status", "previewed"),
            approval_state=data.get("approval_state", "pending"),
            sprint_plan=data.get("sprint_plan", []),
            risk_level=data.get("risk_level", "LOW"),
            validation_commands=data.get("validation_commands", []),
            timestamp=data.get("timestamp", time.time()),
            execution_result=data.get("execution_result"),
            checkpoint_id=data.get("checkpoint_id"),
            current_step_idx=data.get("current_step_idx", 0),
            retries_left=data.get("retries_left", 3),
        )


class SprintRunner:
    """Manages sprint execution lifecycle for the active project."""

    def __init__(self, project_path: str, project_name: str = "Grandpa") -> None:
        self.project_path = Path(project_path).resolve()
        self.project_name = project_name
        self.sprint_file = self.project_path / ".grandpa" / "sprint_state.json"
        self.sprint_file.parent.mkdir(parents=True, exist_ok=True)
        self.tracker = ProjectStateTracker(project_path, project_name=project_name)

    def load_sprint(self) -> Optional[Sprint]:
        """Load current sprint state from disk."""
        if not self.sprint_file.exists():
            return None
        try:
            data = json.loads(self.sprint_file.read_text(encoding="utf-8"))
            return Sprint.from_dict(data)
        except Exception:
            return None

    def save_sprint(self, sprint: Sprint) -> None:
        """Save the sprint state back to disk."""
        self.sprint_file.write_text(json.dumps(sprint.to_dict(), indent=2), encoding="utf-8")

    def _parse_validation_command(self, cmd_str: str) -> List[str]:
        """Map generic command strings to safe allowlisted lists."""
        parts = cmd_str.strip().split()
        if not parts:
            return []
        if parts[0] == "pytest":
            parts = ["uv", "run"] + parts
        elif parts[0] == "ruff" or (len(parts) > 1 and parts[:2] == ["ruff", "check"]):
            parts = ["uv", "run"] + parts
        return parts

    def preview_sprint(self) -> Tuple[Sprint, str]:
        """Inspect workspace and select the next task to generate a sprint plan preview."""
        state = self.tracker.load_state()

        from grandpa.agent.development.roadmap_generator import is_legacy_roadmap
        if is_legacy_roadmap(state):
            return None, "Legacy roadmap detected. Run `grandpa roadmap migrate` first."

        planner = EngineeringPlanner(state)
        milestone, task, reason = planner.analyze_milestone_and_task()
        if not task:
            return None, f"No pending tasks available for sprint. Reason: {reason}"

        wp = planner.generate_work_package()

        sprint_plan = [
            f"1. Verify task dependencies for '{task.task_id}' ({task.title})",
            f"2. Apply code modifications for '{task.title}'",
            f"3. Run validation commands: {', '.join(wp['validation_plan'])}",
        ]

        sprint = Sprint(
            project_name=self.project_name,
            project_path=str(self.project_path),
            task_id=task.task_id,
            milestone_id=milestone or "Default",
            status="previewed",
            approval_state="pending",
            sprint_plan=sprint_plan,
            risk_level=wp["risk_level"],
            validation_commands=wp["validation_plan"],
            current_step_idx=0,
            retries_left=3,
        )
        self.save_sprint(sprint)
        return sprint, "Sprint preview created successfully."

    def start_sprint(self, auto_approve: bool = False) -> Tuple[Optional[Sprint], str]:
        """Start or resume the active previewed sprint, validating dependencies and running checks."""
        sprint = self.load_sprint()
        if not sprint:
            sprint, msg = self.preview_sprint()
            if not sprint:
                return None, msg

        if sprint.status in ("completed", "cancelled"):
            return sprint, f"Sprint is already in a terminal state: {sprint.status.upper()}."

        if sprint.status == "paused":
            sprint.status = "running"
            self.save_sprint(sprint)
            return self.run_sprint_loop(sprint)

        if not auto_approve and sprint.approval_state != "approved":
            return sprint, "Sprint requires approval. Run 'grandpa sprint start --approve' or set approval."

        sprint.approval_state = "approved"
        sprint.status = "running"
        self.save_sprint(sprint)

        state_obj = self.tracker.load_state()
        checkpoint_id = f"chk_pre_sprint_{sprint.task_id}_{int(time.time())}"
        self.tracker.checkpoint_manager.save_checkpoint(state_obj, checkpoint_id)
        sprint.checkpoint_id = checkpoint_id
        self.save_sprint(sprint)

        return self.run_sprint_loop(sprint)

    def pause_sprint(self) -> Tuple[Optional[Sprint], str]:
        """Pause the currently running sprint."""
        sprint = self.load_sprint()
        if not sprint:
            return None, "No active sprint found."
        if sprint.status != "running":
            return sprint, f"Sprint status is '{sprint.status.upper()}', cannot pause."
        sprint.status = "paused"
        self.save_sprint(sprint)
        return sprint, "Sprint paused successfully."

    def resume_sprint(self) -> Tuple[Optional[Sprint], str]:
        """Resume the paused sprint."""
        sprint = self.load_sprint()
        if not sprint:
            return None, "No active sprint found."
        if sprint.status != "paused":
            return sprint, f"Sprint status is '{sprint.status.upper()}', cannot resume."
        sprint.status = "running"
        self.save_sprint(sprint)
        return self.run_sprint_loop(sprint)

    def cancel_sprint(self) -> Tuple[Optional[Sprint], str]:
        """Cancel the active sprint, rolling back to pre-sprint checkpoint."""
        sprint = self.load_sprint()
        if not sprint:
            return None, "No active sprint found."
        if sprint.status in ("completed", "cancelled"):
            return sprint, f"Sprint is already in a terminal state: {sprint.status.upper()}."

        sprint.status = "cancelled"
        self.save_sprint(sprint)

        if sprint.checkpoint_id:
            success, msg = self.tracker.checkpoint_manager.restore_checkpoint(sprint.checkpoint_id)
            if success:
                return sprint, f"Sprint cancelled. Restored checkpoint '{sprint.checkpoint_id}' successfully."
            return sprint, f"Sprint cancelled but failed to restore checkpoint: {msg}"

        return sprint, "Sprint cancelled successfully."

    def run_sprint_loop(self, sprint: Sprint) -> Tuple[Sprint, str]:
        """Core loop executing sprint steps sequentially with boundary checks."""
        state = self.tracker.load_state()
        task = next((t for t in state.tasks if t.task_id == sprint.task_id), None)

        if not task:
            sprint.status = "cancelled"
            sprint.execution_result = "Task not found in project state."
            self.save_sprint(sprint)
            return sprint, "Sprint cancelled: task not found."

        if sprint.current_step_idx == 0:
            completed_ids = {t.task_id for t in state.tasks if t.completion_state}
            unmet = [dep for dep in task.dependencies if dep not in completed_ids]
            if unmet:
                sprint.status = "paused"
                sprint.execution_result = f"Blocked: unmet dependencies {unmet}"
                self.save_sprint(sprint)
                return sprint, f"Sprint blocked by unmet dependencies: {unmet}"
            sprint.current_step_idx = 1
            self.save_sprint(sprint)

        sprint = self.load_sprint()
        if sprint.status != "running":
            return sprint, f"Sprint execution stopped: state is {sprint.status.upper()}."

        if sprint.current_step_idx == 1:
            sprint.current_step_idx = 2
            self.save_sprint(sprint)

        sprint = self.load_sprint()
        if sprint.status != "running":
            return sprint, f"Sprint execution stopped: state is {sprint.status.upper()}."

        if sprint.current_step_idx == 2:
            failures = []
            for cmd_str in sprint.validation_commands:
                args = self._parse_validation_command(cmd_str)
                if not args:
                    continue
                cmd = DiagnosticCommand(args=args, cwd=str(self.project_path))
                res = run_catalog_command(cmd)
                if res.exit_code != 0:
                    failures.append(f"Command '{cmd_str}' failed with code {res.exit_code}.")

            if failures:
                sprint.retries_left -= 1
                if sprint.retries_left > 0:
                    sprint.status = "paused"
                    sprint.execution_result = f"Validation failures: {failures}. Retries left: {sprint.retries_left}."
                    self.save_sprint(sprint)
                    return sprint, "Sprint paused due to validation failures. Run 'resume' to retry."
                else:
                    sprint.status = "completed"
                    sprint.execution_result = f"Failed. Validation failures: {failures}."
                    self.save_sprint(sprint)
                    self.tracker.update_task_status(task.task_id, "blocked")
                    return sprint, f"Sprint finished with failures: {failures}."

            sprint.status = "completed"
            sprint.execution_result = "Success. All validation commands passed."
            self.save_sprint(sprint)

            self.tracker.update_task_status(task.task_id, "completed")

            state = self.tracker.load_state()
            ms_tasks = [t for t in state.tasks if t.milestone == sprint.milestone_id]
            if ms_tasks and all(t.completion_state for t in ms_tasks):
                self.tracker.add_milestone(sprint.milestone_id, "completed")

            state_obj = self.tracker.load_state()
            post_chk_id = f"chk_post_sprint_{sprint.task_id}_{int(time.time())}"
            self.tracker.checkpoint_manager.save_checkpoint(state_obj, post_chk_id)

            try:
                from grandpa.memory.service import MemoryService
                svc = MemoryService.get_instance()
                svc.remember(
                    content=f"Sprint completed for task {sprint.task_id} in project {self.project_name}.",
                    category="project",
                    project_name=self.project_name,
                    key=f"sprint_{sprint.task_id}_completed",
                )
                svc.preferences.set_preference("last_sprint_task_completed", sprint.task_id)
            except Exception:
                pass

        return sprint, "Sprint execution loop completed successfully."
