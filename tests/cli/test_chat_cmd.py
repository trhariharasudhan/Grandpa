"""Tests for ``Grandpa chat`` interactive REPL command."""

from __future__ import annotations

from unittest import mock
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from grandpa.agents._stubs import (
    AgentContext,
    AgentResult,
    BaseAgent,
    ToolUsingAgent,
)
from grandpa.cli.chat_cmd import (
    _create_one_shot_reminder,
    _handle_memory_slash_command,
    _handle_natural_assistant_intent,
    _handle_reminders_slash_command,
    _read_input,
    chat,
)
from grandpa.core.config import GrandpaConfig
from grandpa.core.registry import AgentRegistry, ToolRegistry
from grandpa.core.types import ToolCall, ToolResult
from grandpa.engine._base import EngineConnectionError, EngineModelNotFoundError
from grandpa.memory_context import MemoryStore
from grandpa.reminders import ReminderStore
from grandpa.tools._stubs import BaseTool, ToolSpec


class _SimpleChatAgent(BaseAgent):
    agent_id = "simple_chat_agent"

    def run(self, input, context: AgentContext | None = None, **kwargs):
        return AgentResult(content="simple ok", turns=1)


class _DangerousChatTool(BaseTool):
    tool_id = "dangerous_chat"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="dangerous_chat",
            description="Confirmation-gated chat tool.",
            requires_confirmation=True,
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(
            tool_name="dangerous_chat",
            content="chat executed!",
            success=True,
        )


class _ToolChatAgent(ToolUsingAgent):
    agent_id = "tool_chat_agent"

    def run(self, input, context: AgentContext | None = None, **kwargs):
        result = self._executor.execute(
            ToolCall(id="chat", name="dangerous_chat", arguments="{}")
        )
        return AgentResult(content=result.content, tool_results=[result], turns=1)


class TestChatCommand:
    """Test the Click command definition and help output."""

    def test_command_exists(self) -> None:
        result = CliRunner().invoke(chat, ["--help"])
        assert result.exit_code == 0
        assert "interactive" in result.output.lower() or "chat" in result.output.lower()

    def test_options(self) -> None:
        result = CliRunner().invoke(chat, ["--help"])
        assert result.exit_code == 0
        assert "--engine" in result.output
        assert "--model" in result.output
        assert "--agent" in result.output
        assert "--tools" in result.output
        assert "--system" in result.output

    def test_slash_commands_listed(self) -> None:
        result = CliRunner().invoke(chat, ["--help"])
        assert result.exit_code == 0
        assert "/quit" in result.output


class TestReadInput:
    """Test the _read_input helper function."""

    def test_read_input_eof(self) -> None:
        with mock.patch("builtins.input", side_effect=EOFError):
            assert _read_input() is None

    def test_read_input_keyboard_interrupt(self) -> None:
        with mock.patch("builtins.input", side_effect=KeyboardInterrupt):
            assert _read_input() is None

    def test_read_input_normal(self) -> None:
        with mock.patch("builtins.input", return_value="hello"):
            assert _read_input() == "hello"


