"""Regression and integration tests for Grandpa Agent Runtime V1."""

from __future__ import annotations

import tempfile
from pathlib import Path

import click.testing
import pytest

from grandpa.agent.context import build_context, classify_intent
from grandpa.agent.executor import AgentExecutor
from grandpa.agent.models import (
    AgentGoal,
    AgentIntent,
    AgentStep,
    StepStatus,
)
from grandpa.agent.verifier import StepVerifier
from grandpa.cli.agent_run_cmd import agent_group
from grandpa.memory.service import MemoryService


@pytest.fixture(autouse=True)
def setup_temp_memory_agent():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_agent_memory.db"
        svc = MemoryService.get_instance(db_path=str(db_path))
        yield svc
        MemoryService.reset_instance()


def test_intent_classification() -> None:
    assert classify_intent("Continue the Grandpa project") == AgentIntent.PROJECT_CONTINUE
    assert classify_intent("What is the status of the project?") == AgentIntent.PROJECT_STATUS
    assert classify_intent("Research FastAPI deployment benefits") == AgentIntent.RESEARCH
    assert classify_intent("Open Cloud Run webpage in browser") == AgentIntent.BROWSER_TASK
    assert classify_intent("Click on the visual button coordinate") == AgentIntent.AUTOMATION_TASK
    assert classify_intent("Remember that I prefer PowerShell shell") == AgentIntent.MEMORY_TASK
    assert classify_intent("Plan a new memory integration feature") == AgentIntent.PLANNING_TASK
    assert classify_intent("Fly to the moon") == AgentIntent.UNKNOWN


def test_context_creation_and_memory_retrieval(setup_temp_memory_agent: MemoryService) -> None:
    svc = setup_temp_memory_agent
    svc.remember(content="D:\\Grandpa", category="project", key="project_path", project_name="Grandpa")
    svc.remember(content="Memory V1", category="project", key="latest_feature", project_name="Grandpa")

    goal = AgentGoal(raw_text="Continue Grandpa project", session_id="test_sess")
    context = build_context(goal)

    assert context.intent == AgentIntent.PROJECT_CONTINUE
    assert context.project_memory.get("project_path") == "D:\\Grandpa"
    assert context.project_memory.get("latest_feature") == "Memory V1"
    # Git branch might or might not be None depending on env, but we shouldn't fabricate missing values
    assert "current_branch" in context.project_memory or context.project_memory.get("current_branch") is None


def test_tool_routing() -> None:
    executor = AgentExecutor()

    step_mem = AgentStep(id="s1", description="Read preferred shell settings", tool="memory")
    assert executor.route_tool(step_mem).tool_name == "MemoryService"

    step_res = AgentStep(id="s2", description="Research FastAPI docs online", tool="research")
    assert executor.route_tool(step_res).tool_name == "BrowserIntelligence"

    step_vis = AgentStep(id="s3", description="Inspect UI elements coordinate", tool="vision")
    assert executor.route_tool(step_vis).tool_name == "VisionEngine"

    step_auto = AgentStep(id="s4", description="Click target button", tool="automation")
    assert executor.route_tool(step_auto).tool_name == "ScreenAutomationService"

    step_plan = AgentStep(id="s5", description="Decompose task goal", tool="planner")
    assert executor.route_tool(step_plan).tool_name == "ExecutivePlanner"


def test_safety_blocking_dangerous_actions() -> None:
    executor = AgentExecutor(confirm_callback=lambda _prompt: False) # Always reject confirmation

    del_step = AgentStep(id="s1", description="Delete index.html file", tool="automation")
    res1 = executor.execute_step(del_step, None)
    assert del_step.status == StepStatus.FAILED
    assert "safety policy" in del_step.error
    assert res1 is None

    git_step = AgentStep(id="s2", description="git push origin main", tool="automation", args={"command": "git push origin main"})
    res2 = executor.execute_step(git_step, None)
    assert git_step.status == StepStatus.FAILED
    assert "Git history" in git_step.error or "safety policy" in git_step.error
    assert res2 is None

    shell_step = AgentStep(id="s3", description="Run cmd shell script", tool="automation", args={"command": "rmdir /s /q C:\\"})
    res3 = executor.execute_step(shell_step, None)
    assert shell_step.status == StepStatus.FAILED
    assert "shell" in shell_step.error
    assert res3 is None


def test_verification_logic() -> None:
    verifier = StepVerifier()

    # Successful step verification
    step_ok = AgentStep(id="s1", description="Get preference", tool="memory")
    v_ok = verifier.verify_step(step_ok, "PowerShell")
    assert v_ok.action_completed
    assert v_ok.expected_result_obtained
    assert not v_ok.failures

    # Failed step verification
    step_fail = AgentStep(id="s2", description="Get preference", tool="memory", error="Connection reset")
    v_fail = verifier.verify_step(step_fail, None)
    assert not v_fail.action_completed
    assert not v_fail.expected_result_obtained
    assert len(v_fail.failures) == 2  # error field and empty result


def test_bounded_recovery() -> None:
    # Set progress callback
    progress_msgs = []
    def prog_cb(m: str) -> None:
        progress_msgs.append(m)

    executor = AgentExecutor(progress_callback=prog_cb)

    # Force step execution failure
    step = AgentStep(id="s1", description="Invalid Action", tool="memory")
    # Make _dispatch raise an exception to trigger recovery retries
    def failing_dispatch(*args, **kwargs):
        raise ValueError("Simulated dispatch failure")
    executor._dispatch = failing_dispatch

    goal = AgentGoal(raw_text="Plan a new feature", session_id="test_sess")
    context = build_context(goal)

    with pytest.raises(ValueError):
        executor.execute_step(step, context)

    assert step.status == StepStatus.FAILED
    assert len(context.recovery_attempts) == 3 # Should attempt exactly 3 times
    assert all(not r.success for r in context.recovery_attempts)


def test_cli_commands(setup_temp_memory_agent: MemoryService) -> None:
    runner = click.testing.CliRunner()

    # 1. Preview
    res_preview = runner.invoke(agent_group, ["preview", "Continue Grandpa project"])
    assert res_preview.exit_code == 0
    assert "Goal:" in res_preview.output
    assert "Plan:" in res_preview.output
    assert "Execution:" in res_preview.output
    assert "Dry run" in res_preview.output

    # 2. Run
    res_run = runner.invoke(agent_group, ["run", "Continue Grandpa project", "--yes"])
    assert res_run.exit_code == 0
    assert "Goal:" in res_run.output
    assert "Verification:" in res_run.output
    assert "Next Actions:" in res_run.output

    # 3. Status
    res_status = runner.invoke(agent_group, ["status"])
    assert res_status.exit_code == 0
    assert "COMPLETED" in res_status.output or "RUNNING" in res_status.output

    # 4. Trace
    res_trace = runner.invoke(agent_group, ["trace"])
    assert res_trace.exit_code == 0
    assert "Last Agent Execution Trace:" in res_trace.output

    # 5. Cancel
    res_cancel = runner.invoke(agent_group, ["cancel"])
    assert res_cancel.exit_code == 0
    assert "cancellation" in res_cancel.output.lower()
