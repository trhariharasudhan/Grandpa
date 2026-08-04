import sys
from io import StringIO
from unittest.mock import MagicMock

from rich.console import Console

from grandpa.cli.theme import render_chat_home, render_logo_borderless
from grandpa.voice.presenter import VoicePresenter


def test_voice_presenter_plain_fallbacks():
    # Test screen reader mode (uses plain labels)
    printed = []
    presenter = VoicePresenter(
        quiet=False, no_color=True, screen_reader=True, output=printed.append
    )

    presenter.print_banner("ollama", "base")
    assert any("Voice Assistant" in p for p in printed)

    presenter.print_status("Listening...")
    assert any("Listening..." in p for p in printed)

    presenter.print_user_message("hello")
    assert any("You: hello" in p for p in printed)

    presenter.print_assistant_message("hi")
    assert any("Grandpa: hi" in p for p in printed)

    presenter.print_confirmation_required("close calculator")
    assert any(
        "Confirmation required before executing: close calculator" in p for p in printed
    )

    presenter.print_action_completed("Calculator closed.")
    assert any("Success: Calculator closed." in p for p in printed)

    presenter.print_error("TTS failed")
    assert any("Error: TTS failed" in p for p in printed)


def test_voice_presenter_non_screen_reader_plain():
    # Test non-screen reader plain mode (uses > and <)
    printed = []
    presenter = VoicePresenter(
        quiet=False, no_color=True, screen_reader=False, output=printed.append
    )

    presenter.print_user_message("hello")
    assert any("> hello" in p for p in printed)

    presenter.print_assistant_message("hi")
    assert any("< hi" in p for p in printed)


def test_voice_presenter_rich_modes(monkeypatch):
    # Force terminal encoding to UTF-8 and TTY to test emojis
    mock_stdout = MagicMock()
    mock_stdout.encoding = "utf-8"
    mock_stdout.isatty.return_value = True
    monkeypatch.setattr(sys, "stdout", mock_stdout)

    buffer = StringIO()
    console = Console(file=buffer, color_system="truecolor", force_terminal=True)
    presenter = VoicePresenter(
        quiet=False,
        no_color=False,
        screen_reader=False,
        console=console,
    )

    # Non-exit statuses are no-ops in rich TTY mode
    presenter.print_status("listening")
    assert "Listening" not in buffer.getvalue()

    presenter.print_status("thinking")
    assert "Thinking" not in buffer.getvalue()

    # Exit statuses are no-ops now in TTY mode
    presenter.print_status("stopping")
    assert "Stopped" not in buffer.getvalue()

    # User and assistant messages render directly to console
    buffer.truncate(0)
    buffer.seek(0)
    presenter.print_user_message("hello")
    assert ">" in buffer.getvalue()
    assert "hello" in buffer.getvalue()

    buffer.truncate(0)
    buffer.seek(0)
    presenter.print_assistant_message("hi")
    assert "Grandpa >" in buffer.getvalue()
    assert "hi" in buffer.getvalue()


def test_voice_presenter_quiet_mode():
    printed = []
    presenter = VoicePresenter(quiet=True, output=printed.append)

    presenter.print_banner("ollama", "base")
    presenter.print_status("listening")
    presenter.print_user_message("hello")
    presenter.print_assistant_message("hi")
    presenter.print_confirmation_required("close")
    presenter.print_action_completed("done")
    presenter.print_error("error")

    assert len(printed) == 0


def test_voice_presenter_thinking_animation(monkeypatch):
    mock_stdout = MagicMock()
    mock_stdout.encoding = "utf-8"
    mock_stdout.isatty.return_value = True
    monkeypatch.setattr(sys, "stdout", mock_stdout)

    console = Console(color_system="truecolor", force_terminal=True)
    presenter = VoicePresenter(
        quiet=False,
        no_color=False,
        screen_reader=False,
        console=console,
    )

    # Test start and stop thinking animation
    presenter.start_thinking()
    assert presenter._thinking is not None
    presenter.stop_thinking()
    assert presenter._thinking is None


def test_voice_presenter_listening_animation(monkeypatch):
    mock_stdout = MagicMock()
    mock_stdout.encoding = "utf-8"
    mock_stdout.isatty.return_value = True
    monkeypatch.setattr(sys, "stdout", mock_stdout)

    console = Console(color_system="truecolor", force_terminal=True)
    presenter = VoicePresenter(
        quiet=False,
        no_color=False,
        screen_reader=False,
        console=console,
    )

    # Test start and stop listening animation
    presenter.start_listening()
    assert presenter._listening is not None
    presenter.stop_listening()
    assert presenter._listening is None


def test_chat_logo_borderless_rendering():
    # Chat logo must have no border/Panel, use ACCENT color
    buffer = StringIO()
    console = Console(file=buffer, color_system="truecolor", force_terminal=True)

    render_logo_borderless(console)
    output = buffer.getvalue()

    # Assert no Panel borders are present
    assert "┌" not in output
    assert "┐" not in output
    assert "└" not in output
    assert "┘" not in output

    # Assert the GRANDPA ASCII logo exists
    assert "██████" in output

    # Check render_chat_home wrapper
    buffer.truncate(0)
    buffer.seek(0)
    render_chat_home(console, "ollama", "base", "direct")
    chat_home_output = buffer.getvalue()
    assert "┌" not in chat_home_output
    assert "██████" in chat_home_output


def test_voice_session_interaction_flows(monkeypatch):
    # Mock is_interactive_terminal to return True
    monkeypatch.setattr("grandpa.voice.presenter.is_interactive_terminal", lambda: True)

    buffer = StringIO()
    console = Console(file=buffer, color_system="truecolor", force_terminal=True)
    presenter = VoicePresenter(
        quiet=False,
        no_color=False,
        screen_reader=False,
        console=console,
    )

    # 1. Startup: Prints banner, but must not print "Stopped" on startup
    presenter.print_banner("ollama", "base")
    output = buffer.getvalue()
    assert "Stopped" not in output
    assert "Voice Assistant" in output

    # 2. Listening animation starts
    presenter.start_listening()
    assert presenter._listening is not None
    presenter.stop_listening()
    assert presenter._listening is None

    # 3. Ctrl+C does not show Stopped in presenter print_status
    buffer.truncate(0)
    buffer.seek(0)
    presenter.print_status("Stopping Grandpa Voice Assistant...")
    assert "Stopped" not in buffer.getvalue()
