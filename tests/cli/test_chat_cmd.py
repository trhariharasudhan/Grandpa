"""Tests for ``Grandpa chat`` interactive REPL command."""

from __future__ import annotations

from unittest import mock
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from rich.console import Console

from grandpa.agents._stubs import (
    AgentContext,
    AgentResult,
    BaseAgent,
    ToolUsingAgent,
)
from grandpa.cli import input_ui, theme
from grandpa.cli.chat_cmd import (
    _create_one_shot_reminder,
    _handle_apps_slash_command,
    _handle_help_slash_command,
    _handle_memory_slash_command,
    _handle_module_slash_command,
    _handle_natural_assistant_intent,
    _handle_reminders_slash_command,
    _read_input,
    _unknown_slash_command_message,
    chat,
)
from grandpa.cli.slash_commands import (
    command_names,
    command_preview_items,
    command_preview_options,
    get_command,
    unknown_command_message,
)
from grandpa.cli.theme import render_help, render_user_message
from grandpa.core.config import GrandpaConfig
from grandpa.core.registry import AgentRegistry, ToolRegistry
from grandpa.core.types import ToolCall, ToolResult
from grandpa.engine._base import (
    EngineConnectionError,
    EngineModelLoadError,
    EngineModelNotFoundError,
)
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

    def test_render_help_shows_command_center_categories(self) -> None:
        console = Console(record=True, width=120)

        render_help(console)
        output = console.export_text()

        assert "Grandpa Command Center" in output
        assert "Core" in output
        assert "Memory & Productivity" in output
        assert "Computer" in output
        assert "Developer" in output
        assert "Personal" in output
        assert "Automation" in output
        assert "/phone" in output
        assert "/desktop" in output
        assert "/order" in output
        assert "/github" in output
        assert "order biryani" in output
        assert "╭" not in output
        assert "╰" not in output

    def test_interactive_help_uses_command_center(self) -> None:
        engine = MagicMock()
        engine.engine_id = "mock"
        config = GrandpaConfig()
        config.intelligence.default_model = "test-model"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("mock", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(chat, ["--model", "test-model"], input="/help\n/quit\n")

        assert result.exit_code == 0
        assert "Grandpa Command Center" in result.output
        assert "Core" in result.output
        assert "Computer" in result.output
        assert "Developer" in result.output
        assert "Personal" in result.output
        assert "Automation" in result.output
        assert "/phone" in result.output
        assert "/desktop" in result.output
        assert "/order" in result.output
        assert "/github" in result.output
        engine.generate.assert_not_called()

    def test_help_subcommands_return_specific_sections(self) -> None:
        commands = _handle_help_slash_command("/help commands")
        examples = _handle_help_slash_command("/help examples")
        modules = _handle_help_slash_command("/help modules")
        shortcuts = _handle_help_slash_command("/help shortcuts")

        assert commands is not None
        assert "/help commands" in commands
        assert "Core" in commands
        assert "Open command center" in commands
        assert "/memory" in commands
        assert "Help Module\nStatus: Available" not in commands
        assert examples is not None
        assert "/help examples" in examples
        assert "Memory:" in examples
        assert "show my memories" in examples
        assert "remind me in 30 minutes" in examples
        assert "order biryani" in examples
        assert "Help Module\nStatus: Available" not in examples
        assert modules is not None
        assert "/help modules" in modules
        assert "Memory" in modules
        assert "Saved facts" in modules
        assert "Phone" in modules
        assert "Future mobile bridge" in modules
        assert "Help Module\nStatus: Available" not in modules
        assert shortcuts is not None
        assert "/help shortcuts" in shortcuts
        assert "Left/Right" in shortcuts
        assert "Up/Down" in shortcuts
        assert "Enter" in shortcuts
        assert "Help Module\nStatus: Available" not in shortcuts

    def test_interactive_help_subcommand_does_not_use_generic_module_help(self) -> None:
        engine = MagicMock()
        engine.engine_id = "mock"
        config = GrandpaConfig()
        config.intelligence.default_model = "test-model"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("mock", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(chat, ["--model", "test-model"], input="/help examples\n/quit\n")

        assert result.exit_code == 0
        assert "/help examples" in result.output
        assert "show my memories" in result.output
        assert "Help Module" not in result.output
        engine.generate.assert_not_called()

    def test_bare_slash_is_not_routed_as_unknown_command(self) -> None:
        engine = MagicMock()
        engine.engine_id = "mock"
        config = GrandpaConfig()
        config.intelligence.default_model = "test-model"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("mock", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(chat, ["--model", "test-model"], input="/\n/quit\n")

        assert result.exit_code == 0
        assert "Unknown command: /" not in result.output
        engine.generate.assert_not_called()

    def test_submitted_normal_input_is_printed_once(self) -> None:
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = {"content": "Hello! How can I assist you today?"}
        config = GrandpaConfig()
        config.intelligence.default_model = "test-model"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("mock", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(chat, ["--model", "test-model"], input="hi\n/quit\n")

        assert result.exit_code == 0
        assert result.output.count("> hi") == 1
        assert "< Hello! How can I assist you today?" in result.output

    def test_submitted_slash_command_is_printed_once(self) -> None:
        engine = MagicMock()
        engine.engine_id = "mock"
        config = GrandpaConfig()
        config.intelligence.default_model = "test-model"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("mock", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(chat, ["--model", "test-model"], input="/help\n/quit\n")

        assert result.exit_code == 0
        assert result.output.count("> /help") == 1
        assert "Grandpa Command Center" in result.output
        engine.generate.assert_not_called()

    def test_empty_input_is_not_printed_as_user_message(self) -> None:
        engine = MagicMock()
        engine.engine_id = "mock"
        config = GrandpaConfig()
        config.intelligence.default_model = "test-model"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("mock", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(chat, ["--model", "test-model"], input="\n/quit\n")

        assert result.exit_code == 0
        assert "> \n" not in result.output
        assert engine.generate.call_count == 0


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

    def test_chat_input_fallback_when_prompt_toolkit_unavailable(self, monkeypatch) -> None:
        monkeypatch.setattr(input_ui, "PROMPT_TOOLKIT_AVAILABLE", False)
        prompts = []

        def fake_input(prompt=""):
            prompts.append(prompt)
            return "/help"

        monkeypatch.setattr("builtins.input", fake_input)

        assert input_ui.read_chat_input() == "/help"
        assert prompts == ["> "]
        assert "You>" not in prompts

    def test_prompt_colors_are_theme_correct(self) -> None:
        assert input_ui.USER_PROMPT == "> "
        assert input_ui.USER_PROMPT_COLOR == "#6244c5"
        assert input_ui.ASSISTANT_PROMPT_COLOR == "#ffc448"
        assert theme.TEXT_ACCENT == "#6244c5"

    def test_render_user_message_uses_purple_prompt(self) -> None:
        console = MagicMock()

        render_user_message(console, "hi")

        assert console.print.call_args.args[0] == "[bold #6244c5]>[/bold #6244c5] hi"

    def test_assistant_prompt_uses_purple_marker(self) -> None:
        console = MagicMock()

        theme.render_assistant_response(console, "hello")

        first_call = console.print.call_args_list[0]
        assert "<" in first_call.args[0]
        assert "#ffc448" in first_call.args[0]


class TestSlashCommandRegistry:
    def test_registry_contains_expected_commands(self) -> None:
        names = set(command_names())

        assert {"/help", "/mode", "/memory", "/reminders", "/desktop", "/phone", "/order", "/github"} <= names

    def test_registry_has_friendly_labels(self) -> None:
        assert get_command("/help").display_label == "Help"  # type: ignore[union-attr]
        assert get_command("/status").display_label == "Status"  # type: ignore[union-attr]
        assert get_command("/github").display_label == "GitHub"  # type: ignore[union-attr]

    def test_mode_subcommands_exist(self) -> None:
        command = get_command("/mode")

        assert command is not None
        assert "/mode list" in command.subcommands
        assert "/mode learning" in command.subcommands

    def test_help_preview_items_exist(self) -> None:
        assert command_preview_items("/help") == [
            "/help",
            "/help commands",
            "/help examples",
            "/help modules",
        ]
        assert [item.label for item in command_preview_options("/help")] == [
            "Help",
            "Commands",
            "Examples",
            "Modules",
        ]

    def test_memory_and_reminder_subcommands_exist(self) -> None:
        memory = get_command("/memory")
        reminders = get_command("/reminders")

        assert memory is not None
        assert reminders is not None
        assert "/memory search <query>" in memory.subcommands
        assert "/memory forget <query or id>" in memory.subcommands
        assert "/reminders list" in reminders.subcommands
        assert "/reminders cancel <id>" in reminders.subcommands

    def test_unknown_suggestions_use_registry_commands(self) -> None:
        message = unknown_command_message("/abc")

        assert "Unknown command: /abc" in message
        for command in ("/help", "/memory", "/reminders", "/desktop", "/phone"):
            assert command in command_names()
            assert command in message

    def test_picker_top_level_suggestions_are_horizontal_candidates(self) -> None:
        suggestions = input_ui._top_level_suggestions("/")
        names = [name for name, _description in suggestions]
        labels = [label for _name, label in suggestions]

        assert names[:3] == ["/help", "/status", "/mode"]
        assert labels[:3] == ["Help", "Status", "Mode"]
        assert "/phone" in names
        assert "/order" in names
        assert "/help" not in labels

    def test_live_slash_completion_returns_top_level_commands(self) -> None:
        completions = input_ui._completion_candidates("/", input_ui.SlashPickerState())

        assert completions
        assert completions[0][0] == "/help"

    def test_picker_toolbar_shows_horizontal_and_vertical_commands(self) -> None:
        state = input_ui.SlashPickerState()
        state.preview_index = 3

        lines = input_ui._picker_toolbar_lines("/", state)

        assert lines[0] == "Slash Commands"
        assert "Help  Status  Mode" in lines[2]
        assert "/help  /status  /mode" not in lines[2]
        assert not any(line.startswith("Selected:") for line in lines)
        assert "  Help" in lines
        assert "  Help commands" in lines
        assert "  Help examples" in lines
        assert "> Help modules" in lines
        assert not any(line.strip().startswith("/") for line in lines[4:])

    def test_picker_display_labels_keep_command_values_for_selection(self) -> None:
        state = input_ui.SlashPickerState()
        state.top_index = 2
        state.preview_index = 0

        lines = input_ui._picker_toolbar_lines("/", state)

        assert "Mode" in lines[2]
        assert not any(line.startswith("Selected:") for line in lines)
        assert any(line.endswith("Mode list") for line in lines)

        class FakeBuffer:
            text = "/"
            cursor_position = 0

        buffer = FakeBuffer()
        assert input_ui._apply_picker_selection(buffer, state) is True
        assert buffer.text == "/mode list"
        assert buffer.cursor_position == len("/mode list")

    def test_picker_toolbar_uses_dark_theme_fragments(self) -> None:
        fragments = input_ui._picker_toolbar_fragments("/", input_ui.SlashPickerState())
        styles = [style for style, _text in fragments]

        assert fragments
        assert "class:picker.title" in styles
        assert "class:picker.command" in styles
        assert "class:picker.current" in styles
        assert input_ui.PICKER_BACKGROUND_COLOR == "#181818"
        assert input_ui.PICKER_COMMAND_COLOR == "#6244c5"

    def test_runtime_input_uses_custom_dark_slash_layout(self, monkeypatch) -> None:
        captured = {}

        class FakeBuffer:
            def __init__(self, **kwargs):
                captured["buffer_kwargs"] = kwargs

        class FakeBufferControl:
            def __init__(self, buffer):
                captured["input_control_buffer"] = buffer

        class FakeApp:
            def run(self):
                return "/help"

        def fake_app(buffer, input_control, picker_state, bindings):
            captured["buffer"] = buffer
            captured["input_control"] = input_control
            captured["picker_state"] = picker_state
            captured["bindings"] = bindings
            return FakeApp()

        monkeypatch.setattr(input_ui, "PROMPT_TOOLKIT_AVAILABLE", True)
        monkeypatch.setattr(input_ui.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(input_ui, "Buffer", FakeBuffer)
        monkeypatch.setattr(input_ui, "BufferControl", FakeBufferControl)
        monkeypatch.setattr(input_ui, "_slash_input_application", fake_app)

        assert input_ui.read_chat_input() == "/help"
        assert captured["buffer_kwargs"] == {"multiline": False}
        assert captured["input_control_buffer"] is captured["buffer"]
        assert isinstance(captured["picker_state"], input_ui.SlashPickerState)
        assert captured["bindings"] is not None
        styles = input_ui._picker_style_dict()
        assert "bottom-toolbar" not in styles
        assert styles["picker.background"] == "bg:#181818 #ffffff"
        assert styles["picker.command"] == "bg:#181818 #6244c5"

    def test_picker_subcommand_suggestions_are_available(self) -> None:
        suggestions = input_ui._subcommand_suggestions("/mode")
        names = [name for name, _description in suggestions]

        assert "/mode list" in names
        assert "/mode learning" in names

    def test_picker_preview_lines_include_selected_command_details(self) -> None:
        assert input_ui._picker_preview_lines("/help") == [
            "Help",
            "Help commands",
            "Help examples",
            "Help modules",
        ]
        mode_lines = input_ui._picker_preview_lines("/mode")
        memory_lines = input_ui._picker_preview_lines("/memory")
        reminder_lines = input_ui._picker_preview_lines("/reminders")

        assert "Mode list" in mode_lines
        assert "Mode show" in mode_lines
        assert "Mode coding" in mode_lines
        assert not any(line.startswith("/") for line in mode_lines)
        assert "Memory list" in memory_lines
        assert "Memory all" in memory_lines
        assert "Memory search <query>" in memory_lines
        assert "Memory forget <query or id>" in memory_lines
        assert "Reminders cancel <id>" in reminder_lines

    def test_picker_preview_options_preserve_submit_commands(self) -> None:
        assert input_ui._command_preview_options("/mode")[0] == ("/mode list", "List")
        assert input_ui._command_preview_options("/mode")[2] == ("/mode coding", "Coding")
        assert input_ui._command_preview_options("/memory")[2] == ("/memory search <query>", "Search Query")

    def test_model_preview_uses_installed_models(self, monkeypatch) -> None:
        monkeypatch.setattr(input_ui, "_installed_ollama_models", lambda: ["gemma3:4b", "grandpa-fast:latest"])

        assert input_ui._picker_preview_lines("/model") == [
            "Model",
            "gemma3:4b",
            "grandpa-fast:latest",
        ]
        assert input_ui._command_preview_options("/model")[1] == ("/model gemma3:4b", "gemma3:4b")

    def test_model_preview_handles_ollama_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(input_ui, "_installed_ollama_models", lambda: [])

        lines = input_ui._picker_preview_lines("/model")

        assert "No local models found" in lines
        assert "Install with: ollama pull qwen2.5:3b" in lines


class TestChatSlashCommands:
    def test_apps_slash_routes_to_application_manager(self, monkeypatch) -> None:
        calls: list[str] = []

        def fake_handle(command: str):
            calls.append(command)
            return type("Result", (), {"message": "Installed applications: Chrome."})()

        monkeypatch.setattr("grandpa.desktop.automation.handle_desktop_command", fake_handle)

        message = _handle_apps_slash_command("/apps list")

        assert message == "Installed applications: Chrome."
        assert calls == ["list installed applications"]

    def test_apps_slash_help(self) -> None:
        message = _handle_apps_slash_command("/apps")

        assert message is not None
        assert "/apps scan" in message
        assert "/apps search <name>" in message

    def test_module_help_phone(self) -> None:
        message = _handle_module_slash_command("/phone")

        assert message is not None
        assert "Phone Module" in message
        assert "Planned / Not configured" in message
        assert "/call <contact>" in message
        assert "Android companion app" in message

    def test_module_help_desktop(self) -> None:
        message = _handle_module_slash_command("/desktop")

        assert message is not None
        assert "Desktop Module" in message
        assert "Available" in message
        assert "permission" in message.lower()

    def test_module_help_order(self) -> None:
        message = _handle_module_slash_command("/order")

        assert message is not None
        assert "Order Module" in message
        assert "Planned / Not configured" in message
        assert "will not place real orders" in message

    def test_mode_help(self) -> None:
        message = _handle_module_slash_command("/mode")

        assert message is not None
        assert "Assistant Modes" in message
        assert "/mode list" in message
        assert "/mode learning" in message

    def test_unknown_slash_command_message(self) -> None:
        message = _unknown_slash_command_message("/abc")

        assert "Unknown command: /abc" in message
        assert "/help" in message
        assert "/memory" in message
        assert "/reminders" in message
        assert "/desktop" in message
        assert "/phone" in message

    def test_memory_help(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")

        message = _handle_memory_slash_command("/memory", store=store)

        assert message is not None
        assert "/memory list" in message
        assert "/memory all" in message
        assert "/memory search <query>" in message
        assert "/memory forget <query or id>" in message

    def test_memory_list(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("preferences", "name", "Hari")

        message = _handle_memory_slash_command("/memory list", store=store)

        assert message is not None
        assert "Saved memories:" in message
        assert "Hari" in message
        assert "Use /memory all" in message

    def test_memory_list_hides_internal_entries_by_default(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("preferences", "name", "Hari")
        store.remember("work_context", "agent_goal_setup", "internal goal")
        store.remember("note", "multi_agent_mag_task", "internal orchestration")
        store.remember("note", "burn_in_validation_marker", "local-only")
        store.remember("note", "marker", "burn in validation marker")

        message = _handle_memory_slash_command("/memory list", store=store)

        assert message is not None
        assert "Hari" in message
        assert "agent_goal_setup" not in message
        assert "multi_agent_mag_task" not in message
        assert "burn_in_validation_marker" not in message
        assert "burn in validation marker" not in message
        assert "Use /memory all" in message

    def test_memory_all_shows_internal_entries(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("work_context", "agent_goal_setup", "internal goal")
        store.remember("note", "burn_in_validation_marker", "local-only")

        message = _handle_memory_slash_command("/memory all", store=store)

        assert message is not None
        assert "Saved memories:" in message
        assert "agent_goal_setup" in message
        assert "internal goal" in message
        assert "burn_in_validation_marker" in message

    def test_memory_list_empty_after_filter_has_guidance(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("work_context", "agent_goal_setup", "internal goal")

        message = _handle_memory_slash_command("/memory list", store=store)

        assert message == (
            "No user-facing memories found.\n"
            "Use /memory all to show internal memories.\n"
            "You can save one with: remember my name is Hari"
        )

    def test_memory_list_deduplicates_repeated_tool_values(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("apps_tools", "uses_vs_code", "VS Code")
        store.remember("note", "uses", "VS Code")

        message = _handle_memory_slash_command("/memory list", store=store)

        assert message is not None
        assert message.count("VS Code") == 1
        assert "Tools & Preferences\n- uses: VS Code" in message

    def test_memory_search(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("note", "ai_automation", "I am learning AI automation")

        message = _handle_memory_slash_command("/memory search automation", store=store)

        assert message is not None
        assert "Matching memories:" in message
        assert "AI automation" in message

    def test_memory_search_vs_code_excludes_unrelated_project(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("apps_tools", "uses_vs_code", "VS Code")
        store.remember("project", "project", "Grandpa")

        message = _handle_memory_slash_command("/memory search VS Code", store=store)

        assert message is not None
        assert "Matching memories:" in message
        assert "uses_vs_code" in message
        assert "VS Code" in message
        assert "project/project" not in message
        assert "Grandpa" not in message

    def test_memory_search_grandpa_returns_project(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("apps_tools", "uses_vs_code", "VS Code")
        store.remember("project", "project", "Grandpa")

        message = _handle_memory_slash_command("/memory search Grandpa", store=store)

        assert message is not None
        assert "Matching memories:" in message
        assert "project/project" in message
        assert "Grandpa" in message
        assert "uses_vs_code" not in message

    def test_memory_search_filters_internal_entries_by_default(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("work_context", "agent_goal_browser", "browser automation diagnostics")

        message = _handle_memory_slash_command("/memory search browser", store=store)

        assert message == "No memories found."

    def test_memory_search_all_includes_internal_entries(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("work_context", "agent_goal_browser", "browser automation diagnostics")

        message = _handle_memory_slash_command("/memory search browser --all", store=store)

        assert message is not None
        assert "Matching memories:" in message
        assert "agent_goal_browser" in message

    def test_memory_search_all_keeps_query_relevance(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("work_context", "agent_goal_grandpa", "Grandpa internal task")
        store.remember("work_context", "agent_goal_browser", "browser automation diagnostics")

        message = _handle_memory_slash_command("/memory search Grandpa --all", store=store)

        assert message is not None
        assert "Matching memories:" in message
        assert "agent_goal_grandpa" in message
        assert "agent_goal_browser" not in message

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

    def test_unknown_slash_command_does_not_call_llm(self) -> None:
        engine = MagicMock()
        engine.engine_id = "mock"
        config = GrandpaConfig()
        config.intelligence.default_model = "test-model"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("mock", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(chat, ["--model", "test-model"], input="/abc\n/quit\n")

        assert result.exit_code == 0
        assert "Unknown command: /abc" in result.output
        engine.generate.assert_not_called()

    def test_model_argument_changes_model_without_picker(self) -> None:
        engine = MagicMock()
        engine.engine_id = "mock"
        config = GrandpaConfig()
        config.intelligence.default_model = "test-model"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("mock", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(chat, ["--model", "test-model"], input="/model grandpa-fast:latest\n/quit\n")

        assert result.exit_code == 0
        assert "Model changed to" in result.output
        assert "grandpa-fast:latest" in result.output
        engine.generate.assert_not_called()

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

    def test_show_all_memories_routes_to_raw_memory_list(self, tmp_path) -> None:
        store = MemoryStore(tmp_path / "memory.db")
        store.remember("work_context", "agent_goal_setup", "internal goal")

        message = _handle_natural_assistant_intent("show all memories", memory_store=store)

        assert message is not None
        assert "Saved memories:" in message
        assert "agent_goal_setup" in message

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

    def test_ollama_low_memory_load_failure_has_actionable_message(
        self,
        tmp_path,
    ) -> None:
        engine = MagicMock()
        engine.engine_id = "ollama"
        engine.generate.side_effect = EngineModelLoadError(
            "grandpa-fast:latest",
            (
                "Ollama could not load grandpa-fast:latest because available "
                "memory is too low. Close memory-heavy apps or use "
                "grandpa-light:latest."
            ),
            low_memory=True,
        )
        config = GrandpaConfig()
        config.agent.default_agent = "none"
        config.intelligence.default_model = "grandpa-fast:latest"
        log_path = tmp_path / "server.log"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("ollama", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
            patch("grandpa.cli.chat_cmd._generation_log_path", return_value=log_path),
        ):
            result = CliRunner().invoke(
                chat,
                ["--model", "grandpa-fast:latest"],
                input="hello\n",
            )

        assert result.exit_code == 1
        assert "available memory is too low" in result.output
        assert "grandpa-light:latest" in result.output
        assert "Traceback" not in result.output
        assert "Chat generation failed" in log_path.read_text(encoding="utf-8")

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

    def test_generic_generation_error_logs_traceback(self, tmp_path) -> None:
        engine = MagicMock()
        engine.engine_id = "ollama"
        engine.generate.side_effect = RuntimeError("programming bug")
        config = GrandpaConfig()
        config.agent.default_agent = "none"
        config.intelligence.default_model = "test-model"
        log_path = tmp_path / "server.log"

        with (
            patch("grandpa.cli.chat_cmd.load_config", return_value=config),
            patch("grandpa.engine.get_engine", return_value=("ollama", engine)),
            patch("grandpa.intelligence.register_builtin_models"),
            patch("grandpa.cli.chat_cmd._generation_log_path", return_value=log_path),
        ):
            result = CliRunner().invoke(
                chat,
                ["--model", "test-model"],
                input="hello\n",
            )

        assert result.exit_code == 0
        assert "programming bug" in result.output
        assert "Traceback" not in result.output
        log_text = log_path.read_text(encoding="utf-8")
        assert "Chat generation failed" in log_text
        assert "RuntimeError: programming bug" in log_text
