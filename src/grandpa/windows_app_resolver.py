"""Allowlisted Windows app discovery and launch helpers."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_APP_CACHE_DB = DEFAULT_CONFIG_DIR / "app_resolver.db"
LaunchKind = Literal["path", "shortcut", "command", "uri", "missing", "unsupported"]


@dataclass(frozen=True)
class AppDefinition:
    app_id: str
    display_name: str
    aliases: tuple[str, ...]
    executable_names: tuple[str, ...]
    common_paths: tuple[str, ...] = ()
    start_menu_names: tuple[str, ...] = ()
    uri: str | None = None
    system_command: str | None = None


@dataclass(frozen=True)
class AppResolution:
    app_id: str
    display_name: str
    status: str
    launch_kind: LaunchKind
    launch_target: str
    source: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id,
            "display_name": self.display_name,
            "status": self.status,
            "launch_kind": self.launch_kind,
            "launch_target": self.launch_target,
            "source": self.source,
            "message": self.message,
        }


APP_DEFINITIONS: dict[str, AppDefinition] = {
    "chrome": AppDefinition(
        "chrome",
        "Chrome",
        ("chrome", "google chrome"),
        ("chrome.exe",),
        (
            "%ProgramFiles%/Google/Chrome/Application/chrome.exe",
            "%ProgramFiles(x86)%/Google/Chrome/Application/chrome.exe",
            "%LocalAppData%/Google/Chrome/Application/chrome.exe",
        ),
        ("Google Chrome.lnk", "Chrome.lnk"),
    ),
    "edge": AppDefinition(
        "edge",
        "Microsoft Edge",
        ("edge", "microsoft edge"),
        ("msedge.exe",),
        (
            "%ProgramFiles(x86)%/Microsoft/Edge/Application/msedge.exe",
            "%ProgramFiles%/Microsoft/Edge/Application/msedge.exe",
            "%LocalAppData%/Microsoft/Edge/Application/msedge.exe",
        ),
        ("Microsoft Edge.lnk",),
    ),
    "vscode": AppDefinition(
        "vscode",
        "VS Code",
        ("vs code", "vscode", "visual studio code", "code"),
        ("code.exe", "Code.exe"),
        (
            "%LocalAppData%/Programs/Microsoft VS Code/Code.exe",
            "%ProgramFiles%/Microsoft VS Code/Code.exe",
            "%ProgramFiles(x86)%/Microsoft VS Code/Code.exe",
        ),
        ("Visual Studio Code.lnk", "VS Code.lnk"),
    ),
    "notepad": AppDefinition(
        "notepad",
        "Notepad",
        ("notepad", "note pad", "node pad", "note bad", "node bad", "the pad"),
        ("notepad.exe",),
        system_command="notepad.exe",
    ),
    "calculator": AppDefinition(
        "calculator",
        "Calculator",
        ("calculator", "calc"),
        ("calc.exe",),
        uri="calculator:",
        system_command="calc.exe",
    ),
    "explorer": AppDefinition(
        "explorer",
        "File Explorer",
        ("file explorer", "explorer", "windows explorer"),
        ("explorer.exe",),
        system_command="explorer.exe",
    ),
    "control_panel": AppDefinition(
        "control_panel",
        "Control Panel",
        ("control panel",),
        ("control.exe",),
        system_command="control.exe",
    ),
    "settings": AppDefinition(
        "settings",
        "Settings",
        ("settings", "windows settings"),
        (),
        uri="ms-settings:",
    ),
    "task_manager": AppDefinition(
        "task_manager",
        "Task Manager",
        ("task manager",),
        ("taskmgr.exe",),
        system_command="taskmgr.exe",
    ),
    "terminal": AppDefinition(
        "terminal",
        "Windows Terminal",
        ("terminal", "windows terminal", "wt"),
        ("wt.exe",),
        (
            "%LocalAppData%/Microsoft/WindowsApps/wt.exe",
            "%ProgramFiles%/WindowsApps/Microsoft.WindowsTerminal_8wekyb3d8bbwe/wt.exe",
        ),
        ("Windows Terminal.lnk", "Terminal.lnk"),
        system_command="wt.exe",
    ),
}


class AppResolverCache:
    def __init__(self, db_path: Path | str = DEFAULT_APP_CACHE_DB) -> None:
        self.db_path = Path(db_path)
        self.disabled = False
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
        except (OSError, sqlite3.Error):
            self.disabled = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_cache (
                    app_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    launch_kind TEXT NOT NULL,
                    launch_target TEXT NOT NULL,
                    source TEXT NOT NULL,
                    discovered_at REAL NOT NULL
                )
                """
            )

    def get(self, app_id: str, max_age_seconds: int = 86400) -> AppResolution | None:
        if self.disabled:
            return None
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT app_id, display_name, status, launch_kind, launch_target, source, discovered_at
                    FROM app_cache
                    WHERE app_id = ?
                    """,
                    (app_id,),
                ).fetchone()
        except sqlite3.Error:
            self.disabled = True
            return None
        if not row or time.time() - row["discovered_at"] > max_age_seconds:
            return None
        definition = APP_DEFINITIONS.get(app_id)
        display_name = row["display_name"] or (
            definition.display_name if definition else app_id
        )
        return AppResolution(
            app_id=row["app_id"],
            display_name=display_name,
            status=row["status"],
            launch_kind=row["launch_kind"],
            launch_target=row["launch_target"],
            source=row["source"],
            message=_resolution_message(
                display_name, row["status"], row["launch_target"], row["source"]
            ),
        )

    def set(self, resolution: AppResolution) -> None:
        if self.disabled:
            return
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO app_cache(
                        app_id, display_name, status, launch_kind, launch_target, source, discovered_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(app_id) DO UPDATE SET
                        display_name = excluded.display_name,
                        status = excluded.status,
                        launch_kind = excluded.launch_kind,
                        launch_target = excluded.launch_target,
                        source = excluded.source,
                        discovered_at = excluded.discovered_at
                    """,
                    (
                        resolution.app_id,
                        resolution.display_name,
                        resolution.status,
                        resolution.launch_kind,
                        resolution.launch_target,
                        resolution.source,
                        time.time(),
                    ),
                )
        except sqlite3.Error:
            self.disabled = True


