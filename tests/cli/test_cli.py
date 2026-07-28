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

    def test_telemetry_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["telemetry", "--help"])
        assert result.exit_code == 0
        assert "stats" in result.output
        assert "export" in result.output
        assert "clear" in result.output

    def test_scheduler_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["scheduler", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "list" in result.output
        assert "pause" in result.output
        assert "resume" in result.output
        assert "cancel" in result.output

    def test_core_commands_remain_registered(self) -> None:
        commands = set(cli.commands)

        assert {"doctor", "chat", "reminders"}.issubset(commands)

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
