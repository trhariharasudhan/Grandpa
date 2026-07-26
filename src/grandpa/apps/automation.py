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

    def list(self, *, include_all: bool = False, source: str | None = None) -> list[ApplicationInfo]:
        apps = load_app_registry(store_path=self.store_path)
        if not include_all:
            apps = [
                app
                for app in apps
                if app.is_user_facing and app.is_launchable and app.confidence >= 0.7
            ]
        if source:
            apps = [app for app in apps if app.source == source or app.source.startswith(f"{source}:")]
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
