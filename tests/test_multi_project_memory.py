"""Integration and unit tests for Multi-Project Memory V1."""

from __future__ import annotations

import tempfile
from pathlib import Path

import click.testing
import pytest

from grandpa.agent.development import MultiProjectRegistry, ProjectStateTracker
from grandpa.agent.development.engine import ContinuationEngine
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


def test_project_registration_and_switching(temp_workspace) -> None:
    registry_file = temp_workspace / "projects_registry.json"
    registry = MultiProjectRegistry(str(registry_file))

    # 1. Registration
    p1_path = temp_workspace / "ChronoBot"
    p1_path.mkdir()
    p1 = registry.register_project("ChronoBot", str(p1_path), "Time assistant")

    assert p1.project_name == "ChronoBot"
    assert p1.project_id == "prj_chronobot"
    assert registry.active_project_id == "prj_chronobot"

    # 2. Duplicate prevention
    with pytest.raises(ValueError, match="already registered at path"):
        registry.register_project("ChronoBot2", str(p1_path))

    with pytest.raises(ValueError, match="already taken"):
        registry.register_project("ChronoBot", str(temp_workspace / "ChronoBot2"))

    # 3. Register second project
    p2_path = temp_workspace / "MotoCompass"
    p2_path.mkdir()
    registry.register_project("MotoCompass", str(p2_path))

    assert len(registry.list_projects()) == 2
    # Active should still be ChronoBot (since it was active and not switched)
    assert registry.active_project_id == "prj_chronobot"

    # 4. Project switching
    registry.switch_project("prj_motocompass")
    assert registry.active_project_id == "prj_motocompass"
    assert registry.get_active_project().project_name == "MotoCompass"

    # Switch by name (case-insensitive)
    registry.switch_project("chronobot")
    assert registry.active_project_id == "prj_chronobot"


def test_memory_isolation_and_continuation(temp_workspace, setup_memory) -> None:
    registry_file = temp_workspace / "projects_registry.json"
    registry = MultiProjectRegistry(str(registry_file))

    p1_path = temp_workspace / "ChronoBot"
    p2_path = temp_workspace / "MotoCompass"
    registry.create_project("ChronoBot", str(p1_path))
    registry.create_project("MotoCompass", str(p2_path))

    # Add distinct tasks to each project
    tracker1 = ProjectStateTracker(str(p1_path), project_name="ChronoBot")
    tracker1.add_task("Chrono Task 1")

    tracker2 = ProjectStateTracker(str(p2_path), project_name="MotoCompass")
    tracker2.add_task("Moto Task 1")

    # 1. Run continuation on active (ChronoBot)
    registry.switch_project("ChronoBot")
    engine1 = ContinuationEngine(str(p1_path), project_name="ChronoBot")
    res1 = engine1.continue_project()
    assert res1["project_name"] == "ChronoBot"
    assert "Chrono Task 1" in res1["execution_plan"]

    # 2. Switch context and run continuation on MotoCompass
    registry.switch_project("MotoCompass")
    engine2 = ContinuationEngine(str(p2_path), project_name="MotoCompass")
    res2 = engine2.continue_project()
    assert res2["project_name"] == "MotoCompass"
    assert "Moto Task 1" in res2["execution_plan"]

    # Verify database memory entries are isolated
    db_projects = setup_memory.projects.list_projects()
    # Should have separate memory records for ChronoBot and MotoCompass
    proj_names = [p["project_name"] for p in db_projects]
    assert "ChronoBot" in proj_names
    assert "MotoCompass" in proj_names


def test_persistence(temp_workspace) -> None:
    registry_file = temp_workspace / "projects_registry.json"

    # Init first registry instance
    registry1 = MultiProjectRegistry(str(registry_file))
    p1_path = temp_workspace / "ChronoBot"
    p1_path.mkdir()
    registry1.register_project("ChronoBot", str(p1_path))

    # Load from second registry instance
    registry2 = MultiProjectRegistry(str(registry_file))
    assert registry2.active_project_id == "prj_chronobot"
    assert len(registry2.list_projects()) == 1


def test_agent_runtime_multi_project(temp_workspace, setup_memory) -> None:
    # We patch global projects_registry path so AgentRuntime uses our isolated file
    import os

    os.environ["GRANDPA_HOME"] = str(temp_workspace)

    registry = MultiProjectRegistry()
    p1_path = temp_workspace / "ChronoBot"
    p2_path = temp_workspace / "MotoCompass"
    registry.create_project("ChronoBot", str(p1_path))
    registry.create_project("MotoCompass", str(p2_path))

    runtime = AgentRuntime()

    # 1. Switch context via goal
    res_switch = runtime.run("Switch to ChronoBot")
    assert "Switched active project context to 'ChronoBot'" in res_switch.message

    # 2. Check active context
    res_context = runtime.run("Show project context")
    assert "Project Context for 'ChronoBot'" in res_context.message

    # 3. Continue project
    res_continue = runtime.run("Continue project")
    assert "Continuation engine active for 'ChronoBot'" in res_continue.message


def test_cli_commands(temp_workspace, setup_memory) -> None:
    import os

    os.environ["GRANDPA_HOME"] = str(temp_workspace)

    runner = click.testing.CliRunner()

    # 1. Create Command
    p1_path = temp_workspace / "ChronoBot"
    res_create = runner.invoke(
        project_group, ["create", "ChronoBot", str(p1_path), "--desc", "Chronos app"]
    )
    assert res_create.exit_code == 0
    assert "Created and registered project 'ChronoBot'" in res_create.output

    # 2. Register Command
    p2_path = temp_workspace / "MotoCompass"
    p2_path.mkdir()
    res_register = runner.invoke(
        project_group, ["register", "MotoCompass", str(p2_path)]
    )
    assert res_register.exit_code == 0
    assert "Registered project 'MotoCompass'" in res_register.output

    # 3. List Command
    res_list = runner.invoke(project_group, ["list"])
    assert res_list.exit_code == 0
    assert "ChronoBot" in res_list.output
    assert "MotoCompass" in res_list.output

    # 4. Switch Command
    res_switch = runner.invoke(project_group, ["switch", "MotoCompass"])
    assert res_switch.exit_code == 0
    assert "Switched active project context to 'MotoCompass'" in res_switch.output

    # 5. Current Command
    res_current = runner.invoke(project_group, ["current"])
    assert res_current.exit_code == 0
    assert "Active Project: MotoCompass" in res_current.output

    # 6. Context Command
    res_context = runner.invoke(project_group, ["context"])
    assert res_context.exit_code == 0
    assert "Active Project    : MotoCompass" in res_context.output
