from __future__ import annotations

from dataclasses import dataclass

from grandpa.desktop.automation import DesktopParser, handle_desktop_command


@dataclass
class FakePcResponse:
    ok: bool = True
    status: str = "completed"
    message: str = "completed"
    approval_required: bool = False


def test_parse_open_app_aliases() -> None:
    parser = DesktopParser()

    chrome = parser.parse("Launch Google Chrome")
    vscode = parser.parse("Start Visual Studio Code")
    paint = parser.parse("Open Paint")

    assert chrome is not None
    assert chrome.pc_action_type == "open_app"
    assert chrome.target == "chrome"
    assert vscode is not None
    assert vscode.target == "vscode"
    assert paint is not None
    assert paint.target == "paint"


def test_parse_open_known_user_folder() -> None:
    action = DesktopParser().parse("Go to Downloads")

    assert action is not None
    assert action.pc_action_type == "open_folder"
    assert action.label == "Downloads"
    assert action.target.endswith("Downloads")


def test_parse_close_app() -> None:
    action = DesktopParser().parse("Close VS Code")

    assert action is not None
    assert action.pc_action_type == "close_app"
    assert action.target == "vscode"


def test_parse_app_window_controls() -> None:
    parser = DesktopParser()

    minimize = parser.parse("Minimize Chrome")
    bring = parser.parse("Bring Spotify to front")

    assert minimize is not None
    assert minimize.pc_action_type == "minimize_window"
    assert minimize.target == "chrome"
    assert bring is not None
    assert bring.pc_action_type == "focus_window"
    assert bring.target == "spotify"


def test_parse_restart_app_requires_confirmation() -> None:
    action = DesktopParser().parse("Restart Spotify")

    assert action is not None
    assert action.pc_action_type == "apps_restart"
    assert action.requires_confirmation is True


def test_parse_volume_commands() -> None:
    parser = DesktopParser()

    mute = parser.parse("Mute sound")
    level = parser.parse("Set volume to 80")

    assert mute is not None
    assert mute.pc_action_type == "volume_mute"
    assert level is not None
    assert level.pc_action_type == "volume_set"
    assert level.args["level"] == 80


def test_parse_power_and_recycle_bin_confirmation() -> None:
    parser = DesktopParser()

    lock = parser.parse("Lock computer")
    shutdown = parser.parse("Shutdown PC")
    recycle = parser.parse("Empty recycle bin")

    assert lock is not None
    assert lock.pc_action_type == "system_lock"
    assert lock.requires_confirmation is False
    assert shutdown is not None
    assert shutdown.pc_action_type == "system_shutdown"
    assert shutdown.requires_confirmation is True
    assert recycle is not None
    assert recycle.pc_action_type == "empty_recycle_bin"
    assert recycle.requires_confirmation is True


def test_handle_desktop_command_runs_through_pc_control_payload() -> None:
    payloads: list[dict] = []

    def fake_runner(payload):
        payloads.append(payload)
        return FakePcResponse(message="Opening Chrome.")

    result = handle_desktop_command("Open Chrome", runner=fake_runner)

    assert result.status == "handled"
    assert result.message == "Chrome opened."
    assert payloads == [
        {
            "action_type": "open_app",
            "target": "chrome",
            "args": {},
            "dry_run": False,
            "require_approval": False,
        }
    ]


def test_dangerous_action_uses_confirmation_payload() -> None:
    payloads: list[dict] = []

    def fake_runner(payload):
        payloads.append(payload)
        return FakePcResponse(False, "approval_required", "Approval required.", True)

    result = handle_desktop_command("Restart computer", runner=fake_runner)

    assert result.status == "needs_confirmation"
    assert result.message == "Approval required."
    assert payloads[0]["action_type"] == "system_restart"
    assert payloads[0]["require_approval"] is True


def test_unknown_desktop_command_falls_back() -> None:
    result = handle_desktop_command("tell me a joke")

    assert result.should_fallback
