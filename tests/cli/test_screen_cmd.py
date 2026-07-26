"""CLI tests for read-only Screen Vision."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.cli.screen_cmd import screen
from grandpa.screen.models import ScreenCommandResult, ScreenDiagnosticResult


def test_screen_command_is_registered() -> None:
    assert "screen" in cli.commands
    result = CliRunner().invoke(screen, ["--help"])
    assert result.exit_code == 0
    assert "capture" in result.output
    assert "diagnose" in result.output
    assert "windows" in result.output


def test_screen_capture_options_reach_service() -> None:
    service = __import__("unittest.mock").mock.Mock()
    service.capture.return_value = ScreenCommandResult(
        "handled", "Screenshot captured."
    )
    with patch("grandpa.cli.screen_cmd._service", return_value=service):
        result = CliRunner().invoke(screen, ["capture", "--monitor", "2"])
    assert result.exit_code == 0
    assert "Screenshot captured" in result.output
    service.capture.assert_called_once_with(
        monitor=2,
        active_window=False,
        save=False,
        output=None,
        overwrite=False,
    )


def test_screen_windows_json_output() -> None:
    service = __import__("unittest.mock").mock.Mock()
    service.windows.return_value = ScreenCommandResult(
        "handled", "Open windows", data={"windows": [{"title": "Editor"}]}
    )
    with patch("grandpa.cli.screen_cmd._service", return_value=service):
        result = CliRunner().invoke(screen, ["windows", "--json"])
    assert result.exit_code == 0
    assert '"title": "Editor"' in result.output


def test_screen_diagnose_output() -> None:
    diagnostic = ScreenDiagnosticResult(
        platform="Windows",
        python_executable="python.exe",
        capture_backend="Pillow ImageGrab",
        monitor_count=1,
        primary_monitor=1,
        virtual_desktop_bounds=(0, 0, 1920, 1080),
        active_window_api="ready",
        ocr_provider="pytesseract",
        tesseract_executable="tesseract.exe",
        ocr_language="eng",
        temporary_directory="screen-temp",
    )
    service = __import__("unittest.mock").mock.Mock()
    service.diagnose.return_value = diagnostic
    with patch("grandpa.cli.screen_cmd._service", return_value=service):
        result = CliRunner().invoke(screen, ["diagnose"])
    assert result.exit_code == 0
    assert "Screen Vision diagnostics" in result.output
    assert "Pillow ImageGrab" in result.output
    assert "pytesseract" in result.output
