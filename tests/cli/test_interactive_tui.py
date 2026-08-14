from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from rich.console import Console

from grandpa.cli import cli, input_ui
from grandpa.cli._first_run import check_and_route
from grandpa.cli.interactive_tui import (
    INTERACTIVE_COMMANDS,
    TUI_PROMPT,
    InteractiveSession,
    render_startup_header,
)
from grandpa.cli.theme import resolve_username, user_prompt
from grandpa.core.config import GrandpaConfig, validate_config_key
from grandpa.core.types import Message, Role


class FakeEngine:
    def health(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return ["grandpa-fast:latest", "grandpa-light:latest"]


def make_session(console: Console | None = None) -> InteractiveSession:
    return InteractiveSession(
        console=console or Console(record=True),
        config=GrandpaConfig(),
        engine_name="ollama",
        engine=FakeEngine(),
        model="grandpa-fast:latest",
        history=[],
    )


def test_bare_cli_routes_to_interactive_chat() -> None:
    context = MagicMock()
    context.invoked_subcommand = None

    check_and_route(context)

    (command,) = context.invoke.call_args.args
    assert command.name == "launcher"
    kwargs = context.invoke.call_args.kwargs
    assert kwargs.get("tui_mode") is True or kwargs.get("tui_mode") is None


def test_bare_cli_renders_modern_logo_once(monkeypatch) -> None:
    config = GrandpaConfig()
    config.intelligence.default_model = "test-model"
    monkeypatch.setenv("GRANDPA_TESTING", "1")

    with (
        patch("grandpa.cli.launcher.load_config", return_value=config),
        patch("grandpa.cli.launcher.ensure_profile", return_value=config) as onboarding,
        patch("grandpa.cli.launcher.run_interactive_menu", return_value="6") as menu,
        patch("grandpa.cli.launcher.render_logo"),
    ):
        result = CliRunner().invoke(cli, input="\n")

    assert result.exit_code == 0
    onboarding.assert_called_once()
    menu.assert_called_once()


def test_interactive_registry_contains_required_commands() -> None:
    names = {command.name for command in INTERACTIVE_COMMANDS.commands}

    assert {
        "/help",
        "/clear",
        "/exit",
        "/status",
        "/model",
        "/engine",
        "/memory",
        "/voice",
        "/doctor",
        "/config",
        "/permissions",
        "/compact",
        "/history",
        "/profile",
        "/whoami",
    } <= names


def test_local_slash_command_does_not_need_generation() -> None:
    session = make_session()

    result = INTERACTIVE_COMMANDS.dispatch(session, "/status")

    assert result.handled is True
    assert "Engine: ollama" in (result.message or "")
    assert "Model: grandpa-fast:latest" in (result.message or "")


def test_model_command_updates_current_session() -> None:
    session = make_session()

    result = INTERACTIVE_COMMANDS.dispatch(session, "/model grandpa-light:latest")

    assert result.handled is True
    assert session.model == "grandpa-light:latest"


def test_compact_keeps_recent_context() -> None:
    session = make_session()
    session.history.extend(
        Message(role=Role.USER, content=f"message {index}") for index in range(12)
    )

    result = INTERACTIVE_COMMANDS.dispatch(session, "/compact")

    assert result.handled is True
    assert len(session.history) == 8
    assert session.history[0].content == "message 4"


def test_startup_header_is_compact_and_status_remains_detailed() -> None:
    console = Console(record=True, width=120)
    session = make_session(console)

    render_startup_header(session)

    output = console.export_text()
    assert "██████╗ ██████╗" in output
    assert "Grandpa v" in output
    assert "| Ollama | grandpa-fast:latest" in output
    assert "Directory" not in output
    assert "Memory" not in output
    assert "Type /help for commands" in output

    status = INTERACTIVE_COMMANDS.dispatch(session, "/status")
    assert "Directory:" in (status.message or "")
    assert "Memory:" in (status.message or "")
    assert "Ollama:" in (status.message or "")


def test_prompt_uses_default_username() -> None:
    assert TUI_PROMPT == "Username > "
    assert GrandpaConfig().user.username == "Username"


def test_prompt_uses_configured_username() -> None:
    config = GrandpaConfig()
    config.user.username = "Hari"

    assert resolve_username(config) == "Hari"
    assert user_prompt(resolve_username(config)) == "Hari > "
    assert validate_config_key("user.username") is str


def test_profile_and_whoami_commands_use_local_session_profile() -> None:
    session = make_session()
    session.config.user.username = "Hari"
    session.config.user.onboarding_completed = True
    session.username = "Hari"

    profile_result = INTERACTIVE_COMMANDS.dispatch(session, "/profile")
    whoami_result = INTERACTIVE_COMMANDS.dispatch(session, "/whoami")

    assert "Name: Hari" in (profile_result.message or "")
    assert "Mode: Local only" in (profile_result.message or "")
    assert whoami_result.message == "Hari\nMode: Local only"


def test_profile_edit_refreshes_prompt_name_for_current_session() -> None:
    session = make_session()
    updated = GrandpaConfig()
    updated.user.username = "Hari"
    updated.user.onboarding_completed = True

    with patch("grandpa.profile.configure_profile", return_value=updated):
        result = INTERACTIVE_COMMANDS.dispatch(session, "/profile edit")

    assert result.handled is True
    assert session.username == "Hari"
    assert "next launch" in (result.message or "")


def test_tui_input_enables_multiline_and_persistent_history(
    monkeypatch, tmp_path
) -> None:
    captured: dict[str, object] = {}

    class FakeHistory:
        def __init__(self, path: str) -> None:
            captured["history_path"] = path

    class FakeBuffer:
        def __init__(self, **kwargs) -> None:
            captured["buffer_kwargs"] = kwargs

    class FakeBufferControl:
        def __init__(self, buffer) -> None:
            captured["buffer"] = buffer

    class FakeApp:
        def run(self) -> str:
            return "hello\nworld"

    def fake_application(*_args, **kwargs):
        captured["prompt"] = kwargs["prompt"]
        return FakeApp()

    history_path = tmp_path / "state" / "history"
    monkeypatch.setattr(input_ui, "PROMPT_TOOLKIT_AVAILABLE", True)
    monkeypatch.setattr(input_ui.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(input_ui, "FileHistory", FakeHistory)
    monkeypatch.setattr(input_ui, "Buffer", FakeBuffer)
    monkeypatch.setattr(input_ui, "BufferControl", FakeBufferControl)
    monkeypatch.setattr(input_ui, "_slash_input_application", fake_application)

    result = input_ui.read_chat_input(
        TUI_PROMPT,
        history_path=history_path,
        multiline=True,
    )

    assert result == "hello\nworld"
    assert captured["prompt"] == TUI_PROMPT
    assert captured["history_path"] == str(history_path)
    assert captured["buffer_kwargs"]["multiline"] is True
    assert isinstance(captured["buffer_kwargs"]["history"], FakeHistory)


def test_tui_falls_back_when_windows_console_buffer_is_unavailable(
    monkeypatch,
) -> None:
    class NoConsoleScreenBufferError(Exception):
        pass

    monkeypatch.setattr(input_ui, "PROMPT_TOOLKIT_AVAILABLE", True)
    monkeypatch.setattr(input_ui.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        input_ui,
        "_slash_input_application",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(NoConsoleScreenBufferError()),
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "/exit")

    assert input_ui.read_chat_input("Username > ") == "/exit"


def test_tui_voice_command_subcommands(tmp_path, monkeypatch) -> None:
    session = make_session()
    # Mock config path so it writes to temp path
    config_file = tmp_path / "config.toml"
    monkeypatch.setenv("Grandpa_CONFIG", str(config_file))

    # 1. Test empty /voice
    res = INTERACTIVE_COMMANDS.dispatch(session, "/voice")
    assert "Usage:" in res.message
    assert "/voice status" in res.message

    # 2. Test /voice status
    # Trigger speech backend registration
    import grandpa.speech  # noqa: F401 - registers local TTS backends

    res = INTERACTIVE_COMMANDS.dispatch(session, "/voice status")
    assert "Voice: Enabled" in res.message
    assert "TTS Backend: kokoro" in res.message

    # 3. Test /voice off
    res = INTERACTIVE_COMMANDS.dispatch(session, "/voice off")
    assert "Voice output disabled." in res.message
    assert session.config.tts.enabled is False
    assert config_file.exists()
    assert "enabled = false" in config_file.read_text().lower()

    # 4. Test /voice on
    res = INTERACTIVE_COMMANDS.dispatch(session, "/voice on")
    assert "Voice output enabled." in res.message
    assert session.config.tts.enabled is True
    assert "enabled = true" in config_file.read_text().lower()

    # 5. Test /voice backend with valid and invalid backends
    res = INTERACTIVE_COMMANDS.dispatch(session, "/voice backend grandpa_voice")
    assert "Voice backend changed to 'grandpa_voice'" in res.message
    assert session.config.tts.backend == "grandpa_voice"

    res = INTERACTIVE_COMMANDS.dispatch(session, "/voice backend invalid_backend_name")
    assert "is not registered" in res.message
