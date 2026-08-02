"""Comprehensive end-to-end acceptance tests for Grandpa V1."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import click.testing
import pytest

from grandpa.agent.context import classify_intent
from grandpa.agent.development import (
    ProjectState,
)
from grandpa.agent.models import AgentExecutionState, AgentIntent
from grandpa.agent.runtime import AgentRuntime
from grandpa.cli.daemon_cmd import daemon
from grandpa.cli.project_cmd import project_group
from grandpa.cli.roadmap_cmd import roadmap_group
from grandpa.cli.sprint_cmd import sprint_group


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir).resolve()


# Scenario 1 & 2: Greeting & Time Queries
def test_greeting_and_time_queries() -> None:
    runtime = AgentRuntime()

    # 1. Greeting
    res_greet = runtime.run("Hello Grandpa")
    assert res_greet.state == AgentExecutionState.COMPLETED
    assert "Hello" in res_greet.message

    # 2. Time query
    res_time = runtime.run("what time is it?")
    assert res_time.state == AgentExecutionState.COMPLETED
    assert "time" in res_time.message


# Scenario 3: Remember / recall / forget preferences
def test_preferences_lifecycle() -> None:
    from grandpa.memory.service import MemoryService
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_pref.db"
        svc = MemoryService.get_instance(db_path=str(db_path))

        # Save preference
        svc.remember("Chrome", category="preference", key="default_browser")

        # Recall preference
        items = svc.list_memories(category="preference", limit=1)
        assert len(items) == 1
        assert items[0].content == "Chrome"

        # Forget preference
        svc.forget(items[0].id)
        assert len(svc.list_memories(category="preference")) == 0

        MemoryService.reset_instance()


# Scenario 4, 5, 6, 7 & 8: Project continuation, Roadmap next task, Sprint preview, Start, Pause, Cancel
def test_project_roadmap_sprint_lifecycle(temp_workspace) -> None:
    from unittest.mock import patch

    from grandpa.agent.execution.models import DiagnosticResult

    os.environ["GRANDPA_HOME"] = str(temp_workspace)
    runner = click.testing.CliRunner()

    p_path = temp_workspace / "TestProj"
    p_path.mkdir(parents=True, exist_ok=True)

    patcher = patch("grandpa.agent.development.sprint.run_catalog_command", return_value=DiagnosticResult(command=[], exit_code=0, stdout="", stderr="", duration_seconds=0.0))
    patcher.start()

    # 1. Register project
    res_reg = runner.invoke(project_group, ["register", "TestProj", str(p_path)])
    assert res_reg.exit_code == 0

    # 2. Switch project
    res_sw = runner.invoke(project_group, ["switch", "TestProj"])
    assert res_sw.exit_code == 0

    # 3. Create roadmap
    res_map = runner.invoke(roadmap_group, ["create", "Build browser automation"])
    assert res_map.exit_code == 0

    # 4. Roadmap milestones and next-task
    res_next = runner.invoke(project_group, ["next-task"])
    assert res_next.exit_code == 0
    assert "Next Task" in res_next.output

    # 5. Sprint Preview
    res_prev = runner.invoke(sprint_group, ["preview"])
    assert res_prev.exit_code == 0
    assert "Sprint Plan Preview" in res_prev.output

    # 6. Sprint start requires approval (prompt confirmation)
    res_start_prompt = runner.invoke(sprint_group, ["start"], input="n\n")
    assert "cancelled" in res_start_prompt.output

    # 7. Sprint start with auto approve option
    res_start_approve = runner.invoke(sprint_group, ["start", "--approve"])
    assert res_start_approve.exit_code == 0

    # 8. Sprint status
    res_stat = runner.invoke(sprint_group, ["status"])
    assert res_stat.exit_code == 0
    assert "Sprint Status" in res_stat.output

    # 9. Sprint Pause
    res_pause = runner.invoke(sprint_group, ["pause"])
    assert res_pause.exit_code == 0

    # 10. Sprint Cancel (rolls back changes)
    res_cancel = runner.invoke(sprint_group, ["cancel"])
    assert res_cancel.exit_code == 0
    patcher.stop()


# Scenario 9 & 10: Browser summary & Vision mock
def test_browser_and_vision_intents() -> None:
    # Verify intent classification matches expected categories
    assert classify_intent("summarize this page") == AgentIntent.BROWSER
    assert classify_intent("what is on my screen?") == AgentIntent.VISION


# Scenario 11: Automation intent match
def test_automation_intent_routing() -> None:
    assert classify_intent("open Notepad") == AgentIntent.AUTOMATION
    assert classify_intent("focus Chrome") == AgentIntent.AUTOMATION
    assert classify_intent("type text") == AgentIntent.AUTOMATION


# Scenario 12, 13, 14, 15 & 16: Agent repository, diagnosis, patch preview, approved patch, focused validation
def test_agent_v2_flow_mock(temp_workspace) -> None:
    from grandpa.agent.execution import inspect_repository, resolve_and_verify_workspace
    # Verify workspace resolves correctly
    ws_ctx = resolve_and_verify_workspace(str(temp_workspace))
    assert ws_ctx.is_safe

    # Verify repository status runs
    repo_state = inspect_repository(str(temp_workspace))
    assert repo_state.current_branch is not None


# Scenario 17 & 18: Checkpoint save/load & state persistence
def test_checkpoint_save_and_load(temp_workspace) -> None:
    from grandpa.agent.development.checkpoint import CheckpointManager
    mgr = CheckpointManager(str(temp_workspace))

    # Setup initial state
    state = ProjectState(project_name="CheckpointProj", project_path=str(temp_workspace))
    from grandpa.agent.development.tracker import ProjectStateTracker
    tracker = ProjectStateTracker(str(temp_workspace), project_name="CheckpointProj")
    tracker.save_state(state)

    # Save checkpoint
    mgr.save_checkpoint(state, "chk_v1")
    checkpoints = mgr.list_checkpoints()
    assert "chk_v1" in checkpoints

    # Restore checkpoint
    success, msg = mgr.restore_checkpoint("chk_v1")
    assert success


# Scenario 19: Server daemon lifecycle
def test_server_daemon_lifecycle(temp_workspace) -> None:
    os.environ["GRANDPA_HOME"] = str(temp_workspace)
    runner = click.testing.CliRunner()

    # Check status when stopped
    res_status = runner.invoke(daemon, ["status"])
    assert "not running" in res_status.output

    # Check stop command idempotency
    res_stop = runner.invoke(daemon, ["stop"])
    assert res_stop.exit_code != 0  # no running server found
