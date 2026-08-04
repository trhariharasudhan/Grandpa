"""Comprehensive integration and security tests for Memory Integration V1 in Grandpa."""

from __future__ import annotations

import tempfile
from pathlib import Path

import click.testing
import pytest

from grandpa.cli.chat_cmd import _handle_natural_memory_intent
from grandpa.cli.memory_cmd import memory
from grandpa.memory.intent import MemoryIntent, MemoryIntentRouter
from grandpa.memory.service import MemoryService
from grandpa.planner.executive import ExecutivePlanner
from grandpa.voice.operator import parse_voice_operator_command


@pytest.fixture(autouse=True)
def setup_temp_memory_integration():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_integration_memory.db"
        svc = MemoryService.get_instance(db_path=str(db_path))
        yield svc
        MemoryService.reset_instance()


# 1. Memory Intent Router Tests
def test_memory_intent_router_patterns() -> None:
    router = MemoryIntentRouter()

    res = router.parse("Remember that I prefer PowerShell")
    assert res is not None
    assert res.intent == MemoryIntent.REMEMBER
    assert res.scope == "preference"
    assert res.target_key == "preferred_shell"
    assert res.target_value == "pwsh"

    res = router.parse("Remember my default browser is Chrome")
    assert res is not None
    assert res.intent == MemoryIntent.REMEMBER
    assert res.scope == "preference"
    assert res.target_key == "default_browser"
    assert res.target_value == "Chrome"

    res = router.parse("Remember Grandpa project is at D:\\Grandpa")
    assert res is not None
    assert res.intent == MemoryIntent.REMEMBER
    assert res.scope == "project"
    assert res.project_name == "Grandpa"
    assert "D:\\Grandpa" in res.target_value

    res = router.parse("What was the last feature we completed?")
    assert res is not None
    assert res.intent == MemoryIntent.RECALL
    assert res.scope == "project"
    assert res.target_key == "latest_feature"

    res = router.parse("What is the latest Grandpa commit?")
    assert res is not None
    assert res.intent == MemoryIntent.RECALL
    assert res.scope == "project"
    assert res.target_key == "latest_commit"

    res = router.parse("Continue where we stopped")
    assert res is not None
    assert res.intent == MemoryIntent.RESUME

    res = router.parse("Forget my preferred browser")
    assert res is not None
    assert res.intent == MemoryIntent.FORGET
    assert res.target_key == "default_browser"

    res = router.parse("Do not remember this")
    assert res is not None
    assert res.intent == MemoryIntent.DO_NOT_REMEMBER


# 2. Relevance Retrieval & Bounded Limits Tests
def test_bounded_relevance_retrieval(
    setup_temp_memory_integration: MemoryService,
) -> None:
    svc = setup_temp_memory_integration

    # Store 10 items
    for i in range(10):
        svc.remember(f"Fact number {i} regarding testing", key=f"fact_{i}")

    # retrieve_relevant must enforce limit <= 5 and max_chars <= 1500
    relevant = svc.retrieve_relevant(query="testing", limit=10, max_chars=1500)
    assert len(relevant) <= 5


def test_ranking_priority(setup_temp_memory_integration: MemoryService) -> None:
    svc = setup_temp_memory_integration
    svc.remember("General knowledge item", category="knowledge", key="gen_item")
    svc.remember(
        "Grandpa project item",
        category="project",
        project_name="Grandpa",
        key="proj_item",
    )
    svc.remember("Preferred shell is pwsh", category="preference", key="pref_item")

    ranked = svc.retrieval.retrieve_relevant(query="pwsh", project_name="Grandpa")
    assert len(ranked) >= 1
    # Project or exact match items should rank top
    assert ranked[0].key in ("pref_item", "proj_item")


# 3. Security & Write Policy Tests
def test_security_sensitive_data_rejection(
    setup_temp_memory_integration: MemoryService,
) -> None:
    svc = setup_temp_memory_integration

    with pytest.raises(ValueError, match="sensitive"):
        svc.remember("my password is secret_123", key="pass_key")

    with pytest.raises(ValueError, match="sensitive"):
        svc.remember("api_key = sk-1234567890abcdef", key="api_key")

    with pytest.raises(ValueError, match="sensitive"):
        svc.remember("credit_card = 4111222233334444", key="card_key")


