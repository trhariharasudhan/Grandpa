from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from grandpa.cli.tray_cmd import tray
from grandpa.tray import (
    TRAY_INSTALL_HINT,
    GrandpaTrayController,
    TrayAlreadyRunningError,
    TrayDependencyError,
    TraySingleInstance,
    TrayUnsupportedError,
    build_menu,
    menu_action_labels,
    run_tray_app,
    validate_tray_environment,
)

pytestmark = pytest.mark.core


class _Command:
    def __init__(self) -> None:
        self.callback = MagicMock()


class _Daemon:
    def __init__(self, pid: int | None = None) -> None:
        self.start = _Command()
        self.stop = _Command()
        self._pid = pid
        self._read_pid = MagicMock(side_effect=lambda: self._pid)


def test_missing_tray_dependency_produces_install_guidance(monkeypatch) -> None:
    monkeypatch.setattr("grandpa.tray.sys.platform", "win32")
    monkeypatch.setattr("grandpa.tray.importlib.util.find_spec", lambda name: None if name == "pystray" else object())

    with pytest.raises(TrayDependencyError, match="uv sync --extra tray"):
        validate_tray_environment()


def test_unsupported_platform_returns_cleanly(monkeypatch) -> None:
    monkeypatch.setattr("grandpa.tray.sys.platform", "linux")

    with pytest.raises(TrayUnsupportedError, match="only supported on Windows"):
        validate_tray_environment()


def test_single_instance_protection(tmp_path: Path) -> None:
    lock = tmp_path / "tray.lock"
    first = TraySingleInstance(lock)
    first.acquire()
    try:
        with pytest.raises(TrayAlreadyRunningError):
            TraySingleInstance(lock).acquire()
    finally:
        first.release()

    assert not lock.exists()


def test_start_calls_existing_start_lifecycle_once() -> None:
    daemon = _Daemon()
    controller = GrandpaTrayController(daemon_module=daemon, startup_module=types.SimpleNamespace())

    result = controller.start()

    assert result.ok is True
    daemon.start.callback.assert_called_once_with(None, None, None, None, None)


def test_stop_calls_existing_stop_lifecycle_once() -> None:
    daemon = _Daemon(pid=123)
    controller = GrandpaTrayController(daemon_module=daemon, startup_module=types.SimpleNamespace())

    result = controller.stop()

    assert result.ok is True
    daemon.stop.callback.assert_called_once_with()


def test_restart_performs_stop_then_start_when_running() -> None:
    daemon = _Daemon(pid=123)
    controller = GrandpaTrayController(daemon_module=daemon, startup_module=types.SimpleNamespace())

    result = controller.restart()

    assert result.ok is True
    daemon.stop.callback.assert_called_once_with()
    daemon.start.callback.assert_called_once_with(None, None, None, None, None)


def test_open_uses_configured_backend_url(monkeypatch) -> None:
    opened: list[str] = []
    config = types.SimpleNamespace(server=types.SimpleNamespace(host="0.0.0.0", port=8123))
    monkeypatch.setattr("grandpa.tray.load_config", lambda: config)
    controller = GrandpaTrayController(
        opener=lambda url: opened.append(url) or True,
        daemon_module=_Daemon(),
        startup_module=types.SimpleNamespace(),
    )

    result = controller.open_grandpa()

    assert result.ok is True
    assert opened == ["http://127.0.0.1:8123/"]


def test_reminders_opens_routines_view(monkeypatch) -> None:
    opened: list[str] = []
    config = types.SimpleNamespace(server=types.SimpleNamespace(host="127.0.0.1", port=8000))
    monkeypatch.setattr("grandpa.tray.load_config", lambda: config)
    controller = GrandpaTrayController(
        opener=lambda url: opened.append(url) or True,
        daemon_module=_Daemon(),
        startup_module=types.SimpleNamespace(),
    )

    result = controller.open_reminders()

    assert result.ok is True
    assert opened == ["http://127.0.0.1:8000/routines"]


def test_exit_tray_does_not_stop_grandpa() -> None:
    daemon = _Daemon(pid=123)
    icon = MagicMock()
    controller = GrandpaTrayController(daemon_module=daemon, startup_module=types.SimpleNamespace())

    result = controller.exit_tray(icon)

    assert result.ok is True
    icon.stop.assert_called_once_with()
    daemon.stop.callback.assert_not_called()


def test_startup_enable_disable_delegates_to_startup_manager() -> None:
    startup = types.SimpleNamespace(
        enable_startup=MagicMock(return_value=types.SimpleNamespace(ok=True, status="enabled", message="enabled")),
        disable_startup=MagicMock(return_value=types.SimpleNamespace(ok=True, status="disabled", message="disabled")),
    )
    controller = GrandpaTrayController(daemon_module=_Daemon(), startup_module=startup)

    assert controller.enable_startup().status == "enabled"
    assert controller.disable_startup().status == "disabled"
    startup.enable_startup.assert_called_once_with()
    startup.disable_startup.assert_called_once_with()


def test_unrelated_errors_are_not_mislabeled_as_missing_dependency(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("grandpa.tray.validate_tray_environment", lambda: None)
    monkeypatch.setattr("grandpa.tray.TraySingleInstance", MagicMock(side_effect=RuntimeError("boom")))
    monkeypatch.setitem(
        __import__("sys").modules,
        "pystray",
        types.SimpleNamespace(Icon=MagicMock()),
    )

    with pytest.raises(RuntimeError, match="boom"):
        run_tray_app(lock_path=tmp_path / "tray.lock")


def test_menu_construction_includes_required_actions() -> None:
    assert menu_action_labels() == [
        "Open Grandpa",
        "Start",
        "Stop",
        "Restart",
        "Status",
        "Reminders",
        "Startup: Enable",
        "Startup: Disable",
        "Exit Tray",
    ]


def test_build_menu_uses_all_required_actions() -> None:
    labels: list[str] = []

    class FakeMenu:
        SEPARATOR = object()

        def __init__(self, *items):
            self.items = items

    def fake_item(label, action):  # noqa: ANN001
        labels.append(label)
        return (label, action)

    fake_pystray = types.SimpleNamespace(Menu=FakeMenu, MenuItem=fake_item)
    build_menu(fake_pystray, GrandpaTrayController(daemon_module=_Daemon(), startup_module=types.SimpleNamespace()))

    assert labels == menu_action_labels()


def test_cli_missing_dependency_guidance(monkeypatch) -> None:
    monkeypatch.setattr("grandpa.cli.tray_cmd.run_tray_app", MagicMock(side_effect=TrayDependencyError(TRAY_INSTALL_HINT)))

    result = CliRunner().invoke(tray)

    assert result.exit_code == 1
    assert "uv sync --extra tray" in result.output


def test_cli_unsupported_platform_message(monkeypatch) -> None:
    monkeypatch.setattr("grandpa.cli.tray_cmd.run_tray_app", MagicMock(side_effect=TrayUnsupportedError("unsupported")))

    result = CliRunner().invoke(tray)

    assert result.exit_code == 1
    assert "unsupported" in result.output
