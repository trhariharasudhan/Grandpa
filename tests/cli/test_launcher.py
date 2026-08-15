from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import click
import pytest
from click.testing import CliRunner

from grandpa.cli.launcher import launcher as launcher_cmd
from grandpa.core.config import load_config
from grandpa.profile import atomic_update_profile


@pytest.fixture
def temp_config(tmp_path: Path, monkeypatch) -> Path:
    config_file = tmp_path / "config.toml"
    monkeypatch.setenv("Grandpa_CONFIG", str(config_file))
    monkeypatch.setenv("GRANDPA_TESTING", "1")
    atomic_update_profile(
        config_file,
        username="TestUser",
        onboarding_completed=True,
    )
    load_config.cache_clear()
    return config_file


def test_launcher_non_interactive_fallback(temp_config, monkeypatch) -> None:
    # Set stdin.isatty to False to simulate non-interactive environment
    monkeypatch.delenv("GRANDPA_TESTING", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    runner = CliRunner()
    result = runner.invoke(launcher_cmd)
    assert result.exit_code == 0
    assert "Non-interactive mode detected. Exiting launcher." in result.output


def test_launcher_exit_action(temp_config, monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # Mock menu to return exit action immediately
    mock_menu = MagicMock(return_value="exit")
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", mock_menu)

    runner = CliRunner()
    result = runner.invoke(launcher_cmd)
    assert result.exit_code == 0
    assert "Goodbye" in result.output


def test_launcher_uses_formal_profile_name_when_title_exists(
    temp_config, monkeypatch
) -> None:
    atomic_update_profile(temp_config, title="Mr.")
    load_config.cache_clear()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    menu = MagicMock(return_value="exit")
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", menu)

    result = CliRunner().invoke(launcher_cmd)

    assert result.exit_code == 0
    assert menu.call_args.args[3] == "Mr. TestUser"


def test_launcher_uses_plain_profile_name_without_title(
    temp_config, monkeypatch
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    menu = MagicMock(return_value="exit")
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", menu)

    result = CliRunner().invoke(launcher_cmd)

    assert result.exit_code == 0
    assert menu.call_args.args[3] == "TestUser"


def test_launcher_chat_action(temp_config, monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # Return "chat" then "exit" to terminate the loop
    menu_responses = ["chat", "exit"]
    mock_menu = MagicMock(side_effect=lambda *args, **kwargs: menu_responses.pop(0))
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", mock_menu)

    # Mock chat invoke to assert tui_mode=True and fullscreen=False
    calls: list[dict[str, object]] = []

    @click.command()
    def fake_chat(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("grandpa.cli.chat_cmd.chat", fake_chat)

    runner = CliRunner()
    result = runner.invoke(launcher_cmd)
    assert result.exit_code == 0
    # Chat should be invoked with fullscreen=False
    assert calls == [{"tui_mode": True, "fullscreen": False}]


def test_launcher_voice_action(temp_config, monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # Return "voice" then "exit"
    menu_responses = ["voice", "exit"]
    mock_menu = MagicMock(side_effect=lambda *args, **kwargs: menu_responses.pop(0))
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", mock_menu)

    calls: list[dict[str, object]] = []

    @click.command()
    def fake_voice(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("grandpa.cli.voice_cmd.voice", fake_voice)

    runner = CliRunner()
    result = runner.invoke(launcher_cmd)
    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0]["no_tts"] is False
    assert calls[0]["wake_word"] is False


def test_launcher_doctor_action(temp_config, monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # Return "doctor" then "exit"
    menu_responses = ["doctor", "exit"]
    mock_menu = MagicMock(side_effect=lambda *args, **kwargs: menu_responses.pop(0))
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", mock_menu)

    # Mock doctor invoke
    calls: list[dict[str, object]] = []

    @click.command()
    def fake_doctor(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("grandpa.cli.doctor_cmd.doctor", fake_doctor)

    # Mock user input to return to launcher
    monkeypatch.setattr("builtins.input", lambda *args: "")

    runner = CliRunner()
    result = runner.invoke(launcher_cmd)
    assert result.exit_code == 0
    assert calls == [{"as_json": False}]


def test_launcher_profile_submenu_view(temp_config, monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # Main menu returns "profile" then "exit"
    main_menu_responses = ["profile", "exit"]
    # Profile submenu returns "view" then "back"
    submenu_responses = ["view", "back"]

    def mock_menu_side_effect(console, title, menu_items, username, last_used):
        if "Profile" in title:
            return submenu_responses.pop(0)
        return main_menu_responses.pop(0)

    mock_menu = MagicMock(side_effect=mock_menu_side_effect)
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", mock_menu)

    # Mock input for "Press Enter to return..."
    monkeypatch.setattr("builtins.input", lambda *args: "")

    runner = CliRunner()
    result = runner.invoke(launcher_cmd)
    assert result.exit_code == 0
    assert "Current Profile:" in result.output


def test_launcher_profile_submenu_reset(temp_config, monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # Main menu returns "profile"
    # Submenu returns "reset"
    # User input confirms "y"
    main_menu_responses = ["profile", "exit"]
    submenu_responses = ["reset", "back"]

    def mock_menu_side_effect(console, title, menu_items, username, last_used):
        if "Profile" in title:
            return submenu_responses.pop(0)
        return main_menu_responses.pop(0)

    mock_menu = MagicMock(side_effect=mock_menu_side_effect)
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", mock_menu)

    # Confirms reset
    monkeypatch.setattr("builtins.input", lambda *args: "y")

    runner = CliRunner()
    result = runner.invoke(launcher_cmd)
    assert result.exit_code == 0
    assert "Profile reset." in result.output


def test_launcher_settings_submenu(temp_config, monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # Route: main menu -> "settings" -> loaded config -> back -> exit
    main_menu_responses = ["settings", "exit"]
    submenu_responses = ["loaded", "back"]

    def mock_menu_side_effect(console, title, menu_items, username, last_used):
        if "Settings" in title:
            return submenu_responses.pop(0)
        return main_menu_responses.pop(0)

    mock_menu = MagicMock(side_effect=mock_menu_side_effect)
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", mock_menu)

    # Mock input for prompt return
    monkeypatch.setattr("builtins.input", lambda *args: "")

    runner = CliRunner()
    result = runner.invoke(launcher_cmd)
    assert result.exit_code == 0
    assert "Loading config from:" in result.output


def test_launcher_settings_submenu_hardware(temp_config, monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    main_menu_responses = ["settings", "exit"]
    submenu_responses = ["hardware", "back"]

    def mock_menu_side_effect(console, title, menu_items, username, last_used):
        if "Settings" in title:
            return submenu_responses.pop(0)
        return main_menu_responses.pop(0)

    mock_menu = MagicMock(side_effect=mock_menu_side_effect)
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", mock_menu)

    monkeypatch.setattr("builtins.input", lambda *args: "")

    runner = CliRunner()
    result = runner.invoke(launcher_cmd)
    assert result.exit_code == 0
    assert "Detected Hardware" in result.output


def test_launcher_saves_last_used_mode(temp_config, monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    menu_responses = ["chat", "exit"]
    mock_menu = MagicMock(side_effect=lambda *args, **kwargs: menu_responses.pop(0))
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", mock_menu)

    @click.command()
    def fake_chat(**_kwargs) -> None:
        return None

    monkeypatch.setattr("grandpa.cli.chat_cmd.chat", fake_chat)

    runner = CliRunner()
    result = runner.invoke(launcher_cmd)
    assert result.exit_code == 0

    load_config.cache_clear()
    config = load_config(temp_config)
    assert getattr(config, "last_used_mode", None) == "Chat Assistant"


def test_ctrl_c_at_root_launcher(temp_config, monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # Return "cancel" (Ctrl+C representation in prompt_toolkit KB)
    mock_menu = MagicMock(return_value="cancel")
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", mock_menu)

    runner = CliRunner()
    result = runner.invoke(launcher_cmd)
    assert result.exit_code == 0
    assert "Goodbye" in result.output


def test_ctrl_c_inside_submenu_returns_to_launcher(temp_config, monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    main_menu_responses = ["profile", "exit"]
    submenu_responses = ["cancel"]  # Ctrl+C inside profile submenu

    def mock_menu_side_effect(console, title, menu_items, username, last_used):
        if "Profile" in title:
            return submenu_responses.pop(0)
        return main_menu_responses.pop(0)

    mock_menu = MagicMock(side_effect=mock_menu_side_effect)
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", mock_menu)

    runner = CliRunner()
    result = runner.invoke(launcher_cmd)
    assert result.exit_code == 0
    assert "Goodbye" in result.output


def test_repeated_invalid_submenu_results_return_to_launcher(
    temp_config, monkeypatch
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    main_menu_responses = ["profile", "exit"]

    def mock_menu_side_effect(_console, title, _items, _username, _last_used):
        if title == "Profile":
            return "obsolete-action"
        return main_menu_responses.pop(0)

    menu = MagicMock(side_effect=mock_menu_side_effect)
    monkeypatch.setattr("grandpa.cli.launcher.run_interactive_menu", menu)

    result = CliRunner().invoke(launcher_cmd)

    assert result.exit_code == 0
    assert "repeated invalid selections" in result.output
    assert menu.call_count == 5
