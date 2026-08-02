"""Unit and integration tests for Autonomous Sprint Runner V1."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from grandpa.agent.development.models import Task
from grandpa.agent.development.sprint import SprintRunner
from grandpa.agent.development.tracker import ProjectStateTracker


@pytest.fixture
def temp_project():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        p_path = Path(tmpdir) / "sprint_project"
        p_path.mkdir()
        yield p_path


def test_sprint_runner_preview_and_lifecycle(temp_project) -> None:
    # 1. Initialize project tracker
    tracker = ProjectStateTracker(str(temp_project), project_name="SprintProject")

    # 2. Seed project state with roadmap and tasks
    state = tracker.load_state()
    state.active_branch = "main"
    state.repository_health = "healthy"
    from grandpa.agent.development.models import Milestone
    state.roadmap.current_milestone = "ms_core"
    state.roadmap.milestones = {"ms_core": Milestone(milestone_id="ms_core", title="Core Milestone", status="in_progress")}
    state.roadmap.roadmap_schema_version = 2

    task_init = Task(
        task_id="tsk_init",
        title="Initialize structures",
        milestone="ms_core",
        priority="high",
        dependencies=[],
        description="Task 1 description",
    )
    task_main = Task(
        task_id="tsk_main",
        title="Core implementation",
        milestone="ms_core",
        priority="medium",
        dependencies=["tsk_init"],
        description="Task 2 description",
    )
    state.tasks = [task_init, task_main]
    tracker.save_state(state)

    runner = SprintRunner(str(temp_project), project_name="SprintProject")

    # 3. Preview sprint (should select first task: tsk_init)
    sprint, msg = runner.preview_sprint()
    assert sprint is not None
    assert sprint.task_id == "tsk_init"
    assert sprint.status == "previewed"
    assert sprint.approval_state == "pending"

    # 4. Start sprint (should set running, run checks, and complete because we mock validation commands to be empty or pass)
    # Let's set validation commands to empty list to verify status transition
    sprint.validation_commands = []
    runner.save_sprint(sprint)

    res_sprint, msg = runner.start_sprint(auto_approve=True)
    assert res_sprint is not None
    assert res_sprint.status == "completed"
    assert "Success" in res_sprint.execution_result

    # 5. Verify tracker state got updated: tsk_init is completed
    updated_state = tracker.load_state()
    t_init = next(t for t in updated_state.tasks if t.task_id == "tsk_init")
    assert t_init.completion_state
    assert t_init.status == "completed"

    # 6. Preview next task (tsk_main)
    sprint2, msg2 = runner.preview_sprint()
    assert sprint2 is not None
    assert sprint2.task_id == "tsk_main"

    # Pause sprint
    runner.save_sprint(sprint2)
    sprint2.status = "running"
    runner.save_sprint(sprint2)
    runner.pause_sprint()

    sprint_check = runner.load_sprint()
    assert sprint_check.status == "paused"

    # Cancel sprint (should restore pre-sprint checkpoint if checkpoint exists)
    sprint_check.checkpoint_id = "chk_pre_sprint_tsk_main_test"
    tracker.checkpoint_manager.save_checkpoint(state, sprint_check.checkpoint_id)
    runner.save_sprint(sprint_check)

    runner.cancel_sprint()
    assert runner.load_sprint().status == "cancelled"