# 4. Chat Integration Natural Intent Tests
def test_chat_natural_memory_intents(
    setup_temp_memory_integration: MemoryService,
) -> None:
    svc = setup_temp_memory_integration

    # Remember preference
    msg = _handle_natural_memory_intent("Remember that I prefer PowerShell")
    assert msg is not None
    assert "pwsh" in msg or "preferred_shell" in msg

    # Recall preference
    recall_msg = _handle_natural_memory_intent("What is my preferred shell?")
    assert recall_msg is not None
    assert "pwsh" in recall_msg

    # Remember project feature
    svc.remember_project_result(
        "Grandpa",
        goal="Build Memory V1",
        status="completed",
        latest_feature="Memory System V1",
    )
    feat_msg = _handle_natural_memory_intent("What was the last feature we completed?")
    assert feat_msg is not None
    assert "Memory System V1" in feat_msg

    # Session disable toggle
    disable_msg = _handle_natural_memory_intent("Do not remember this")
    assert disable_msg is not None
    assert "disabled" in disable_msg
    assert not svc.session_memory_enabled()


# 5. Voice Intent Routing Tests
def test_voice_operator_memory_intent() -> None:
    intent = parse_voice_operator_command("Grandpa, remember that I prefer Chrome.")
    assert intent.kind == "memory"
    assert intent.action == "remember"

    forget_intent = parse_voice_operator_command(
        "Grandpa, forget my preferred browser."
    )
    assert forget_intent.kind == "memory"
    assert forget_intent.action == "forget"


# 6. Executive Planner Integration Tests
def test_planner_project_outcome_recording(
    setup_temp_memory_integration: MemoryService,
) -> None:
    svc = setup_temp_memory_integration
    planner = ExecutivePlanner(session_id="test_plan_session")

    plan = planner.create("Open browser to github.com")
    assert plan is not None

    # Simulate execution failure
    result = planner._fail(plan, "test_failure", "Failed to connect to browser.")
    assert result.status in ("failed", "partially_completed")

    # Project memory should store the failed outcome
    summary = svc.projects.get_project_summary("Grandpa")
    assert summary is not None
    assert "last_failed_plan" in summary.metadata


# 7. CLI Subcommands Tests
def test_cli_extended_subcommands(setup_temp_memory_integration: MemoryService) -> None:
    svc = setup_temp_memory_integration
    svc.remember("Recent feature update", category="knowledge", key="rec_feat")
    svc.projects.update_project_info(
        "Grandpa", "Automation assistant", latest_feature="Memory Integration V1"
    )

    runner = click.testing.CliRunner()

    # recent
    res = runner.invoke(memory, ["recent"])
    assert res.exit_code == 0
    assert "rec_feat" in res.output

    # relevant
    res = runner.invoke(memory, ["relevant", "feature"])
    assert res.exit_code == 0

    # project
    res = runner.invoke(memory, ["project", "Grandpa"])
    assert res.exit_code == 0
    assert "Automation assistant" in res.output

    # explain
    res = runner.invoke(memory, ["explain", "feature"])
    assert res.exit_code == 0
    assert "Explanation" in res.output

    # session
    res = runner.invoke(memory, ["session", "status"])
    assert res.exit_code == 0

    # disable / enable
    res = runner.invoke(memory, ["disable"])
    assert res.exit_code == 0
    assert "DISABLED" in res.output

    res = runner.invoke(memory, ["enable"])
    assert res.exit_code == 0
    assert "ENABLED" in res.output


# 8. Regression & Validation Tests
def test_structured_project_field_mapping(
    setup_temp_memory_integration: MemoryService,
) -> None:
    svc = setup_temp_memory_integration

    # Store separate keys
    svc.remember(
        content="Grandpa automation",
        category="project",
        key="proj_grandpa_summary",
        project_name="Grandpa",
    )
    svc.remember(
        content="Memory V1",
        category="project",
        key="latest_feature",
        project_name="Grandpa",
    )
    svc.remember(
        content="D:\\Grandpa",
        category="project",
        key="project_path",
        project_name="Grandpa",
    )
    svc.remember(
        content="abc1234",
        category="project",
        key="latest_commit",
        project_name="Grandpa",
    )
    svc.remember(
        content="Fix mapping issues",
        category="project",
        key="next_task",
        project_name="Grandpa",
    )
    svc.remember(
        content="Failed test run",
        category="project",
        key="last_failed_plan",
        project_name="Grandpa",
    )

    runner = click.testing.CliRunner()
    res = runner.invoke(memory, ["project", "Grandpa"])

    assert res.exit_code == 0
    assert "Summary       : Grandpa automation" in res.output
    assert "Latest Feature: Memory V1" in res.output
    assert "Path          : D:\\Grandpa" in res.output
    assert "Latest Commit : abc1234" in res.output
    assert "Next Task     : Fix mapping issues" in res.output
    assert "Failed Plan   : Failed test run" in res.output