class TestChatSlashCommands:
    def test_memory_help(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")

        message = _handle_memory_slash_command("/memory", store=store)

        assert message is not None
        assert "/memory list" in message
        assert "/memory search <query>" in message
        assert "/memory forget <query or id>" in message

    def test_memory_list(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("preferences", "name", "Hari")

        message = _handle_memory_slash_command("/memory list", store=store)

        assert message is not None
        assert "Saved memories:" in message
        assert "Hari" in message

    def test_memory_search(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("note", "ai_automation", "I am learning AI automation")

        message = _handle_memory_slash_command("/memory search automation", store=store)

        assert message is not None
        assert "Matching memories:" in message
        assert "AI automation" in message

    def test_memory_forget_by_id(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("preferences", "name", "Hari")
        memory_id = store.list_memories()[0]["id"]

        message = _handle_memory_slash_command(f"/memory forget {memory_id}", store=store)

        assert message == "Forgot 1 memory."
        assert store.list_memories() == []

    def test_reminders_help(self, tmp_path) -> None:
        store = ReminderStore(tmp_path / "reminders.db")

        message = _handle_reminders_slash_command("/reminders", store=store)

        assert message is not None
        assert "/reminders list" in message
        assert "/reminders all" in message
        assert "/reminders cancel <id>" in message

    def test_reminders_list_pending_only(self, tmp_path) -> None:
        from datetime import UTC, datetime, timedelta

        store = ReminderStore(tmp_path / "reminders.db")
        now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
        pending = store.create("drink water", now + timedelta(minutes=30))
        cancelled = store.create("cancelled reminder", now + timedelta(hours=1))
        store.cancel(cancelled.id, now=now)

        message = _handle_reminders_slash_command("/reminders list", store=store)

        assert message is not None
        assert pending.message in message
        assert cancelled.message not in message

    def test_reminders_all(self, tmp_path) -> None:
        from datetime import UTC, datetime, timedelta

        store = ReminderStore(tmp_path / "reminders.db")
        now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
        pending = store.create("drink water", now + timedelta(minutes=30))
        cancelled = store.create("cancelled reminder", now + timedelta(hours=1))
        store.cancel(cancelled.id, now=now)

        message = _handle_reminders_slash_command("/reminders all", store=store)

        assert message is not None
        assert pending.message in message
        assert cancelled.message in message

    def test_reminders_cancel(self, tmp_path) -> None:
        from datetime import UTC, datetime, timedelta

        store = ReminderStore(tmp_path / "reminders.db")
        reminder = store.create("drink water", datetime(2026, 6, 13, 12, 30, tzinfo=UTC) + timedelta(minutes=30))

        message = _handle_reminders_slash_command(f"/reminders cancel {reminder.id}", store=store)

        assert message == "Reminder cancelled."
        assert store.get(reminder.id).status == "cancelled"  # type: ignore[union-attr]

    def test_chat_reminder_creation_still_works(self, tmp_path, monkeypatch) -> None:
        from datetime import UTC

        store = ReminderStore(tmp_path / "reminders.db")
        monkeypatch.setattr("grandpa.reminder_parser.default_reminder_timezone", lambda: UTC)

        message = _create_one_shot_reminder("remind me in 30 minutes to drink water", store=store)

        assert message is not None
        assert "Reminder created" in message
        assert store.list(status="pending")[0].message == "drink water"

    def test_show_my_memories_routes_locally(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("preferences", "name", "Hari")

        message = _handle_natural_assistant_intent("show my memories", memory_store=store)

        assert message is not None
        assert "Saved memories:" in message
        assert "Hari" in message

    def test_list_my_reminders_routes_to_one_shot_reminders(self, tmp_path) -> None:
        from datetime import UTC, datetime, timedelta

        store = ReminderStore(tmp_path / "reminders.db")
        store.create("drink water", datetime(2026, 6, 13, 12, 0, tzinfo=UTC) + timedelta(minutes=30))

        message = _handle_natural_assistant_intent("list my reminders", reminder_store=store)

        assert message is not None
        assert "Reminders:" in message
        assert "drink water" in message

    def test_what_reminders_do_i_have_routes_to_one_shot_reminders(self, tmp_path) -> None:
        from datetime import UTC, datetime, timedelta

        store = ReminderStore(tmp_path / "reminders.db")
        store.create("call Arjun", datetime(2026, 6, 13, 19, 0, tzinfo=UTC) + timedelta(days=1))

        for text in (
            "what reminders do I have?",
            "what reminder do I have",
            "what are my reminders",
            "do I have any reminders",
            "show me my reminders",
            "list my reminders",
        ):
            message = _handle_natural_assistant_intent(text, reminder_store=store)

            assert message is not None
            assert "Reminders:" in message
            assert "call Arjun" in message

    def test_empty_natural_reminder_list_has_creation_hint(self, tmp_path) -> None:
        store = ReminderStore(tmp_path / "reminders.db")

        message = _handle_natural_assistant_intent("what reminders do I have", reminder_store=store)

        assert message == (
            "No pending reminders found. You can create one with: "
            "remind me in 30 minutes to drink water"
        )

    def test_delete_reminder_not_found_stays_local(self, tmp_path) -> None:
        store = ReminderStore(tmp_path / "reminders.db")

        message = _handle_natural_assistant_intent("delete reminder 4", reminder_store=store)

        assert message == "Reminder not found. Use /reminders list to see reminder IDs."

    def test_delete_reminder_cancels_pending_one_shot_reminder(self, tmp_path) -> None:
        from datetime import UTC, datetime, timedelta

        store = ReminderStore(tmp_path / "reminders.db")
        reminder = store.create("drink water", datetime(2026, 6, 13, 12, 0, tzinfo=UTC) + timedelta(minutes=30))

        message = _handle_natural_assistant_intent(f"delete reminder {reminder.id}", reminder_store=store)

        assert message == "Reminder cancelled."
        assert store.get(reminder.id).status == "cancelled"  # type: ignore[union-attr]


class TestChatAgents:
    def test_simple_agent_does_not_receive_tool_only_kwargs(self) -> None:
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = {"content": "engine fallback"}
        config = GrandpaConfig()
        config.intelligence.default_model = "test-model"

        AgentRegistry.register_value("simple_chat_agent", _SimpleChatAgent)

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("mock", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(
                chat,
                ["--agent", "simple_chat_agent", "--model", "test-model"],
                input="hello\n/quit\n",
            )

        assert result.exit_code == 0
        assert "simple ok" in result.output
        assert "failed" not in result.output.lower()

    def test_tool_agent_uses_legacy_agent_tools_and_prompts_confirmation(self) -> None:
        engine = MagicMock()
        engine.engine_id = "mock"
        config = GrandpaConfig()
        config.intelligence.default_model = "test-model"
        config.agent.tools = "dangerous_chat"
        config.agent.max_turns = 3

        AgentRegistry.register_value("tool_chat_agent", _ToolChatAgent)
        ToolRegistry.register_value("dangerous_chat", _DangerousChatTool)

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("mock", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(
                chat,
                ["--agent", "tool_chat_agent", "--model", "test-model"],
                input="hello\nyes\n/quit\n",
            )

        assert result.exit_code == 0
        assert "Confirm:" in result.output
        assert "chat executed!" in result.output


class TestChatOllamaUnavailable:
    def test_missing_ollama_model_decline_has_manual_guidance(self) -> None:
        engine = MagicMock()
        engine.engine_id = "ollama"
        engine.generate.side_effect = EngineModelNotFoundError("qwen2.5:3b")
        config = GrandpaConfig()
        config.agent.default_agent = "none"
        config.intelligence.default_model = "qwen2.5:3b"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("ollama", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(
                chat,
                ["--model", "qwen2.5:3b"],
                input="hello\nn\n",
            )

        assert result.exit_code == 1
        assert (
            'Ollama is running, but model "qwen2.5:3b" is not installed.'
            in result.output
        )
        assert 'Pull "qwen2.5:3b" now?' in result.output
        assert "Install it with: ollama pull qwen2.5:3b" in result.output
        assert "Verify it with: ollama list" in result.output
        assert "Ollama is not available." not in result.output
        assert "Traceback" not in result.output
        engine.pull_model.assert_not_called()

    def test_missing_ollama_model_empty_confirmation_defaults_to_no(self) -> None:
        engine = MagicMock()
        engine.engine_id = "ollama"
        engine.generate.side_effect = EngineModelNotFoundError("qwen2.5:3b")
        config = GrandpaConfig()
        config.agent.default_agent = "none"
        config.intelligence.default_model = "qwen2.5:3b"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("ollama", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(
                chat,
                ["--model", "qwen2.5:3b"],
                input="hello\n\n",
            )

        assert result.exit_code == 1
        assert "Install it with: ollama pull qwen2.5:3b" in result.output
        engine.pull_model.assert_not_called()

    def test_missing_ollama_model_acceptance_pulls_once(self) -> None:
        engine = MagicMock()
        engine.engine_id = "ollama"
        engine.generate.side_effect = EngineModelNotFoundError("qwen2.5:3b")
        engine.pull_model.return_value = {"model": "qwen2.5:3b", "status": "success"}
        config = GrandpaConfig()
        config.agent.default_agent = "none"
        config.intelligence.default_model = "qwen2.5:3b"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("ollama", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(
                chat,
                ["--model", "qwen2.5:3b"],
                input="hello\ny\n",
            )

        assert result.exit_code == 1
        engine.pull_model.assert_called_once_with("qwen2.5:3b")
        assert 'Pulling "qwen2.5:3b" from Ollama' in result.output
        assert 'Model "qwen2.5:3b" was installed.' in result.output
        assert "Please rerun the chat command." in result.output
        assert "Traceback" not in result.output

    def test_missing_ollama_model_pull_connection_failure_uses_unavailable_message(
        self,
    ) -> None:
        engine = MagicMock()
        engine.engine_id = "ollama"
        engine.generate.side_effect = EngineModelNotFoundError("qwen2.5:3b")
        engine.pull_model.side_effect = EngineConnectionError(
            "Ollama not reachable at http://localhost:11434"
        )
        config = GrandpaConfig()
        config.agent.default_agent = "none"
        config.intelligence.default_model = "qwen2.5:3b"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("ollama", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(
                chat,
                ["--model", "qwen2.5:3b"],
                input="hello\ny\n",
            )

        assert result.exit_code == 1
        engine.pull_model.assert_called_once_with("qwen2.5:3b")
        assert "Ollama is not available." in result.output
        assert "Start it with: ollama serve" in result.output
        assert "Traceback" not in result.output

    def test_missing_ollama_model_pull_programming_error_is_not_swallowed(self) -> None:
        engine = MagicMock()
        engine.engine_id = "ollama"
        engine.generate.side_effect = EngineModelNotFoundError("qwen2.5:3b")
        engine.pull_model.side_effect = RuntimeError("pull bug")
        config = GrandpaConfig()
        config.agent.default_agent = "none"
        config.intelligence.default_model = "qwen2.5:3b"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("ollama", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(
                chat,
                ["--model", "qwen2.5:3b"],
                input="hello\ny\n",
            )

        assert isinstance(result.exception, RuntimeError)
        assert "pull bug" in str(result.exception)
        assert "Ollama is not available." not in result.output

    def test_ollama_connection_failure_has_actionable_message(self) -> None:
        engine = MagicMock()
        engine.engine_id = "ollama"
        engine.generate.side_effect = EngineConnectionError(
            "Ollama not reachable at http://localhost:11434"
        )
        config = GrandpaConfig()
        config.agent.default_agent = "none"
        config.intelligence.default_model = "test-model"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("ollama", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(
                chat,
                ["--model", "test-model"],
                input="hello\n",
            )

        assert result.exit_code == 1
        assert "Ollama is not available." in result.output
        assert "Start it with: ollama serve" in result.output
        assert "Verify it with: ollama list" in result.output
        assert "Traceback" not in result.output
        assert "httpx" not in result.output.lower()

    def test_non_connection_error_is_not_reported_as_ollama_unavailable(self) -> None:
        engine = MagicMock()
        engine.engine_id = "ollama"
        engine.generate.side_effect = RuntimeError("programming bug")
        config = GrandpaConfig()
        config.agent.default_agent = "none"
        config.intelligence.default_model = "test-model"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("ollama", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(
                chat,
                ["--model", "test-model"],
                input="hello\n",
            )

        assert result.exit_code == 0
        assert "Ollama is not available." not in result.output
        assert "not installed" not in result.output
        assert "ollama pull" not in result.output
        assert "ollama serve" not in result.output
        assert "Traceback" not in result.output
