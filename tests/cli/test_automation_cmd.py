from __future__ import annotations

from click.testing import CliRunner

from grandpa.automation.models import AutomationResult
from grandpa.cli.automation_cmd import automation


class FakeService:
    def __init__(self) -> None:
        self.commands: list[tuple[str, bool]] = []
        self.confirmed: list[str] = []

    def handle(
        self,
        command: str,
        *,
        dry_run: bool = False,
        target_window: str | None = None,
    ) -> AutomationResult:
        self.commands.append((command, dry_run))
        if command.startswith("click") and not dry_run:
            return AutomationResult(
                "needs_confirmation",
                "I found Save. Do you want me to click it? Yes / No",
                confirmation_token="token",
            )
        return AutomationResult("handled", "Done.")

    def confirm(self, token: str) -> AutomationResult:
        self.confirmed.append(token)
        return AutomationResult("handled", "Clicked.")

    def reject(self, _token: str) -> AutomationResult:
        return AutomationResult("handled", "Automation action cancelled.")


def test_cli_click_confirms_without_real_input(monkeypatch) -> None:
    service = FakeService()
    monkeypatch.setattr(
        "grandpa.cli.automation_cmd.get_automation_service", lambda: service
    )

    result = CliRunner().invoke(automation, ["click", "Save", "--yes"])

    assert result.exit_code == 0
    assert service.commands == [("click Save", False)]
    assert service.confirmed == ["token"]
    assert "Clicked." in result.output


def test_cli_locate_is_read_only(monkeypatch) -> None:
    service = FakeService()
    monkeypatch.setattr(
        "grandpa.cli.automation_cmd.get_automation_service", lambda: service
    )

    result = CliRunner().invoke(automation, ["locate", "Save", "button"])

    assert result.exit_code == 0
    assert service.commands == [("locate Save button", False)]
    assert service.confirmed == []


def test_cli_type_dry_run(monkeypatch) -> None:
    service = FakeService()
    monkeypatch.setattr(
        "grandpa.cli.automation_cmd.get_automation_service", lambda: service
    )

    result = CliRunner().invoke(automation, ["type", "Hello", "World", "--dry-run"])

    assert result.exit_code == 0
    assert service.commands == [("type Hello World", True)]


def test_cli_registers_move_and_press(monkeypatch) -> None:
    service = FakeService()
    monkeypatch.setattr(
        "grandpa.cli.automation_cmd.get_automation_service", lambda: service
    )
    runner = CliRunner()

    moved = runner.invoke(automation, ["move", "--x", "300", "--y", "300"])
    pressed = runner.invoke(
        automation, ["press", "enter", "--window", "Notepad"]
    )

    assert moved.exit_code == 0
    assert pressed.exit_code == 0
    assert service.commands == [
        ("move mouse to 300 300", False),
        ("press enter", False),
    ]


def test_cli_session_retains_and_clears_target(monkeypatch) -> None:
    events: list[str] = []

    class SessionService(FakeService):
        target_window = None

        def handle(self, command: str, **_kwargs) -> AutomationResult:
            events.append(command)
            if command.startswith("focus "):
                self.target_window = type("Target", (), {"label": command[6:]})()
            return AutomationResult("handled", "Done.")

        def clear_target(self) -> None:
            events.append("clear")
            self.target_window = None

    monkeypatch.setattr(
        "grandpa.cli.automation_cmd.ScreenAutomationService", SessionService
    )
    result = CliRunner().invoke(
        automation,
        ["session"],
        input="focus Notepad\ntype Hello\npress enter\nclear target\nstatus\nexit\n",
    )

    assert result.exit_code == 0
    assert events == ["focus Notepad", "type Hello", "press enter", "clear"]
    assert "Target window: none" in result.output