def test_cli_session_memory_persistence(
    setup_temp_memory_integration: MemoryService,
) -> None:
    svc = setup_temp_memory_integration
    runner = click.testing.CliRunner()

    # Disable via CLI (simulated process 1)
    res1 = runner.invoke(memory, ["disable"])
    assert res1.exit_code == 0

    # Check that another instance reads the disabled state
    svc_new = MemoryService(db_path=svc.store.db_path)
    assert not svc_new.session_memory_enabled()

    # Enable via CLI (simulated process 2)
    res2 = runner.invoke(memory, ["enable"])
    assert res2.exit_code == 0

    # Check new instance reads enabled state
    svc_new_2 = MemoryService(db_path=svc.store.db_path)
    assert svc_new_2.session_memory_enabled()


def test_chat_recall_and_forget(setup_temp_memory_integration: MemoryService) -> None:
    # Remember via chat
    msg1 = _handle_natural_memory_intent("Remember that I prefer PowerShell")
    assert msg1 is not None

    # Recall via chat
    msg2 = _handle_natural_memory_intent("What is my preferred shell?")
    assert msg2 is not None
    assert "PowerShell" in msg2 or "pwsh" in msg2

    # Forget via chat
    msg3 = _handle_natural_memory_intent("Forget my preferred shell")
    assert msg3 is not None
    assert "Forgot" in msg3

    # Confirm forgotten/missing memory is not fabricated
    msg4 = _handle_natural_memory_intent("What is my preferred shell?")
    assert msg4 is not None
    assert "do not have a recorded preference" in msg4 or "N/A" in msg4 or "not" in msg4


def test_voice_recall_and_forget(setup_temp_memory_integration: MemoryService) -> None:
    # Voice command remembering
    intent1 = parse_voice_operator_command("Grandpa, remember that I prefer Chrome.")
    assert intent1.kind == "memory"
    assert intent1.action == "remember"

    # Voice command forgetting
    intent2 = parse_voice_operator_command("Grandpa, forget my preferred browser.")
    assert intent2.kind == "memory"
    assert intent2.action == "forget"


def test_continue_project_context(setup_temp_memory_integration: MemoryService) -> None:
    svc = setup_temp_memory_integration

    svc.remember(
        content="Memory Integration V1",
        category="project",
        key="latest_feature",
        project_name="Grandpa",
    )
    svc.remember(
        content="D:\\Grandpa",
        category="project",
        key="project_path",
        project_name="Grandpa",
    )
    svc.remember(
        content="xyz567",
        category="project",
        key="latest_commit",
        project_name="Grandpa",
    )
    svc.remember(
        content="Add validation steps",
        category="project",
        key="next_task",
        project_name="Grandpa",
    )

    msg = _handle_natural_memory_intent("Continue the Grandpa project")
    assert msg is not None
    assert "Resuming Grandpa project." in msg
    assert "Path: D:\\Grandpa." in msg
    assert "Latest Feature: Memory Integration V1." in msg
    assert "Latest Commit: xyz567." in msg
    assert "Next Task: Add validation steps." in msg


def test_voice_operator_loop_integration(
    setup_temp_memory_integration: MemoryService,
) -> None:

    commands = [
        "Remember that I prefer Chrome",
        "What is my preferred browser?",
        "Forget my preferred browser",
        "What is my preferred browser?",
        "stop listening",
    ]
    command_idx = 0

    def mock_input(prompt: str = "") -> str:
        nonlocal command_idx
        if command_idx >= len(commands):
            return "stop listening"
        cmd = commands[command_idx]
        command_idx += 1
        return cmd

    outputs = []

    def mock_output(msg: str) -> None:
        outputs.append(msg)

    from grandpa.voice.operator import run_voice_operator_loop

    # Run loop
    exit_code = run_voice_operator_loop(
        input_func=mock_input,
        output_func=mock_output,
        prefer_voice=False,
    )

    assert exit_code == 0
    # Confirm it executed properly
    assert any("Chrome" in out for out in outputs)
    assert any("Forgot" in out for out in outputs)
