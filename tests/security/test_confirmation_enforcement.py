"""Confirmation enforcement on the live CLI paths.

Covers docs/audit/FEATURE-INVENTORY.md findings 1, 6 and 7:

* ``Grandpa ask --tools shell_exec`` used to hardcode an always-approve
  callback (``cli/ask.py:413-414``), so a non-interactive invocation ran
  arbitrary shell commands with no prompt and no way to opt out.
* ``Grandpa agents ask`` defaulted ``--yes`` to ``True``
  (``cli/agent_cmd.py:642-644``), auto-approving the same tool set.
* Chat never handed a ``confirm_callback`` down to
  ``desktop_automation.execute_automation`` (``local_actions.py:1806``,
  ``chat_cmd.py:1886``), so the confirm-required tier at
  ``desktop_automation.py:37-45`` could never be satisfied.

The tests assert on the enforcement point, not on model behaviour: T1/T2
check whether a real shell command ran, T3 checks whether a
confirmation-gated tool executed, and T4/T5 assert on the callback
argument reaching ``execute_automation``.
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from grandpa.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from grandpa.cli import cli
from grandpa.core.types import ToolCall, ToolResult
from grandpa.tools._stubs import BaseTool, ToolSpec

# Opted out of the default-deny actuation fixture (tests/actuation_guard.py):
pytestmark = pytest.mark.real_actions(
    reason="runs real subprocesses, which is the unit under test; the command and its working directory are the test's own"
)

_ask_mod = importlib.import_module("grandpa.cli.ask")
_agent_cmd_mod = importlib.import_module("grandpa.cli.agent_cmd")

# Command the probe agent asks ``shell_exec`` to run. Set per-test so the
# marker path lands inside pytest's tmp_path.
_SHELL_COMMAND: dict[str, str] = {"command": "echo noop"}


# ---------------------------------------------------------------------------
# T1 / T2 helpers — `Grandpa ask --tools shell_exec`
# ---------------------------------------------------------------------------


class _ShellProbeAgent(ToolUsingAgent):
    """Agent that unconditionally issues one real ``shell_exec`` call.

    Stands in for the model's tool-calling decision so the test exercises
    the confirmation gate rather than a 0.5B model's reliability.
    """

    agent_id = "shell_probe_agent"

    def run(self, input, context: AgentContext | None = None, **kwargs):
        import json

        result = self._executor.execute(
            ToolCall(
                id="probe",
                name="shell_exec",
                arguments=json.dumps({"command": _SHELL_COMMAND["command"]}),
            )
        )
        return AgentResult(content=result.content, tool_results=[result], turns=1)


def _mock_engine() -> MagicMock:
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {
        "content": "unused",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


@pytest.fixture
def ask_setup():
    """Patch engine discovery and register the shell probe agent."""
    from grandpa.core.config import GrandpaConfig
    from grandpa.core.registry import AgentRegistry, ToolRegistry
    from grandpa.tools.shell_exec import ShellExecTool

    # conftest's autouse _clean_registries fixture empties the registries
    # before every test, and load_builtin_tools() is a no-op once its
    # module-level _builtins_loaded flag is set. Register explicitly, the
    # same way tests/cli/test_ask_agent.py does.
    ToolRegistry.register_or_replace("shell_exec", ShellExecTool)
    AgentRegistry.register_or_replace("shell_probe_agent", _ShellProbeAgent)

    engine = _mock_engine()
    config = GrandpaConfig()
    config.intelligence.default_model = "test-model"
    config.agent.max_turns = 2
    config.agent.context_from_memory = False

    with (
        patch.object(_ask_mod, "load_config", return_value=config),
        patch.object(_ask_mod, "get_engine", return_value=("mock", engine)),
        patch.object(_ask_mod, "discover_engines", return_value=[("mock", engine)]),
        patch.object(
            _ask_mod, "discover_models", return_value={"mock": ["test-model"]}
        ),
        patch.object(_ask_mod, "register_builtin_models"),
        patch.object(_ask_mod, "merge_discovered_models"),
    ):
        yield config


class TestAskShellExecConfirmation:
    """T1 / T2 — finding 1."""

    def test_t1_ask_does_not_run_shell_command_without_confirmation(
        self, ask_setup, tmp_path
    ) -> None:
        """Non-tty stdin and no --yes must NOT execute the shell command."""
        marker = tmp_path / "t1_marker.txt"
        _SHELL_COMMAND["command"] = f'echo ran > "{marker}"'

        result = CliRunner().invoke(
            cli,
            ["ask", "--agent", "shell_probe_agent", "--tools", "shell_exec", "go"],
        )

        assert not marker.exists(), (
            "shell_exec executed without confirmation on a non-tty stdin; "
            f"marker file was created. CLI output:\n{result.output}"
        )

    def test_t2_ask_runs_shell_command_with_explicit_yes(
        self, ask_setup, tmp_path
    ) -> None:
        """An explicit --yes must still execute the shell command."""
        marker = tmp_path / "t2_marker.txt"
        _SHELL_COMMAND["command"] = f'echo ran > "{marker}"'

        result = CliRunner().invoke(
            cli,
            [
                "ask",
                "--yes",
                "--agent",
                "shell_probe_agent",
                "--tools",
                "shell_exec",
                "go",
            ],
        )

        assert marker.exists(), (
            "shell_exec did not run even though --yes was passed. "
            f"CLI output:\n{result.output}"
        )


# ---------------------------------------------------------------------------
# T3 helpers — `Grandpa agents ask`
# ---------------------------------------------------------------------------


class _GatedTool(BaseTool):
    """Confirmation-gated tool that records whether it actually ran."""

    tool_id = "gated_probe"
    executed: list[str] = []

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="gated_probe",
            description="Confirmation-gated probe tool.",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        _GatedTool.executed.append("ran")
        return ToolResult(tool_name="gated_probe", content="executed!", success=True)


class _FakeAgentExecutor:
    """Stand-in for AgentExecutor that mirrors its confirm propagation.

    Mirrors ``agents/executor.py:344-356``: the callback stored on the
    executor is forwarded into the agent's own ToolExecutor.
    """

    def execute_tick(self, agent_id: str) -> None:
        from grandpa.tools._stubs import ToolExecutor

        kwargs: dict[str, Any] = {}
        callback = getattr(self, "_confirm_callback", None)
        if callback is not None:
            kwargs["interactive"] = True
            kwargs["confirm_callback"] = callback
        executor = ToolExecutor([_GatedTool()], **kwargs)
        executor.execute(ToolCall(id="1", name="gated_probe", arguments="{}"))


class _FakeManager:
    def send_message(self, *args, **kwargs) -> None:
        return None

    def list_messages(self, agent_id):
        return [{"direction": "agent_to_user", "content": "done"}]


class TestAgentsAskConfirmation:
    """T3 — finding 7."""

    def test_t3_agents_ask_does_not_auto_approve_by_default(self) -> None:
        _GatedTool.executed.clear()
        executor = _FakeAgentExecutor()

        with (
            patch.object(_agent_cmd_mod, "_get_manager", return_value=_FakeManager()),
            patch.object(_agent_cmd_mod, "_resolve_agent_id", return_value="agent-1"),
            patch.object(
                _agent_cmd_mod,
                "_get_scheduler_and_executor",
                return_value=(None, executor, None),
            ),
        ):
            result = CliRunner().invoke(cli, ["agents", "ask", "agent-1", "hello"])

        assert not _GatedTool.executed, (
            "`agents ask` auto-approved a confirmation-gated tool with no flags. "
            f"CLI output:\n{result.output}"
        )


# ---------------------------------------------------------------------------
# T4 / T5 — chat's synthetic-input path
# ---------------------------------------------------------------------------


@pytest.fixture
def recorded_automation(monkeypatch):
    """Record the kwargs ``execute_automation`` is invoked with."""
    import grandpa.local_actions as local_actions
    from grandpa.desktop.control.automation import AutomationResult

    calls: list[dict[str, Any]] = []

    def _fake_execute_automation(spec: str, **kwargs: Any):
        calls.append({"spec": spec, **kwargs})
        return AutomationResult(
            status="handled", action=spec, message="ok", tts_text="ok"
        )

    monkeypatch.setattr(
        local_actions, "execute_automation_spec", _fake_execute_automation
    )
    return calls


def _drive_chat_local_action(phrase: str, confirm) -> None:
    """Run the request/approve pair exactly as chat does.

    ``local_actions`` gates every ``kind="automation"`` result behind its
    own pending-approval store, so ``execute_automation`` is only reached
    on the follow-up "yes" turn. Chat passes the same callback on both.
    """
    from grandpa.local_actions import handle_local_action

    handle_local_action(phrase, confirm=confirm)
    handle_local_action("yes", confirm=confirm)


class TestChatSyntheticInputConfirmation:
    """T4 / T5 — finding 6."""

    def test_t4_chat_type_passes_confirm_callback(self, recorded_automation) -> None:
        _drive_chat_local_action("type hello", confirm=lambda spec, perm: True)

        assert recorded_automation, "execute_automation was never reached"
        call = recorded_automation[-1]
        assert call["spec"] == "type|hello"
        assert call.get("confirm_callback") is not None, (
            "chat reached execute_automation with confirm_callback=None; "
            "the confirm-required tier can never be satisfied"
        )

    def test_t5_chat_press_passes_confirm_callback(self, recorded_automation) -> None:
        _drive_chat_local_action("press enter", confirm=lambda spec, perm: True)

        assert recorded_automation, "execute_automation was never reached"
        call = recorded_automation[-1]
        assert call["spec"] == "press|enter"
        assert call.get("confirm_callback") is not None, (
            "chat reached execute_automation with confirm_callback=None; "
            "the confirm-required tier can never be satisfied"
        )

    def test_t4b_chat_cmd_supplies_a_confirm_callback(self) -> None:
        """The chat REPL must actually pass ``confirm=`` at its call site."""
        from grandpa.cli import chat_cmd

        source = inspect.getsource(chat_cmd)
        idx = source.find("local_action = handle_local_action(")
        assert idx != -1, "chat's handle_local_action call site moved"
        call_site = source[idx : idx + 200]
        assert "confirm=" in call_site, (
            "chat_cmd calls handle_local_action without a confirm callback, so "
            f"synthetic input can never be approved. Call site:\n{call_site}"
        )