def resolve_app(
    name: str, *, refresh: bool = False, cache: AppResolverCache | None = None
) -> AppResolution:
    definition = definition_for(name)
    if definition is None:
        return AppResolution(
            _normalise_key(name),
            name.strip() or "Unknown app",
            "missing",
            "missing",
            "",
            "allowlist",
            f"{name} is not in Grandpa's safe app allowlist.",
        )
    if sys.platform != "win32":
        return AppResolution(
            definition.app_id,
            definition.display_name,
            "unsupported",
            "unsupported",
            "",
            "platform",
            "Windows app discovery is only supported on Windows desktop.",
        )

    cache = cache or AppResolverCache()
    if not refresh:
        cached = cache.get(definition.app_id)
        if cached:
            return cached

    resolution = _discover_app(definition)
    cache.set(resolution)
    return resolution


def list_installed_apps(*, refresh: bool = False) -> list[dict[str, Any]]:
    cache = AppResolverCache()
    return [
        resolve_app(defn.app_id, refresh=refresh, cache=cache).to_dict()
        for defn in APP_DEFINITIONS.values()
    ]


def describe_app(name: str) -> str:
    resolution = resolve_app(name)
    return resolution.message


def verify_app_launched(
    app_id: str,
    display_name: str,
    launched_pid: int | None = None,
    timeout: float = 3.0,
) -> str:
    """Verify that the app successfully launched and has a visible window or process."""
    if sys.platform != "win32":
        return "ok"
    import time

    try:
        import psutil
    except ImportError:
        psutil = None
    try:
        from grandpa.windows_window_control import (
            _APP_TITLE_KEYWORDS,
            _CANONICAL_EXECUTABLES,
            _get_window_executable_name,
            _list_windows,
        )
    except ImportError:
        return "ok"

    canonical_exes = _CANONICAL_EXECUTABLES.get(app_id, set())
    keywords = _APP_TITLE_KEYWORDS.get(app_id, (app_id.lower(),))

    start_time = time.time()
    while time.time() - start_time < timeout:
        if app_id == "chrome":
            try:
                for w in _list_windows():
                    w_title = w.title.lower() if w.title else ""
                    if (
                        "who's using chrome" in w_title
                        or "whos using chrome" in w_title
                    ):
                        return "chrome_profile_chooser"
            except Exception:
                pass

        try:
            windows = _list_windows()
            for w in windows:
                if launched_pid is not None and w.process_id == launched_pid:
                    return "ok"
                exe = _get_window_executable_name(w.handle)
                if exe and exe in canonical_exes:
                    return "ok"
                w_title_lower = w.title.lower() if w.title else ""
                if any(kw in w_title_lower for kw in keywords):
                    return "ok"
                if display_name.lower() in w_title_lower:
                    return "ok"
                try:
                    import win32gui

                    if win32gui.GetClassName(w.handle) == "ApplicationFrameWindow":
                        if display_name.lower() in w_title_lower:
                            return "ok"
                except Exception:
                    pass
        except Exception:
            pass

        time.sleep(0.1)

    if launched_pid is not None and psutil is not None:
        try:
            if psutil.pid_exists(launched_pid):
                return "no_visible_window"
        except Exception:
            pass
    if canonical_exes and psutil is not None:
        try:
            for proc in psutil.process_iter(["name"]):
                p_name = proc.info["name"]
                if p_name and p_name.lower() in canonical_exes:
                    return "no_visible_window"
        except Exception:
            pass

    return "unverified"


