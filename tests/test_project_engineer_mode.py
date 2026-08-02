"""Unit and integration tests for Project Engineer Mode V1."""

from __future__ import annotations

import tempfile
from pathlib import Path

import click.testing
import pytest

from grandpa.agent.development.models import ProjectState, Roadmap, Task
from grandpa.agent.development.planner import EngineeringPlanner
from grandpa.agent.development.tracker import ProjectStateTracker
from grandpa.agent.runtime import AgentRuntime
from grandpa.cli.project_cmd import project_group


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir).resolve()


def test_milestone_and_task_prioritization() -> None:
    # 1. Test standard dependency checking and current milestone prioritization
    roadmap = Roadmap(
        completed_milestones=[],
        current_milestone="Milestone_1",
        planned_milestones=["Milestone_2"],
        blocked_milestones=[]
    )
    t1 = Task(task_id="t1", title="Task 1", completion_state=False, dependencies=[], priority="medium")
    t2 = Task(task_id="t2", title="Task 2", completion_state=False, dependencies=["t1"], priority="high")

    state = ProjectState(
        project_name="TestProj",
        project_path="/mock",
        tasks=[t1, t2],
        roadmap=roadmap
    )

    planner = EngineeringPlanner(state)
    m, task, reason = planner.analyze_milestone_and_task()

    # Milestone 1 should be active, t1 should be recommended because t2 depends on t1
    assert m == "Milestone_1"
    assert task is not None
    assert task.task_id == "t1"
    assert "dependencies met" in reason

    # Complete t1, now t2 should be recommended
    t1.completion_state = True
    planner = EngineeringPlanner(state)
    m, task, reason = planner.analyze_milestone_and_task()
    assert task.task_id == "t2"


def test_blocker_prioritization() -> None:
    # 1. Blocked milestone check
    roadmap = Roadmap(
        completed_milestones=[],
        current_milestone="Milestone_1",
        planned_milestones=["Milestone_2"],
        blocked_milestones=["Milestone_Blocked"]
    )
    state = ProjectState(
        project_name="TestProj",
        project_path="/mock",
        tasks=[],
        roadmap=roadmap
    )

    planner = EngineeringPlanner(state)
    m, task, reason = planner.analyze_milestone_and_task()
    assert m == "Milestone_Blocked"
    assert task is None
    assert "Resolving blocker" in reason

    # 2. Blocked task check
    roadmap.blocked_milestones = []
    t_blocked = Task(task_id="t_blocked", title="Blocked task", completion_state=False, dependencies=[], status="blocked")
    state.tasks = [t_blocked]
    planner = EngineeringPlanner(state)
    m, task, reason = planner.analyze_milestone_and_task()
    assert task.task_id == "t_blocked"
    assert "Resolving blocked task" in reason


def test_work_package_generation() -> None:
    roadmap = Roadmap(
        completed_milestones=[],
        current_milestone="Milestone_1",
        planned_milestones=["Milestone_2"],
        blocked_milestones=[]
    )
    t1 = Task(task_id="t1", title="Task 1", completion_state=False, dependencies=[], priority="medium")
    state = ProjectState(
        project_name="TestProj",
        project_path="/mock",
        tasks=[t1],
        roadmap=roadmap,
        active_branch="main",
        repository_health="healthy"
    )

    planner = EngineeringPlanner(state)
    wp = planner.generate_work_package()

    assert wp["project_name"] == "TestProj"
    assert wp["recommended_milestone"] == "Milestone_1"
    assert wp["recommended_task"].task_id == "t1"
    assert wp["risk_level"] == "LOW"

    # Verify risk escalation (high risk when blocked)
    t1.status = "blocked"
    wp_blocked = planner.generate_work_package()
    assert wp_blocked["risk_level"] == "HIGH"


def test_cli_engineer_commands(temp_workspace) -> None:
    import os
    os.environ["GRANDPA_HOME"] = str(temp_workspace)

    runner = click.testing.CliRunner()

    # Create project context
    p_path = temp_workspace / "TestProj"
    runner.invoke(project_group, ["create", "TestProj", str(p_path)])

    # 1. Run plan command
    res_plan = runner.invoke(project_group, ["plan"])
    assert res_plan.exit_code == 0
    assert "Recommended Milestone" in res_plan.output

    # 2. Run next-task command
    res_next = runner.invoke(project_group, ["next-task"])
    assert res_next.exit_code == 0
    assert "Next Task" in res_next.output or "No tasks" in res_next.output

    # 3. Run work-package command
    res_wp = runner.invoke(project_group, ["work-package"])
    assert res_wp.exit_code == 0
    assert "Project: TestProj" in res_wp.output
    assert "Validation:" in res_wp.output

    # 4. Run blockers command
    res_bl = runner.invoke(project_group, ["blockers"])
    assert res_bl.exit_code == 0
    assert "Blocked Milestones:" in res_bl.output
    assert "Blocked Tasks:" in res_bl.output


def test_agent_runtime_engineer_goals(temp_workspace) -> None:
    import os
    os.environ["GRANDPA_HOME"] = str(temp_workspace)

    # Setup project context
    p_path = temp_workspace / "TestProj"
    tracker = ProjectStateTracker(str(p_path), project_name="TestProj")
    tracker.save_state(tracker.load_state())

    from grandpa.agent.development import MultiProjectRegistry
    registry = MultiProjectRegistry()
    registry.register_project("TestProj", str(p_path))

    runtime = AgentRuntime()

    # 1. Switch project
    runtime.run("Switch to TestProj")

    # 2. Plan next milestone goal
    res_plan = runtime.run("Plan next milestone")
    assert "Recommended Milestone" in res_plan.message

    # 3. Generate work package goal
    res_wp = runtime.run("Generate work package")
    assert "Project: TestProj" in res_wp.message
