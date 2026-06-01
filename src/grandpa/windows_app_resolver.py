"""Allowlisted Windows app discovery and launch helpers."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
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
        ("notepad",),
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
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

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
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT app_id, display_name, status, launch_kind, launch_target, source, discovered_at
                FROM app_cache
                WHERE app_id = ?
                """,
                (app_id,),
            ).fetchone()
        if not row or time.time() - row["discovered_at"] > max_age_seconds:
            return None
        definition = APP_DEFINITIONS.get(app_id)
        display_name = row["display_name"] or (definition.display_name if definition else app_id)
        return AppResolution(
            app_id=row["app_id"],
            display_name=display_name,
            status=row["status"],
            launch_kind=row["launch_kind"],
            launch_target=row["launch_target"],
            source=row["source"],
            message=_resolution_message(display_name, row["status"], row["launch_target"], row["source"]),
        )

    def set(self, resolution: AppResolution) -> None:
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


def resolve_app(name: str, *, refresh: bool = False, cache: AppResolverCache | None = None) -> AppResolution:
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
    return [resolve_app(defn.app_id, refresh=refresh, cache=cache).to_dict() for defn in APP_DEFINITIONS.values()]


def describe_app(name: str) -> str:
    resolution = resolve_app(name)
    return resolution.message


def launch_app(name: str) -> AppResolution:
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
    try:
        if resolution.launch_kind in {"path", "command"}:
            subprocess.Popen([resolution.launch_target], shell=False)  # noqa: S603
        elif resolution.launch_kind in {"shortcut", "uri"}:
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
    return resolution


def definition_for(name: str) -> AppDefinition | None:
    key = _normalise_key(name)
    for definition in APP_DEFINITIONS.values():
        if key == definition.app_id or key in definition.aliases:
            return definition
    return None


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
        found = shutil.which(exe)
        if found:
            return _found(definition, "path", found, "path")

    if definition.uri:
        return _found(definition, "uri", definition.uri, "uri")

    if definition.system_command:
        return _found(definition, "command", definition.system_command, "system_command")

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
    return [Path(os.path.expandvars(raw)) for raw in definition.common_paths]


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
                                display_name = _query_registry_string(winreg, sub_key, "DisplayName")
                                install_location = _query_registry_string(winreg, sub_key, "InstallLocation")
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


def _found(definition: AppDefinition, kind: LaunchKind, target: str, source: str) -> AppResolution:
    return AppResolution(
        definition.app_id,
        definition.display_name,
        "found",
        kind,
        target,
        source,
        _resolution_message(definition.display_name, "found", target, source),
    )


def _resolution_message(display_name: str, status: str, target: str, source: str) -> str:
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