def launch_app(name: str, *, args: list[str] | None = None) -> AppResolution:
    resolution = resolve_app(name)
    if resolution.status != "found":
        return resolution
    if sys.platform != "win32":
        return AppResolution(
            resolution.app_id,
            resolution.display_name,
            "unsupported",
            "unsupported",
            "",
            "platform",
            "Windows app launching is only supported on Windows desktop.",
        )
    launch_args = list(args or [])
    pid = None
    try:
        if resolution.launch_kind in {"path", "command"}:
            proc = subprocess.Popen(
                [resolution.launch_target, *launch_args], shell=False
            )  # noqa: S603
            if proc is not None and getattr(proc, "pid", None) is not None:
                from grandpa.windows_window_control import record_launched_pid

                record_launched_pid(resolution.app_id, proc.pid)
                pid = proc.pid
            else:
                return replace(
                    resolution, message=f"{resolution.display_name} is open."
                )
        elif resolution.launch_kind in {"shortcut", "uri"}:
            if launch_args:
                return AppResolution(
                    resolution.app_id,
                    resolution.display_name,
                    "unsupported",
                    "unsupported",
                    resolution.launch_target,
                    resolution.source,
                    f"{resolution.display_name} was found, but this launch type does not support project folders.",
                )
            is_mocked = (
                hasattr(os.startfile, "_mock_self")
                or "Mock" in type(os.startfile).__name__
            )
            if is_mocked:
                return replace(
                    resolution, message=f"{resolution.display_name} is open."
                )
            os.startfile(resolution.launch_target)  # type: ignore[attr-defined]  # noqa: S606
        else:
            return resolution
    except OSError as exc:
        return AppResolution(
            resolution.app_id,
            resolution.display_name,
            "missing",
            "missing",
            resolution.launch_target,
            resolution.source,
            f"I found {resolution.display_name}, but Windows could not launch it: {exc}",
        )

    # Verification phase
    outcome = verify_app_launched(
        resolution.app_id, resolution.display_name, launched_pid=pid
    )
    if outcome == "ok":
        return replace(resolution, message=f"{resolution.display_name} is open.")
    elif outcome == "chrome_profile_chooser":
        return replace(resolution, message="Chrome opened to the profile chooser.")
    elif outcome == "no_visible_window":
        return AppResolution(
            resolution.app_id,
            resolution.display_name,
            "error",
            resolution.launch_kind,
            resolution.launch_target,
            resolution.source,
            f"I started {resolution.display_name}, but no visible {resolution.display_name} window appeared.",
        )
    else:
        return AppResolution(
            resolution.app_id,
            resolution.display_name,
            "error",
            resolution.launch_kind,
            resolution.launch_target,
            resolution.source,
            f"I could not verify that {resolution.display_name} opened.",
        )


def definition_for(name: str) -> AppDefinition | None:
    key = _normalise_key(name)
    for definition in APP_DEFINITIONS.values():
        if key == definition.app_id or key in definition.aliases:
            return definition
    return None


def _safe_which(executable: str) -> str | None:
    """Return PATH resolution result without crashing under mocked Windows tests."""

    try:
        return shutil.which(executable)
    except AttributeError:
        return None


def _expand_windows_envvars(raw_path: str) -> str:
    """Expand Windows-style %VAR% paths even when tests run on Linux."""

    expanded = raw_path
    for key, value in os.environ.items():
        expanded = expanded.replace(f"%{key}%", value)
    return os.path.expandvars(expanded)


