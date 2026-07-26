"""Local Windows Application Manager."""

from grandpa.apps.automation import ApplicationManager
from grandpa.apps.inventory import (
    AppFindResult,
    AppInventoryRecord,
    find_app,
    list_apps,
    normalize_app_name,
    scan_app_inventory,
)

__all__ = [
    "AppFindResult",
    "AppInventoryRecord",
    "ApplicationManager",
    "find_app",
    "list_apps",
    "normalize_app_name",
    "scan_app_inventory",
]
