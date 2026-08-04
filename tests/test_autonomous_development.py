"""Integration and unit tests for Autonomous Development Workflow V1."""

from __future__ import annotations

import tempfile
from pathlib import Path

import click.testing
import pytest

from grandpa.agent.development.engine import ContinuationEngine
from grandpa.agent.development.tracker import ProjectStateTracker
from grandpa.agent.runtime import AgentRuntime
from grandpa.cli.project_cmd import project_group
from grandpa.memory.service import MemoryService


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir).resolve()


@pytest.fixture
def setup_memory():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_memory.db"
        svc = MemoryService.get_instance(db_path=str(db_path))
        yield svc
        MemoryService.reset_instance()


def test_state_tracking_and_tasks(temp_workspace) -> None:
    tracker = ProjectStateTracker(str(temp_workspace), project_name="TestProj")
    state = tracker.load_state()

    assert state.project_name == "TestProj"
    assert state.project_path == str(temp_workspace)
    assert not state.tasks

    # 1. Add tasks
    t1 = tracker.add_task("First task", priority="high")
    assert t1.task_id == "tsk_001"
    assert t1.priority == "high"
    assert not t1.dependencies

    t2 = tracker.add_task("Second task", priority="medium", dependencies=["tsk_001"])
    assert t2.task_id == "tsk_002"
    assert t2.dependencies == ["tsk_001"]

    # Reload state to check persistence
    state2 = tracker.load_state()
    assert len(state2.tasks) == 2
    assert state2.tasks[1].task_id == "tsk_002"

    # 2. Update task status
    tracker.update_task_status("tsk_001", "completed")
    state3 = tracker.load_state()
    assert state3.tasks[0].completion_state is True
    assert state3.tasks[0].status == "completed"


def test_roadmap_logic(temp_workspace) -> None:
    tracker = ProjectStateTracker(str(temp_workspace))

    # 1. Add milestones
    tracker.add_milestone("Milestone A", "completed")
    tracker.add_milestone("Milestone B", "planned")
    tracker.add_milestone("Milestone C", "planned")
    tracker.add_milestone("Milestone D", "blocked")

    state = tracker.load_state()
    assert "Milestone A" in state.roadmap.completed_milestones
    assert "Milestone B" in state.roadmap.planned_milestones
    assert "Milestone D" in state.roadmap.blocked_milestones

    # 2. Start milestone
    tracker.start_milestone("Milestone B")
    state2 = tracker.load_state()
    assert state2.roadmap.current_milestone == "Milestone B"
    assert state2.current_milestone == "Milestone B"
    assert "Milestone B" not in state2.roadmap.planned_milestones

    # 3. Complete milestone
    tracker.complete_milestone("Milestone B")
    state3 = tracker.load_state()
    assert state3.roadmap.current_milestone is None
    assert "Milestone B" in state3.roadmap.completed_milestones
    assert state3.next_milestone == "Milestone C"


def test_checkpoints(temp_workspace) -> None:
    tracker = ProjectStateTracker(str(temp_workspace))
    state = tracker.load_state()
    tracker.add_task("Task 1")

    # 1. Save checkpoint
    checkpoint = tracker.checkpoint_manager.save_checkpoint(state, "chk_test")
    assert checkpoint.checkpoint_id == "chk_test"
    assert "chk_test" in tracker.checkpoint_manager.list_checkpoints()

    # 2. Load checkpoint
    loaded = tracker.checkpoint_manager.load_checkpoint("chk_test")
    assert loaded.checkpoint_id == "chk_test"
    assert loaded.state.project_name == "Grandpa"

    # 3. Validate checkpoint
    assert tracker.checkpoint_manager.validate_checkpoint(
        loaded, loaded.active_branch, loaded.repository_health
    )
    # branch mismatch
    assert not tracker.checkpoint_manager.validate_checkpoint(
        loaded, "other-branch", loaded.repository_health
    )
    # health mismatch
    assert not tracker.checkpoint_manager.validate_checkpoint(
        loaded, loaded.active_branch, "unhealthy"
    )


def test_continuation_engine_and_memory(temp_workspace, setup_memory) -> None:
    engine = ContinuationEngine(str(temp_workspace), project_name="MemoryProj")
    tracker = engine.tracker

    # Set up some tasks
    tracker.add_task("Step 1", priority="medium")
    tracker.add_task("Step 2", priority="high", dependencies=["tsk_001"])

    # 1. Get next task - should resolve t1 first (dependencies of t2 not met)
    state = tracker.load_state()
    next_task = engine.identify_next_task(state)
    assert next_task is not None
    assert next_task.task_id == "tsk_001"

    # Complete t1
    tracker.update_task_status("tsk_001", "completed")
    state = tracker.load_state()
    next_task2 = engine.identify_next_task(state)
    assert next_task2 is not None
    assert next_task2.task_id == "tsk_002"

    # 2. Continue project
    res = engine.continue_project()
    assert res["project_name"] == "MemoryProj"
    assert "Next task identified" in res["execution_plan"]

    # 3. Verify memory integration
    projects = setup_memory.projects.list_projects()
    assert len(projects) == 1
    assert projects[0]["project_name"] == "MemoryProj"
    assert projects[0]["next_task"] == "Step 2"


def test_agent_runtime_continuation(temp_workspace, setup_memory) -> None:
    # Set up some task state in workspace
    tracker = ProjectStateTracker(str(temp_workspace), project_name="RuntimeProj")
    tracker.add_task("Complete project setup")

    # Override target project path in runtime test (via mock or default resolution)
    # In AgentRuntime.run, it will use temp_workspace if D:\Grandpa does not exist,
    # but we can also copy D:\Grandpa behavior by temporarily patching Path.cwd()
    runtime = AgentRuntime()
    # Mock continue grandpa project goal execution
    res = runtime.run("Continue Grandpa project")
    assert res.context.project_memory is not None
    assert "Continuation engine active" in res.message


def test_cli_commands(temp_workspace, setup_memory) -> None:
    runner = click.testing.CliRunner()

    # Initialize some dummy project files
    tracker = ProjectStateTracker(str(temp_workspace), project_name="CliProj")
    tracker.add_task("A task")
    tracker.add_milestone("Milestone A", "planned")
    tracker.start_milestone("Milestone A")

    # We monkeypatch the _get_project_path inside click tests
    import grandpa.cli.project_cmd

    original_path_getter = grandpa.cli.project_cmd._get_project_path
    grandpa.cli.project_cmd._get_project_path = lambda: str(temp_workspace)

    try:
        # 1. Status Command
        res = runner.invoke(project_group, ["status"])
        assert res.exit_code == 0
        assert "CliProj" in res.output

        # 2. Roadmap Command
        res = runner.invoke(project_group, ["roadmap"])
        assert res.exit_code == 0
        assert "Milestone A" in res.output

        # 3. Next Command
        res = runner.invoke(project_group, ["next"])
        assert res.exit_code == 0
        assert "A task" in res.output

        # 4. Checkpoint Save Command
        res = runner.invoke(project_group, ["checkpoint", "save", "--id", "backup_1"])
        assert res.exit_code == 0
        assert "Saved checkpoint 'backup_1'" in res.output

        # 5. Checkpoint Load Command
        res = runner.invoke(project_group, ["checkpoint", "load", "backup_1"])
        assert res.exit_code == 0
        assert "Restored project state from checkpoint 'backup_1'" in res.output

        # 6. Resume Command
        res = runner.invoke(project_group, ["resume"])
        assert res.exit_code == 0
        assert "Resuming project" in res.output
    finally:
        grandpa.cli.project_cmd._get_project_path = original_path_getter
