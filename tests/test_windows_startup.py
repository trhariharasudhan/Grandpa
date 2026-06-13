from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from grandpa.cli.startup_cmd import startup
from grandpa.windows_startup import (
    ENTRY_FILENAME,
    disable_startup,
    enable_startup,
    get_startup_entry_path,
    startup_command,
    startup_status,
)

pytestmark = pytest.mark.core


def _python(tmp_path: Path) -> Path:
    exe = tmp_path / "Python With Spaces" / "python.exe"
    exe.parent.mkdir()
    exe.write_text("fake", encoding="utf-8")
    return exe


def test_startup_command_uses_python_module_entrypoint(tmp_path: Path) -> None:
    exe = _python(tmp_path)

    assert startup_command(exe) == [str(exe), "-m", "grandpa.cli", "start"]


def test_enable_creates_owned_startup_entry(tmp_path: Path) -> None:
    exe = _python(tmp_path)

    result = enable_startup(startup_dir=tmp_path / "Startup", python_executable=exe, platform="win32")

    assert result.ok is True
    entry = tmp_path / "Startup" / ENTRY_FILENAME
    assert result.entry_path == entry
    content = entry.read_text(encoding="utf-8")
    assert "GrandpaAssistant startup entry" in content
    assert f'"{exe}"' in content
    assert '"-m" "grandpa.cli" "start"' in content


def test_enable_is_idempotent(tmp_path: Path) -> None:
    exe = _python(tmp_path)
    startup_dir = tmp_path / "Startup"

    first = enable_startup(startup_dir=startup_dir, python_executable=exe, platform="win32")
    before = first.entry_path.read_text(encoding="utf-8")  # type: ignore[union-attr]
    second = enable_startup(startup_dir=startup_dir, python_executable=exe, platform="win32")

    assert second.ok is True
    assert second.status == "enabled"
    assert first.entry_path.read_text(encoding="utf-8") == before  # type: ignore[union-attr]


def test_status_detects_enabled_state(tmp_path: Path) -> None:
    exe = _python(tmp_path)
    startup_dir = tmp_path / "Startup"
    enable_startup(startup_dir=startup_dir, python_executable=exe, platform="win32")

    result = startup_status(startup_dir=startup_dir, python_executable=exe, platform="win32")

    assert result.ok is True
    assert result.status == "enabled"
    assert result.stale is False


def test_disable_removes_only_grandpa_entry(tmp_path: Path) -> None:
    exe = _python(tmp_path)
    startup_dir = tmp_path / "Startup"
    unrelated = startup_dir / "OtherApp.cmd"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("echo keep", encoding="utf-8")
    enable_startup(startup_dir=startup_dir, python_executable=exe, platform="win32")

    result = disable_startup(startup_dir=startup_dir, platform="win32")

    assert result.ok is True
    assert not (startup_dir / ENTRY_FILENAME).exists()
    assert unrelated.exists()


def test_disable_is_safe_when_already_disabled(tmp_path: Path) -> None:
    result = disable_startup(startup_dir=tmp_path / "Startup", platform="win32")

    assert result.ok is True
    assert result.status == "disabled"


def test_stale_executable_is_reported(tmp_path: Path) -> None:
    missing = tmp_path / "missing python" / "python.exe"
    startup_dir = tmp_path / "Startup"
    enable_startup(startup_dir=startup_dir, python_executable=missing, platform="win32")

    result = startup_status(startup_dir=startup_dir, python_executable=missing, platform="win32")

    assert result.ok is True
    assert result.status == "enabled_stale"
    assert result.stale is True


def test_non_windows_returns_unsupported(tmp_path: Path) -> None:
    result = enable_startup(startup_dir=tmp_path, platform="linux")

    assert result.ok is False
    assert result.unsupported is True
    assert result.status == "unsupported"


def test_refuses_to_overwrite_unrelated_startup_file(tmp_path: Path) -> None:
    startup_dir = tmp_path / "Startup"
    startup_dir.mkdir()
    entry = get_startup_entry_path(startup_dir)
    entry.write_text("echo unrelated", encoding="utf-8")

    result = enable_startup(startup_dir=startup_dir, python_executable=_python(tmp_path), platform="win32")

    assert result.ok is False
    assert result.status == "blocked"
    assert entry.read_text(encoding="utf-8") == "echo unrelated"


def test_permission_error_is_actionable(monkeypatch, tmp_path: Path) -> None:
    exe = _python(tmp_path)

    def fail_write(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "write_text", fail_write)

    result = enable_startup(startup_dir=tmp_path / "Startup", python_executable=exe, platform="win32")

    assert result.ok is False
    assert result.status == "failed"
    assert "permissions" in result.message.lower()


def test_cli_status_calls_startup_manager(monkeypatch, tmp_path: Path) -> None:
    exe = _python(tmp_path)
    result = enable_startup(startup_dir=tmp_path / "Startup", python_executable=exe, platform="win32")
    monkeypatch.setattr("grandpa.cli.startup_cmd.startup_status", lambda: result)

    cli_result = CliRunner().invoke(startup, ["status"])

    assert cli_result.exit_code == 0
    assert "Grandpa startup enabled" in cli_result.output
    assert "grandpa.cli start" in cli_result.output


def test_cli_unsupported_exits_cleanly(monkeypatch) -> None:
    monkeypatch.setattr("grandpa.cli.startup_cmd.startup_status", lambda: startup_status(platform="linux"))

    result = CliRunner().invoke(startup, ["status"])

    assert result.exit_code == 1
    assert "only supported on Windows" in result.output
