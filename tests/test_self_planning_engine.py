"""Upgraded unit and integration tests for Self-Planning Engine V1."""

from __future__ import annotations

import tempfile
from pathlib import Path

import click.testing
import pytest

from grandpa.agent.development.models import Milestone, ProjectState, Roadmap
from grandpa.agent.development.planner import EngineeringPlanner
from grandpa.agent.development.roadmap_generator import (
    RoadmapGenerator,
    classify_goal,
    detect_project_type,
    validate_roadmap,
)
from grandpa.agent.development.tracker import ProjectStateTracker
from grandpa.agent.runtime import AgentRuntime
from grandpa.cli.roadmap_cmd import roadmap_group


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir).resolve()


def test_goal_classification() -> None:
    # 1. Test browser automation goal
    evidence = detect_project_type("/mock")
    assert classify_goal('Build browser automation using playwright', evidence) == "browser_automation"

    # 2. Test FastAPI auth goal
    assert classify_goal('Implement authentication and register routes', evidence) == "authentication"

    # 3. Test React UI goal
    assert classify_goal('Build react frontend view components', evidence) == "frontend_ui"

    # 4. Test unknown goal
    assert classify_goal('Run custom code operations', evidence) == "unknown"


def test_project_stack_detection(temp_workspace) -> None:
    # 1. Test Python / FastAPI project detection
    pyproj = temp_workspace / "pyproject.toml"
    pyproj.touch()
    main_py = temp_workspace / "main.py"
    main_py.write_text("import fastapi\napp = fastapi.FastAPI()", encoding="utf-8")

    evidence = detect_project_type(str(temp_workspace))
    assert "python" in evidence.detected_stack
    assert "fastapi" in evidence.detected_stack
    assert evidence.detected_type in ("Python", "FastAPI")


def test_roadmap_differentiation_and_ids(temp_workspace) -> None:
    state = ProjectState(
        project_name="TestProj",
        project_path=str(temp_workspace),
        tasks=[],
        roadmap=Roadmap()
    )

    generator = RoadmapGenerator(state)

    # 1. Generate browser automation roadmap
    generator.generate_roadmap("Build browser automation using playwright", [])
    ms_keys = list(state.roadmap.milestones.keys())
    assert any("browser_automation" in k for k in ms_keys)
    assert any("ms_browser_automation" in t.milestone for t in state.tasks if t.milestone)

    # 2. Test ID stability
    first_size = len(state.tasks)
    generator.generate_roadmap("Build browser automation using playwright", [])
    # Re-running the same roadmap command should be idempotent and not create duplicate tasks
    assert len(state.tasks) == first_size


def test_validation_and_cycles() -> None:
    state = ProjectState(
        project_name="TestProj",
        project_path="/mock",
        tasks=[],
        roadmap=Roadmap()
    )

    # Create cyclic milestone dependencies
    m1 = Milestone(milestone_id="m1", title="M1", dependencies=["m2"])
    m2 = Milestone(milestone_id="m2", title="M2", dependencies=["m1"])
    state.roadmap.milestones = {"m1": m1, "m2": m2}

    is_valid, errors = validate_roadmap(state)
    assert not is_valid
    assert any("Circular dependency detected in milestones" in err for err in errors)


def test_persistence_and_merge(temp_workspace) -> None:
    tracker = ProjectStateTracker(str(temp_workspace), project_name="PersistedProj")
    state = tracker.load_state()

    generator = RoadmapGenerator(state)
    generator.generate_roadmap("Build browser automation", [])
    tracker.save_state(state)

    # Re-read and verify merge behavior
    tracker2 = ProjectStateTracker(str(temp_workspace))
    state2 = tracker2.load_state()
    assert any("browser_automation" in k for k in state2.roadmap.milestones)


def test_project_engineer_integration(temp_workspace) -> None:
    state = ProjectState(
        project_name="TestProj",
        project_path=str(temp_workspace),
        tasks=[],
        roadmap=Roadmap()
    )
    generator = RoadmapGenerator(state)
    generator.generate_roadmap("Build browser automation", [])

    planner = EngineeringPlanner(state)
    wp = planner.generate_work_package()

    assert wp["project_name"] == "TestProj"
    assert wp["recommended_milestone"] != "None"
    assert wp["validation_plan"] != []


def test_cli_roadmap_commands(temp_workspace) -> None:
    import os
    os.environ["GRANDPA_HOME"] = str(temp_workspace)

    runner = click.testing.CliRunner()

    p_path = temp_workspace / "TestProj"
    from grandpa.cli.project_cmd import project_group
    runner.invoke(project_group, ["create", "TestProj", str(p_path)])

    # 1. Create Roadmap CLI
    res_create = runner.invoke(roadmap_group, ["create", "Build browser automation", "-g", "Open browser safely"])
    assert res_create.exit_code == 0
    assert "Created roadmap successfully" in res_create.output

    # 2. Show Roadmap CLI
    res_show = runner.invoke(roadmap_group, ["show"])
    assert res_show.exit_code == 0
    assert "browser_automation" in res_show.output

    # 3. List Milestones CLI
    res_ms = runner.invoke(roadmap_group, ["milestones"])
    assert res_ms.exit_code == 0
    assert "browser_automation" in res_ms.output

    # 4. Show Graph CLI
    res_graph = runner.invoke(roadmap_group, ["graph"])
    assert res_graph.exit_code == 0
    assert "graph TD" in res_graph.output

    # 5. Expand Milestone CLI
    # Resolve first milestone ID
    tracker = ProjectStateTracker(str(p_path))
    state = tracker.load_state()
    m_id = list(state.roadmap.milestones.keys())[0]

    res_exp = runner.invoke(roadmap_group, ["expand", m_id, "-t", "task_new", "--title", "Custom Action", "-d", "task_browser_automation_launch_browser"])
    assert res_exp.exit_code == 0
    assert "Successfully expanded milestone" in res_exp.output

    # 6. Validate CLI
    res_val = runner.invoke(roadmap_group, ["validate"])
    assert res_val.exit_code == 0
    assert "Roadmap is valid" in res_val.output


