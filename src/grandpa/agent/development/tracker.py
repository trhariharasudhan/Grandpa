"""Project state tracker and task registry for Autonomous Development Workflow V1."""

from __future__ import annotations

import json
from pathlib import Path

from grandpa.agent.development.models import ProjectState, Roadmap, Task


class ProjectStateTracker:
    """Tracks active milestones, task completions, and repository health state."""

    def __init__(self, project_path: str, project_name: str = "Grandpa") -> None:
        self.project_path = Path(project_path).resolve()
        self.project_name = project_name
        self.state_file = self.project_path / ".grandpa" / "development_state.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        from grandpa.agent.development.checkpoint import CheckpointManager
        self.checkpoint_manager = CheckpointManager(project_path)

    def load_state(self) -> ProjectState:
        """Load project state from disk, initializing it if absent."""
        if not self.state_file.exists():
            # Initialize default state
            state = ProjectState(
                project_name=self.project_name,
                project_path=str(self.project_path),
                roadmap=Roadmap(),
            )
            self.save_state(state)
            return state

        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return ProjectState.from_dict(data)
        except Exception:
            # Fallback initialization on corrupt file
            state = ProjectState(
                project_name=self.project_name,
                project_path=str(self.project_path),
                roadmap=Roadmap(),
            )
            self.save_state(state)
            return state

    def save_state(self, state: ProjectState) -> None:
        """Save the current project state back to disk."""
        self.state_file.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")

    def add_task(self, title: str, priority: str = "medium", dependencies: list[str] = None) -> Task:
        """Add a new task to the Task Registry."""
        state = self.load_state()
        task_id = f"tsk_{len(state.tasks) + 1:03d}"

        task = Task(
            task_id=task_id,
            title=title,
            status="pending",
            priority=priority,
            dependencies=dependencies or [],
            completion_state=False
        )
        state.tasks.append(task)
        self.save_state(state)
        return task

    def update_task_status(self, task_id: str, status: str) -> None:
        """Update task execution status (pending, in_progress, completed, blocked)."""
        state = self.load_state()
        for t in state.tasks:
            if t.task_id == task_id:
                t.status = status
                if status == "completed":
                    t.completion_state = True
                else:
                    t.completion_state = False
                break
        self.save_state(state)

    def add_milestone(self, milestone: str, status: str = "planned") -> None:
        """Add a milestone to the Roadmap."""
        state = self.load_state()
        if status == "completed":
            if milestone not in state.roadmap.completed_milestones:
                state.roadmap.completed_milestones.append(milestone)
        elif status == "planned":
            if milestone not in state.roadmap.planned_milestones:
                state.roadmap.planned_milestones.append(milestone)
        elif status == "blocked":
            if milestone not in state.roadmap.blocked_milestones:
                state.roadmap.blocked_milestones.append(milestone)
        self.save_state(state)

    def start_milestone(self, milestone: str) -> None:
        """Start a planned milestone, updating the current milestone."""
        state = self.load_state()
        roadmap = state.roadmap
        if milestone in roadmap.planned_milestones:
            roadmap.planned_milestones.remove(milestone)
        roadmap.current_milestone = milestone
        state.current_milestone = milestone
        self.save_state(state)

    def complete_milestone(self, milestone: str) -> None:
        """Complete the current milestone, adding it to completed list."""
        state = self.load_state()
        roadmap = state.roadmap
        if roadmap.current_milestone == milestone:
            roadmap.current_milestone = None
            state.current_milestone = None
        if milestone not in roadmap.completed_milestones:
            roadmap.completed_milestones.append(milestone)

        # Populate next milestone if planned ones are available
        if roadmap.planned_milestones:
            state.next_milestone = roadmap.planned_milestones[0]
        else:
            state.next_milestone = None

        self.save_state(state)
