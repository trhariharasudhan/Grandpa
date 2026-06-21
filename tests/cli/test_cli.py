"""Tests for the CLI skeleton."""

from __future__ import annotations

import importlib
import io
import sys
from pathlib import Path
from unittest import mock

import click
import pytest
from click.testing import CliRunner

import grandpa
from grandpa.cli import cli, main


class TestMainEntryPoint:
    """Tests for the ``Grandpa`` console script entry point."""

    def test_windows_reconfigures_stdout_to_utf8(self) -> None:
        """On Windows, main() must reconfigure stdout/stderr to UTF-8 so that
        CJK characters in CLI output don't trigger UnicodeEncodeError under
        legacy code pages (cp950, cp932, cp949)."""
        stdout_mock = mock.MagicMock(spec=io.TextIOWrapper)
        stderr_mock = mock.MagicMock(spec=io.TextIOWrapper)
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(sys, "stdout", stdout_mock),
            mock.patch.object(sys, "stderr", stderr_mock),
            mock.patch("grandpa.cli.cli") as cli_mock,
        ):
            main()
        stdout_mock.reconfigure.assert_called_once_with(
            encoding="utf-8", errors="replace"
        )
        stderr_mock.reconfigure.assert_called_once_with(
            encoding="utf-8", errors="replace"
        )
        cli_mock.assert_called_once()

    def test_non_windows_does_not_reconfigure(self) -> None:
        """On non-Windows platforms, stdout/stderr are left untouched."""
        stdout_mock = mock.MagicMock(spec=io.TextIOWrapper)
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(sys, "stdout", stdout_mock),
            mock.patch("grandpa.cli.cli") as cli_mock,
        ):
            main()
        stdout_mock.reconfigure.assert_not_called()
        cli_mock.assert_called_once()


class TestCLI:
    def test_help(self) -> None:
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "grandpa" in result.output

    def test_version(self) -> None:
        result = CliRunner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert grandpa.__version__ in result.output

    def test_ask_requires_query(self) -> None:
        result = CliRunner().invoke(cli, ["ask"])
        assert result.exit_code != 0

    def test_serve_needs_engine(self) -> None:
        """Serve requires a running engine; exits with error when none available."""
        result = CliRunner().invoke(cli, ["serve"])
        # Either exits with error (no engine) or succeeds (deps missing)
        # Both are valid states for testing
        out = result.output.lower()
        assert result.exit_code != 0 or "not installed" in out or "no inference" in out

    def test_model_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["model", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "info" in result.output
        assert "pull" in result.output

    def test_memory_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["memory", "--help"])
        assert result.exit_code == 0
        assert "index" in result.output
        assert "search" in result.output
        assert "stats" in result.output

    def test_mine_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["mine", "--help"])
        assert result.exit_code == 0
        assert "doctor" in result.output
        assert "start" in result.output
        assert "stop" in result.output

    def test_telemetry_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["telemetry", "--help"])
        assert result.exit_code == 0
        assert "stats" in result.output
        assert "export" in result.output
        assert "clear" in result.output

    def test_bench_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["bench", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output

    def test_scheduler_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["scheduler", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "list" in result.output
        assert "pause" in result.output
        assert "resume" in result.output
        assert "cancel" in result.output

    def test_channel_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["channel", "--help"])
        assert result.exit_code == 0
        assert "send" in result.output
        assert "list" in result.output

    def test_core_commands_remain_registered(self) -> None:
        commands = set(cli.commands)

        assert {"doctor", "chat", "reminders"}.issubset(commands)

    def test_voice_doctor_command_outputs_status_labels(self, monkeypatch) -> None:
        from grandpa.voice import doctor as voice_doctor_module

        monkeypatch.setattr(
            voice_doctor_module,
            "run_voice_doctor",
            lambda: {
                "ok": True,
                "checks": [
                    {"name": "server import", "status": "pass", "message": "ok"},
                    {"name": "speech dependencies", "status": "warn", "message": "optional"},
                ],
            },
        )

        result = CliRunner().invoke(cli, ["doctor", "--voice"])

        assert result.exit_code == 0
        assert "Grandpa Voice Doctor" in result.output
        assert "PASS" in result.output
        assert "WARN" in result.output
        assert "FAIL" in result.output

    def test_reminders_help_does_not_import_deep_research_modules(self) -> None:
        with mock.patch("importlib.import_module", wraps=importlib.import_module) as spy:
            result = CliRunner().invoke(cli, ["reminders", "--help"])

        assert result.exit_code == 0
        assert "create" in result.output
        imported = [call.args[0] for call in spy.call_args_list]
        assert "grandpa.cli.reminders_cmd" in imported
        assert "grandpa.cli.deep_research_setup_cmd" not in imported
        assert "grandpa.connectors.pipeline" not in imported
        assert "grandpa.connectors.embeddings" not in imported

    def test_deep_research_missing_optional_dependency_guidance(self) -> None:
        real_import_module = importlib.import_module

        def fake_import_module(name: str, package: str | None = None):
            if name == "grandpa.cli.deep_research_setup_cmd":
                raise ModuleNotFoundError("No module named 'numpy'", name="numpy")
            return real_import_module(name, package)

        with mock.patch("importlib.import_module", side_effect=fake_import_module):
            result = CliRunner().invoke(cli, ["deep-research-setup", "--skip-chat"])

        assert result.exit_code != 0
        assert "requires optional dependencies" in result.output
        assert "uv sync --extra memory-faiss" in result.output

    def test_lazy_command_does_not_hide_programming_import_errors(self) -> None:
        real_import_module = importlib.import_module

        def fake_import_module(name: str, package: str | None = None):
            if name == "grandpa.cli.deep_research_setup_cmd":
                raise ModuleNotFoundError(
                    "No module named 'grandpa.internal_typo'",
                    name="grandpa.internal_typo",
                )
            return real_import_module(name, package)

        with mock.patch("importlib.import_module", side_effect=fake_import_module):
            with pytest.raises(ModuleNotFoundError):
                CliRunner().invoke(
                    cli,
                    ["deep-research-setup", "--skip-chat"],
                    catch_exceptions=False,
                )

    def test_lazy_command_preserves_unrelated_programming_errors(self) -> None:
        command = cli.commands["reminders"]
        assert isinstance(command, click.Command)

        with mock.patch.object(command, "_load", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                CliRunner().invoke(
                    cli,
                    ["reminders", "--help"],
                    catch_exceptions=False,
                )

    def test_init_creates_config(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".grandpa"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("grandpa.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("grandpa.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("grandpa.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli, ["init", "--engine", "ollama", "--no-download"]
            )
        assert result.exit_code == 0
        assert config_path.exists()
        content = config_path.read_text()
        assert "[engine]" in content
