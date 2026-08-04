"""Backward-compatible application inventory facade."""

from __future__ import annotations

from pathlib import Path

from grandpa.apps.launcher import launch_application
from grandpa.apps.models import ApplicationInfo
from grandpa.apps.models import AppResolveResult as AppFindResult
from grandpa.apps.registry import (
    DEFAULT_APP_REGISTRY_PATH as DEFAULT_APP_INVENTORY_PATH,
)
from grandpa.apps.registry import load_app_registry, save_app_registry
from grandpa.apps.resolver import normalize_app_name, resolve_app
from grandpa.apps.scanner import (
    MAX_DISCOVERED_APPS,
    default_install_roots,
    default_start_menu_roots,
    scan_app_inventory,
)


class AppInventoryRecord(ApplicationInfo):
    """Compatibility record with the historical positional constructor."""

    def __init__(
        self,
        display_name: str,
        normalized_name: str,
        launch_target: str,
        source: str,
        aliases: tuple[str, ...],
        last_seen_at: float,
    ) -> None:
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "aliases", tuple(aliases))
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "path", launch_target)
        object.__setattr__(
            self,
            "working_directory",
            str(Path(launch_target).parent) if launch_target else "",
        )
        object.__setattr__(self, "publisher", "")
        object.__setattr__(self, "version", "")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "icon_path", launch_target)
        object.__setattr__(self, "last_seen_at", last_seen_at)
        object.__setattr__(self, "confidence", 1.0)
        object.__setattr__(self, "is_user_facing", True)
        object.__setattr__(self, "is_launchable", True)
        object.__setattr__(self, "canonical_key", normalized_name)


def list_apps(
    *, store_path: Path = DEFAULT_APP_INVENTORY_PATH
) -> list[AppInventoryRecord]:
    return [_compat_record(app) for app in load_app_registry(store_path=store_path)]


def save_inventory(
    apps: list[AppInventoryRecord], *, store_path: Path = DEFAULT_APP_INVENTORY_PATH
) -> None:
    save_app_registry(apps, store_path=store_path)


def find_app(
    name: str, *, store_path: Path = DEFAULT_APP_INVENTORY_PATH
) -> AppFindResult:
    return resolve_app(name, list_apps(store_path=store_path))


def launch_inventory_app(record: AppInventoryRecord) -> str:
    return launch_application(record)


def _compat_record(app: ApplicationInfo) -> AppInventoryRecord:
    return AppInventoryRecord(
        app.display_name, app.name, app.path, app.source, app.aliases, app.last_seen_at
    )


__all__ = [
    "AppFindResult",
    "AppInventoryRecord",
    "DEFAULT_APP_INVENTORY_PATH",
    "MAX_DISCOVERED_APPS",
    "default_install_roots",
    "default_start_menu_roots",
    "find_app",
    "launch_inventory_app",
    "list_apps",
    "normalize_app_name",
    "save_inventory",
    "scan_app_inventory",
]