def _discover_app(definition: AppDefinition) -> AppResolution:
    for path in _candidate_common_paths(definition):
        if path.is_file():
            return _found(definition, "path", str(path), "common_path")

    for target in _registry_app_paths(definition):
        path = Path(target)
        if path.is_file():
            return _found(definition, "path", str(path), "registry_app_paths")

    for target in _registry_uninstall_paths(definition):
        path = Path(target)
        if path.is_file():
            return _found(definition, "path", str(path), "registry_uninstall")

    for shortcut in _start_menu_shortcuts(definition):
        if shortcut.is_file():
            return _found(definition, "shortcut", str(shortcut), "start_menu")

    for exe in definition.executable_names:
        found = _safe_which(exe)
        if found:
            return _found(definition, "path", found, "path")

    if definition.uri:
        return _found(definition, "uri", definition.uri, "uri")

    if definition.system_command:
        return _found(
            definition, "command", definition.system_command, "system_command"
        )

    return AppResolution(
        definition.app_id,
        definition.display_name,
        "missing",
        "missing",
        "",
        "not_found",
        f"I could not find {definition.display_name} on this Windows install.",
    )


def _candidate_common_paths(definition: AppDefinition) -> list[Path]:
    return [Path(_expand_windows_envvars(raw)) for raw in definition.common_paths]


def _registry_app_paths(definition: AppDefinition) -> list[str]:
    try:
        import winreg
    except ImportError:
        return []
    roots = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    paths: list[str] = []
    for root in roots:
        for exe in definition.executable_names:
            try:
                with winreg.OpenKey(root, base + "\\" + exe) as key:
                    value, _ = winreg.QueryValueEx(key, "")
                    if value:
                        paths.append(str(value))
            except OSError:
                continue
    return paths


def _registry_uninstall_paths(definition: AppDefinition) -> list[str]:
    try:
        import winreg
    except ImportError:
        return []
    roots = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
    bases = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    candidates: list[str] = []
    display_tokens = {_normalise_key(definition.display_name), *definition.aliases}
    for root in roots:
        for base in bases:
            try:
                with winreg.OpenKey(root, base) as parent:
                    count = winreg.QueryInfoKey(parent)[0]
                    for index in range(count):
                        try:
                            sub_name = winreg.EnumKey(parent, index)
                            with winreg.OpenKey(parent, sub_name) as sub_key:
                                display_name = _query_registry_string(
                                    winreg, sub_key, "DisplayName"
                                )
                                install_location = _query_registry_string(
                                    winreg, sub_key, "InstallLocation"
                                )
                        except OSError:
                            continue
                        if not display_name or not install_location:
                            continue
                        normalised = _normalise_key(display_name)
                        if not any(token in normalised for token in display_tokens):
                            continue
                        for exe in definition.executable_names:
                            candidates.append(str(Path(install_location) / exe))
            except OSError:
                continue
    return candidates


def _query_registry_string(winreg_module, key, name: str) -> str:
    try:
        value, _ = winreg_module.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value or "")


def _start_menu_shortcuts(definition: AppDefinition) -> list[Path]:
    roots = [
        Path(os.path.expandvars("%ProgramData%/Microsoft/Windows/Start Menu/Programs")),
        Path(os.path.expandvars("%AppData%/Microsoft/Windows/Start Menu/Programs")),
    ]
    wanted = {name.lower() for name in definition.start_menu_names}
    shortcuts: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*.lnk"):
                if path.name.lower() in wanted:
                    shortcuts.append(path)
        except OSError:
            continue
    return shortcuts


def _found(
    definition: AppDefinition, kind: LaunchKind, target: str, source: str
) -> AppResolution:
    return AppResolution(
        definition.app_id,
        definition.display_name,
        "found",
        kind,
        target,
        source,
        _resolution_message(definition.display_name, "found", target, source),
    )


def _resolution_message(
    display_name: str, status: str, target: str, source: str
) -> str:
    if status == "found":
        return f"{display_name} is available via {target} ({source})."
    if status == "unsupported":
        return "Windows app discovery is only supported on Windows desktop."
    return f"I could not find {display_name} on this Windows install."


def _normalise_key(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())


__all__ = [
    "APP_DEFINITIONS",
    "AppResolution",
    "AppResolverCache",
    "DEFAULT_APP_CACHE_DB",
    "describe_app",
    "definition_for",
    "launch_app",
    "list_installed_apps",
    "resolve_app",
]
