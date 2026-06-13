"""Minimal Windows system tray controller for Grandpa."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from grandpa.core.config import DEFAULT_CONFIG_DIR, load_config

logger = logging.getLogger(__name__)

TRAY_LOCK_FILE = DEFAULT_CONFIG_DIR / "tray.lock"
TRAY_INSTALL_HINT = "Install it with: uv sync --extra tray"


class TrayDependencyError(RuntimeError):
    """Raised when optional tray dependencies are missing."""


class TrayAlreadyRunningError(RuntimeError):
    """Raised when another Grandpa tray controller is already running."""


class TrayUnsupportedError(RuntimeError):
    """Raised when tray mode is requested on an unsupported platform."""


@dataclass(frozen=True)
class TrayActionResult:
    ok: bool
    status: str
    message: str


@dataclass(frozen=True)
class TrayMenuAction:
    label: str
    action: str


REQUIRED_MENU_ACTIONS = (
    TrayMenuAction("Open Grandpa", "open"),
    TrayMenuAction("Start", "start"),
    TrayMenuAction("Stop", "stop"),
    TrayMenuAction("Restart", "restart"),
    TrayMenuAction("Status", "status"),
    TrayMenuAction("Reminders", "reminders"),
    TrayMenuAction("Startup: Enable", "startup_enable"),
    TrayMenuAction("Startup: Disable", "startup_disable"),
    TrayMenuAction("Exit Tray", "exit"),
)


class TraySingleInstance:
    """Small lock-file guard for a single tray process per user profile."""

    def __init__(self, lock_path: Path = TRAY_LOCK_FILE) -> None:
        self.lock_path = Path(lock_path)
        self._fd: int | None = None

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._fd, str(os.getpid()).encode("ascii", errors="ignore"))
        except FileExistsError as exc:
            raise TrayAlreadyRunningError("Grandpa tray is already running.") from exc
        except OSError as exc:
            raise RuntimeError(f"Could not create tray lock: {exc}") from exc

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            logger.debug("Failed to remove tray lock file", exc_info=True)

    def __enter__(self) -> "TraySingleInstance":
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


class GrandpaTrayController:
    """Backend service actions exposed by the tray menu."""

    def __init__(
        self,
        *,
        opener: Callable[[str], bool] | None = None,
        daemon_module: Any | None = None,
        startup_module: Any | None = None,
    ) -> None:
        self.opener = opener or webbrowser.open
        from grandpa import windows_startup
        from grandpa.cli import daemon_cmd

        self.daemon = daemon_module or daemon_cmd
        self.startup = startup_module or windows_startup
        self.last_message = ""

    def local_url(self, path: str = "") -> str:
        config = load_config()
        host = config.server.host
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        base = f"http://{host}:{config.server.port}"
        return f"{base}{path}"

    def open_grandpa(self) -> TrayActionResult:
        url = self.local_url("/")
        self.opener(url)
        return self._remember(True, "opened", f"Opened Grandpa at {url}")

    def open_reminders(self) -> TrayActionResult:
        url = self.local_url("/routines")
        self.opener(url)
        return self._remember(True, "opened", f"Opened reminders view at {url}")

    def start(self) -> TrayActionResult:
        try:
            self.daemon.start.callback(None, None, None, None, None)
        except SystemExit as exc:
            if exc.code:
                return self._remember(False, "failed", "Grandpa could not start or is already running.")
        except Exception as exc:
            logger.exception("Tray start action failed")
            return self._remember(False, "failed", f"Grandpa start failed: {exc}")
        return self._remember(True, "started", "Grandpa started.")

    def stop(self) -> TrayActionResult:
        try:
            self.daemon.stop.callback()
        except SystemExit as exc:
            if exc.code:
                return self._remember(False, "failed", "Grandpa was not running.")
        except Exception as exc:
            logger.exception("Tray stop action failed")
            return self._remember(False, "failed", f"Grandpa stop failed: {exc}")
        return self._remember(True, "stopped", "Grandpa stopped.")

    def restart(self) -> TrayActionResult:
        if self.daemon._read_pid() is not None:
            stopped = self.stop()
            if not stopped.ok:
                return stopped
        return self.start()

    def status(self) -> TrayActionResult:
        try:
            pid = self.daemon._read_pid()
        except Exception as exc:
            logger.exception("Tray status action failed")
            return self._remember(False, "failed", f"Grandpa status failed: {exc}")
        if pid is None:
            return self._remember(True, "stopped", "Grandpa is stopped.")
        return self._remember(True, "running", f"Grandpa is running (PID {pid}).")

    def enable_startup(self) -> TrayActionResult:
        result = self.startup.enable_startup()
        return self._remember(result.ok, result.status, result.message)

    def disable_startup(self) -> TrayActionResult:
        result = self.startup.disable_startup()
        return self._remember(result.ok, result.status, result.message)

    def exit_tray(self, icon: Any | None = None) -> TrayActionResult:
        if icon is not None:
            icon.stop()
        return self._remember(True, "exited", "Grandpa tray exited. Background service was left unchanged.")

    def _remember(self, ok: bool, status: str, message: str) -> TrayActionResult:
        self.last_message = message
        return TrayActionResult(ok, status, message)


def validate_tray_environment(platform: str | None = None) -> None:
    if (platform or sys.platform) != "win32":
        raise TrayUnsupportedError("Grandpa tray is only supported on Windows.")
    missing = [name for name in ("pystray", "PIL") if importlib.util.find_spec(name) is None]
    if missing:
        raise TrayDependencyError(
            "Grandpa tray dependencies are not installed.\n"
            f"{TRAY_INSTALL_HINT}\n"
            f"Missing: {', '.join(missing)}"
        )


def build_menu(pystray_module: Any, controller: GrandpaTrayController) -> Any:
    item = pystray_module.MenuItem
    return pystray_module.Menu(
        item("Open Grandpa", lambda icon, _item: controller.open_grandpa()),
        item("Start", lambda icon, _item: controller.start()),
        item("Stop", lambda icon, _item: controller.stop()),
        item("Restart", lambda icon, _item: controller.restart()),
        item("Status", lambda icon, _item: controller.status()),
        item("Reminders", lambda icon, _item: controller.open_reminders()),
        pystray_module.Menu.SEPARATOR,
        item("Startup: Enable", lambda icon, _item: controller.enable_startup()),
        item("Startup: Disable", lambda icon, _item: controller.disable_startup()),
        pystray_module.Menu.SEPARATOR,
        item("Exit Tray", lambda icon, _item: controller.exit_tray(icon)),
    )


def create_placeholder_icon() -> Any:
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (17, 24, 39, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill=(52, 211, 153, 255))
    draw.ellipse((20, 20, 44, 44), fill=(17, 24, 39, 255))
    draw.rectangle((30, 8, 34, 56), fill=(245, 158, 11, 255))
    return image


def run_tray_app(
    *,
    controller: GrandpaTrayController | None = None,
    lock_path: Path = TRAY_LOCK_FILE,
) -> TrayActionResult:
    validate_tray_environment()
    import pystray

    tray_controller = controller or GrandpaTrayController()
    with TraySingleInstance(lock_path):
        icon = pystray.Icon(
            "Grandpa",
            icon=create_placeholder_icon(),
            title="Grandpa",
            menu=build_menu(pystray, tray_controller),
        )
        icon.run()
    return TrayActionResult(True, "exited", "Grandpa tray exited.")


def menu_action_labels() -> list[str]:
    return [action.label for action in REQUIRED_MENU_ACTIONS]


__all__ = [
    "GrandpaTrayController",
    "REQUIRED_MENU_ACTIONS",
    "TRAY_INSTALL_HINT",
    "TrayActionResult",
    "TrayAlreadyRunningError",
    "TrayDependencyError",
    "TrayMenuAction",
    "TraySingleInstance",
    "TrayUnsupportedError",
    "build_menu",
    "create_placeholder_icon",
    "menu_action_labels",
    "run_tray_app",
    "validate_tray_environment",
]
