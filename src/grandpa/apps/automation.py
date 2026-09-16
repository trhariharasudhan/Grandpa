"""High-level Application Manager facade."""

from __future__ import annotations

from pathlib import Path

from grandpa.apps.launcher import launch_application
from grandpa.apps.models import ApplicationInfo, AppResolveResult
from grandpa.apps.process_manager import list_running_apps
from grandpa.apps.registry import (
    DEFAULT_APP_REGISTRY_PATH,
    app_registry_needs_refresh,
    load_app_registry,
)
from grandpa.apps.resolver import resolve_app
from grandpa.apps.scanner import scan_app_inventory


class ApplicationManager:
    """Discover, cache, resolve, and launch installed applications."""

    def __init__(self, *, store_path: Path = DEFAULT_APP_REGISTRY_PATH) -> None:
        self.store_path = store_path

    def scan(self) -> list[ApplicationInfo]:
        return scan_app_inventory(store_path=self.store_path)

    def list(
        self, *, include_all: bool = False, source: str | None = None
    ) -> list[ApplicationInfo]:
        apps = load_app_registry(store_path=self.store_path)
        if not include_all:
            apps = [
                app
                for app in apps
                if app.is_user_facing and app.is_launchable and app.confidence >= 0.7
            ]
        if source:
            apps = [
                app
                for app in apps
                if app.source == source or app.source.startswith(f"{source}:")
            ]
        return apps

    def cache_needs_refresh(self) -> bool:
        return app_registry_needs_refresh(store_path=self.store_path)

    def search(self, query: str) -> AppResolveResult:
        return resolve_app(query, self.list())

    def launch(self, query: str) -> AppResolveResult:
        result = self.search(query)
        if result.status == "found":
            message = launch_application(result.matches[0])
            return AppResolveResult("found", result.matches, message, result.score)
        return result

    def running(self) -> list[str]:
        return [proc.display_name or proc.name for proc in list_running_apps()]


__all__ = ["ApplicationManager"]


def execute_inventory(action: str, target: str = "") -> str:
    """Answer one application-inventory question, in words.

    Moved here from ``desktop/automation.py`` when chat's desktop branch was
    migrated. The sentences are the ones that handler produced, unchanged --
    what moved is where they live, so the action layer and the desktop handler
    say the same thing rather than each having a copy.
    """
    from grandpa.apps.process_manager import find_running_app, list_running_apps

    manager = ApplicationManager()
    label = str(target or "").strip()

    if action == "apps_scan":
        return f"Found {len(manager.scan())} applications. Database saved."
    if action == "apps_list":
        apps = manager.list()
        if not apps:
            return "No app inventory found. Run `grandpa apps scan` first."
        names = ", ".join(app.display_name for app in apps[:10])
        suffix = f" and {len(apps) - 10} more" if len(apps) > 10 else ""
        return (
            f"Installed applications ({len(apps)} total): {names}{suffix}. "
            "Use `grandpa apps list` to browse them."
        )
    if action == "apps_search":
        return manager.search(label).message
    if action == "apps_running":
        apps = list_running_apps()
        if not apps:
            return (
                "No running applications detected, or process inspection is "
                "unavailable."
            )
        names = ", ".join(app.display_name or app.name for app in apps[:10])
        return f"Running applications: {names}."
    if action == "apps_is_running":
        process = find_running_app(label)
        if process is None:
            return f"{label} is not running."
        return f"{label} is running as PID {process.pid}."
    if action == "apps_restart":
        return f"Restarting {label} requires confirmation and is not run automatically."
    return "Unknown application inventory command."
