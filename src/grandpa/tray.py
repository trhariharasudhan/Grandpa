"""Minimal Windows system tray controller for Grandpa."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import uuid
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

    def __init__(
        self,
        lock_path: Path = TRAY_LOCK_FILE,
        *,
        pid_alive: Callable[[int], bool] | None = None,
    ) -> None:
        self.lock_path = Path(lock_path)
        self._fd: int | None = None
        self._pid = os.getpid()
        self._token = uuid.uuid4().hex
        self._pid_alive = pid_alive or _pid_is_alive

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(3):
            try:
                self._fd = os.open(
                    str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
                os.write(
                    self._fd,
                    f"{self._pid}\n{self._token}\n".encode("ascii", errors="ignore"),
                )
                return
            except FileExistsError as exc:
                if self._existing_lock_is_live():
                    raise TrayAlreadyRunningError(
                        "Grandpa tray is already running."
                    ) from exc
                self._remove_stale_lock()
            except OSError as exc:
                raise RuntimeError(f"Could not create tray lock: {exc}") from exc
        raise TrayAlreadyRunningError("Grandpa tray is already running.")

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if not self._owns_current_lock():
            return
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            logger.debug("Failed to remove tray lock file", exc_info=True)

    def __enter__(self) -> "TraySingleInstance":
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def _existing_lock_is_live(self) -> bool:
        pid = self._read_lock_pid()
        return pid is not None and self._pid_alive(pid)

    def _read_lock_pid(self) -> int | None:
        try:
            raw_pid = (
                self.lock_path.read_text(encoding="ascii", errors="ignore")
                .splitlines()[0]
                .strip()
            )
            pid = int(raw_pid)
        except (IndexError, OSError, ValueError):
            return None
        return pid if pid > 0 else None

    def _owns_current_lock(self) -> bool:
        try:
            lines = self.lock_path.read_text(
                encoding="ascii", errors="ignore"
            ).splitlines()
        except OSError:
            return False
        if len(lines) < 2:
            return False
        try:
            pid = int(lines[0].strip())
        except ValueError:
            return False
        return pid == self._pid and lines[1].strip() == self._token

    def _remove_stale_lock(self) -> None:
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Could not remove stale tray lock: {exc}") from exc


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil  # type: ignore[import-not-found]

        if not psutil.pid_exists(pid):
            return False
        if sys.platform == "win32" and not _pid_belongs_to_current_windows_user(
            psutil, pid
        ):
            return True
        return True
    except ImportError:
        pass

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_belongs_to_current_windows_user(psutil_module: Any, pid: int) -> bool:
    psutil_error = getattr(psutil_module, "Error", RuntimeError)
    try:
        import getpass

        username = str(psutil_module.Process(pid).username()).lower()
        current = getpass.getuser().lower()
    except (AttributeError, OSError, RuntimeError, psutil_error):
        return True
    return username == current or username.endswith(f"\\{current}")


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
                return self._remember(
                    False, "failed", "Grandpa could not start or is already running."
                )
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
        return self._remember(
            True,
            "exited",
            "Grandpa tray exited. Background service was left unchanged.",
        )

    def _remember(self, ok: bool, status: str, message: str) -> TrayActionResult:
        self.last_message = message
        return TrayActionResult(ok, status, message)


def validate_tray_environment(platform: str | None = None) -> None:
    if (platform or sys.platform) != "win32":
        raise TrayUnsupportedError("Grandpa tray is only supported on Windows.")
    missing = [
        name for name in ("pystray", "PIL") if importlib.util.find_spec(name) is None
    ]
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
    pystray_module: Any | None = None,
) -> TrayActionResult:
    validate_tray_environment()
    if pystray_module is None:
        import pystray as pystray_module

    tray_controller = controller or GrandpaTrayController()
    with TraySingleInstance(lock_path):
        icon = pystray_module.Icon(
            "Grandpa",
            icon=create_placeholder_icon(),
            title="Grandpa",
            menu=build_menu(pystray_module, tray_controller),
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