def test_agent_runtime_roadmap_goals(temp_workspace) -> None:
    import os
    os.environ["GRANDPA_HOME"] = str(temp_workspace)

    p_path = temp_workspace / "TestProj"
    tracker = ProjectStateTracker(str(p_path), project_name="TestProj")
    tracker.save_state(tracker.load_state())

    from grandpa.agent.development import MultiProjectRegistry
    registry = MultiProjectRegistry()
    registry.register_project("TestProj", str(p_path))

    runtime = AgentRuntime()

    runtime.run("Switch to TestProj")

    # 1. Create roadmap goal
    res_create = runtime.run("Create roadmap for browser automation")
    assert "Created roadmap successfully" in res_create.message

    # 2. What should I build next goal
    res_next = runtime.run("What should I build next")
    assert "Recommendation" in res_next.message


def test_roadmap_migration_full(temp_workspace) -> None:
    from grandpa.agent.development.models import Milestone, Task
    from grandpa.agent.development.roadmap_generator import (
        is_legacy_roadmap,
        migrate_legacy_roadmap,
    )

    # Setup legacy project state
    state = ProjectState(
        project_name="TestProj",
        project_path=str(temp_workspace),
        tasks=[],
        roadmap=Roadmap()
    )

    # 1. Add legacy placeholder milestone and task
    state.roadmap.milestones["ms_core"] = Milestone(
        milestone_id="ms_core",
        title="Core Infrastructure Implementation",
        description="Generic template",
        status="pending",
    )

    tsk_placeholder = Task(
        task_id="tsk_init",
        title="Initialize Repository Structures",
        status="pending",
        milestone="ms_core",
    )
    state.tasks.append(tsk_placeholder)

    # Add a user-created milestone (should be preserved)
    state.roadmap.milestones["ms_user_custom"] = Milestone(
        milestone_id="ms_user_custom",
        title="Real User Milestone",
        description="Preserved",
        status="pending",
    )

    tsk_user = Task(
        task_id="tsk_user_custom_action",
        title="Real User Task",
        status="pending",
        milestone="ms_user_custom",
    )
    state.tasks.append(tsk_user)

    # Check requirement 1: Legacy detection
    assert is_legacy_roadmap(state) is True

    # Check requirement 2: Preview makes no changes
    import copy
    state_before = copy.deepcopy(state)
    simulated_state, changes = migrate_legacy_roadmap(copy.deepcopy(state))
    # State before and after simulated migration should be unchanged
    assert state.roadmap.roadmap_schema_version == 1
    assert "ms_core" in state.roadmap.milestones
    assert any(t.task_id == "tsk_init" for t in state.tasks)

    # Check simulated changes details
    assert "ms_core" in changes["archived_milestones"]
    assert "tsk_init" in changes["archived_tasks"]
    assert "ms_self_planning_stabilization" in changes["added_milestones"]

    # Check requirement 3: Apply archives old state & modifies correctly
    migrated_state, changes_applied = migrate_legacy_roadmap(state)

    # Version update
    assert migrated_state.roadmap.roadmap_schema_version == 2
    assert migrated_state.roadmap.migrated_from_version == 1
    assert migrated_state.roadmap.migration_timestamp is not None

    # Legacy items removed
    assert "ms_core" not in migrated_state.roadmap.milestones
    assert not any(t.task_id == "tsk_init" for t in migrated_state.tasks)

    # Completed/User-created items preserved
    assert "ms_user_custom" in migrated_state.roadmap.milestones
    assert any(t.task_id == "tsk_user_custom_action" for t in migrated_state.tasks)

    # Archived data recorded in history
    assert any(h.get("action") == "migrate_archive_legacy" for h in migrated_state.roadmap.planning_history)

    # Check requirement 8: Project Engineer rejects legacy roadmap
    planner_legacy = EngineeringPlanner(state_before)
    milestone, task, reason = planner_legacy.analyze_milestone_and_task()
    assert milestone is None
    assert task is None
    assert "Legacy roadmap detected" in reason

    # Check requirement 9: Project Engineer uses migrated roadmap
    planner_migrated = EngineeringPlanner(migrated_state)
    m_mig, t_mig, r_mig = planner_migrated.analyze_milestone_and_task()
    assert m_mig == "ms_self_planning_stabilization"
    assert t_mig is not None
    assert t_mig.task_id == "task_self_planning_stabilization_verify"

    # Check requirement 11: Idempotency (repeated migration does nothing)
    assert is_legacy_roadmap(migrated_state) is False

    # Check requirement 12: No duplicates (length of milestones matching title count)
    milestones_list = list(migrated_state.roadmap.milestones.keys())
    assert len(milestones_list) == len(set(milestones_list))
