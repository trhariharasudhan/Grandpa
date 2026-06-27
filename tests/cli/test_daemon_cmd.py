"""Tests for ``Grandpa start|stop|restart|status`` daemon management commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.cli.daemon_cmd import _pid_alive, _read_pid, _write_pid


class TestDaemonCommands:
    """Core daemon CLI tests."""

    def test_start_command_exists(self) -> None:
        """``Grandpa start --help`` succeeds."""
        result = CliRunner().invoke(cli, ["start", "--help"])
        assert result.exit_code == 0
        out = result.output.lower()
        assert "daemon" in out or "start" in out or "background" in out

    def test_stop_no_server(self) -> None:
        """``Grandpa stop`` when no PID file shows 'not running'."""
        with patch("grandpa.cli.daemon_cmd._read_pid", return_value=None):
            result = CliRunner().invoke(cli, ["stop"])
        assert result.exit_code != 0
        assert "No running server" in result.output

    def test_status_no_server(self) -> None:
        """``Grandpa status`` when no PID file shows 'not running'."""
        with patch("grandpa.cli.daemon_cmd._read_pid", return_value=None):
            result = CliRunner().invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "not running" in result.output

    def test_read_pid_no_file(self, tmp_path: Path) -> None:
        """``_read_pid()`` returns None when no PID file exists."""
        with patch(
            "grandpa.cli.daemon_cmd._PID_FILE",
            tmp_path / "nonexistent.pid",
        ):
            assert _read_pid() is None

    def test_write_and_read_pid(self, tmp_path: Path) -> None:
        """Write a PID, then read it back (mock os.kill to succeed)."""
        pid_file = tmp_path / "server.pid"
        with (
            patch("grandpa.cli.daemon_cmd._PID_FILE", pid_file),
            patch("grandpa.cli.daemon_cmd.DEFAULT_CONFIG_DIR", tmp_path),
            patch("grandpa.cli.daemon_cmd._pid_alive", return_value=True),
        ):
            _write_pid(12345)
            assert pid_file.exists()
            assert _read_pid() == 12345

    def test_read_pid_removes_stale_windows_pid(self, tmp_path: Path) -> None:
        """Stale or invalid Windows PIDs are treated as not running."""
        pid_file = tmp_path / "server.pid"
        pid_file.write_text("999999")
        with (
            patch("grandpa.cli.daemon_cmd._PID_FILE", pid_file),
            patch("grandpa.cli.daemon_cmd._pid_alive", return_value=False),
        ):
            assert _read_pid() is None
        assert not pid_file.exists()

    def test_pid_alive_handles_winerror_87_without_crashing(self) -> None:
        """Windows invalid-PID errors should produce False, not tracebacks."""
        error = OSError(87, "The parameter is incorrect")
        with (
            patch("grandpa.cli.daemon_cmd.platform.system", return_value="Windows"),
            patch("grandpa.cli.daemon_cmd.sys.modules", {"psutil": None}),
            patch("grandpa.cli.daemon_cmd.os.kill", side_effect=error),
        ):
            assert _pid_alive(999999) is False

    def test_status_shows_running(self) -> None:
        """``Grandpa status`` shows running info when PID exists."""
        mock_config = MagicMock()
        mock_config.server.host = "127.0.0.1"
        mock_config.server.port = 8000

        with (
            patch("grandpa.cli.daemon_cmd._read_pid", return_value=9999),
            patch(
                "grandpa.cli.daemon_cmd.load_config",
                return_value=mock_config,
            ),
        ):
            result = CliRunner().invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "running" in result.output
        assert "9999" in result.output

    def test_start_already_running(self) -> None:
        """``Grandpa start`` exits with error when a server is already running."""
        with patch("grandpa.cli.daemon_cmd._read_pid", return_value=42):
            result = CliRunner().invoke(cli, ["start"])
        assert result.exit_code != 0
        assert "already running" in result.output
