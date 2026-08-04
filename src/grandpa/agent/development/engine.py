"""Continuation engine for Autonomous Development Workflow V1."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from grandpa.agent.development.checkpoint import CheckpointManager
from grandpa.agent.development.models import ProjectState, Task
from grandpa.agent.development.tracker import ProjectStateTracker
from grandpa.memory.service import MemoryService


class ContinuationEngine:
    """Orchestrates loading state, repo diagnostics, next task resolution, and plan generation."""

    def __init__(self, project_path: str, project_name: str = "Grandpa") -> None:
        self.project_path = Path(project_path).resolve()
        self.project_name = project_name
        self.tracker = ProjectStateTracker(
            str(self.project_path), project_name=self.project_name
        )
        self.checkpoint_manager = CheckpointManager(str(self.project_path))

    def inspect_repository(self) -> Tuple[str, str]:
        """Detect current active branch and compile health of the project."""
        # 1. Detect branch
        branch = "main"
        try:
            res_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                check=True,
            )
            branch = res_branch.stdout.strip()
        except Exception:
            pass

        # 2. Detect health via python compileall
        health = "healthy"
        try:
            res_compile = subprocess.run(
                ["python", "-m", "compileall", "-q", str(self.project_path)],
                cwd=str(self.project_path),
                capture_output=True,
            )
            if res_compile.returncode != 0:
                health = "unhealthy"
        except Exception:
            health = "unhealthy"

        return branch, health

    def identify_next_task(self, state: ProjectState) -> Optional[Task]:
        """Resolve next pending task based on priority and dependency chain."""
        from grandpa.agent.development.roadmap_generator import is_legacy_roadmap

        if is_legacy_roadmap(state):
            return None
        completed_ids = {t.task_id for t in state.tasks if t.completion_state}

        # Sort tasks by priority: high, medium, low
        priority_map = {"high": 0, "medium": 1, "low": 2}
        pending_tasks = [t for t in state.tasks if not t.completion_state]

        # Check if all dependencies are satisfied
        ready_tasks = []
        for t in pending_tasks:
            if all(dep in completed_ids for dep in t.dependencies):
                ready_tasks.append(t)

        if not ready_tasks:
            return None

        # Sort by priority
        ready_tasks.sort(key=lambda t: priority_map.get(t.priority, 1))
        return ready_tasks[0]

    def continue_project(self) -> Dict[str, Any]:
        """Orchestrate full project loading, diagnostics, next task identification, and planning."""
        # 1. Load project state
        state = self.tracker.load_state()

        # 2. Inspect active repo
        branch, health = self.inspect_repository()
        state.active_branch = branch
        state.repository_health = health
        state.timestamp = time.time()

        # 3. Identify next task
        next_task = self.identify_next_task(state)

        # 4. Generate plan description
        if next_task:
            plan_desc = (
                f"Next task identified: [{next_task.task_id}] '{next_task.title}' "
                f"(Priority: {next_task.priority.upper()}). Dependencies: {next_task.dependencies or 'None'}."
            )
        else:
            plan_desc = "No pending tasks found. All milestone goals are completed."

        # 5. Save state changes
        self.tracker.save_state(state)

        # 6. Memory Integration Sync
        self.sync_to_memory(state, next_task)

        return {
            "project_name": state.project_name,
            "project_path": state.project_path,
            "active_branch": state.active_branch,
            "repository_health": state.repository_health,
            "current_milestone": state.current_milestone,
            "next_milestone": state.next_milestone,
            "next_task": next_task,
            "execution_plan": plan_desc,
        }

    def sync_to_memory(self, state: ProjectState, next_task: Optional[Task]) -> None:
        """Persist project stats to SQLite Memory Service."""
        try:
            svc = MemoryService.get_instance()
            last_milestone = (
                state.roadmap.completed_milestones[-1]
                if state.roadmap.completed_milestones
                else None
            )
            next_task_title = next_task.title if next_task else None

            content = (
                f"Project {state.project_name} at {state.project_path}. "
                f"Milestone: {state.current_milestone or 'None'}. "
                f"Next milestone: {state.next_milestone or 'None'}. "
                f"Health: {state.repository_health}."
            )

            # Store to projects category
            svc.projects.update_project_info(
                project_name=state.project_name,
                content=content,
                project_path=state.project_path,
                latest_feature=state.last_completed_feature,
                next_task=next_task_title,
                metadata={
                    "last_completed_milestone": last_milestone,
                    "next_milestone": state.next_milestone,
                    "project_health": state.repository_health,
                    "continuation_history": [
                        f"Resumed at {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    ],
                },
            )
        except Exception:
            pass
