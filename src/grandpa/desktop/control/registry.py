"""Service registry for Grandpa desktop control domains."""

from __future__ import annotations

import sys
from functools import lru_cache
from typing import Any

from grandpa.desktop.control.applications import ApplicationControlService
from grandpa.desktop.control.automation import AutomationControlService
from grandpa.desktop.control.clipboard import ClipboardControlService
from grandpa.desktop.control.diagnostics import DesktopDiagnosticsService
from grandpa.desktop.control.files import FileControlService
from grandpa.desktop.control.monitors import MonitorControlService
from grandpa.desktop.control.power import PowerControlService
from grandpa.desktop.control.windows import WindowControlService


@lru_cache(maxsize=1)
def get_application_service() -> ApplicationControlService:
    return ApplicationControlService()


@lru_cache(maxsize=1)
def get_window_service() -> WindowControlService:
    return WindowControlService()


@lru_cache(maxsize=1)
def get_clipboard_service() -> ClipboardControlService:
    return ClipboardControlService()


@lru_cache(maxsize=1)
def get_monitor_service() -> MonitorControlService:
    return MonitorControlService()


@lru_cache(maxsize=1)
def get_diagnostics_service() -> DesktopDiagnosticsService:
    return DesktopDiagnosticsService()


@lru_cache(maxsize=1)
def get_file_service() -> FileControlService:
    return FileControlService()


@lru_cache(maxsize=1)
def get_automation_service() -> AutomationControlService:
    return AutomationControlService()


@lru_cache(maxsize=1)
def get_power_service() -> PowerControlService:
    return PowerControlService()


def list_desktop_services(*, platform: str | None = None) -> list[dict[str, Any]]:
    platform = platform or sys.platform
    services = [
        get_application_service().diagnostics(),
        get_window_service().diagnostics(),
        get_clipboard_service().diagnostics(),
        get_monitor_service().diagnostics(),
        get_diagnostics_service().diagnostics(),
        get_file_service().diagnostics(),
        get_automation_service().diagnostics(platform=platform),
        get_power_service().diagnostics(platform=platform),
    ]
    return services


def desktop_control_diagnostics(*, platform: str | None = None) -> dict[str, Any]:
    services = list_desktop_services(platform=platform)
    ready = sum(1 for service in services if service.get("ready"))
    return {
        "status": "ready" if ready else "unsupported",
        "service_count": len(services),
        "ready_count": ready,
        "services": services,
        "support_matrix": {
            str(service.get("service")): {
                "ready": bool(service.get("ready")),
                "risk_levels": service.get("risk_levels", {}),
                "dependencies": service.get("dependencies", {}),
            }
            for service in services
        },
        "local_only": True,
    }


__all__ = [
    "desktop_control_diagnostics",
    "get_application_service",
    "get_automation_service",
    "get_clipboard_service",
    "get_diagnostics_service",
    "get_file_service",
    "get_monitor_service",
    "get_power_service",
    "get_window_service",
    "list_desktop_services",
]
