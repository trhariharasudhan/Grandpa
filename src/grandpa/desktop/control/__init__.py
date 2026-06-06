"""Domain services for Grandpa desktop and PC control."""

from grandpa.desktop.control.registry import (
    desktop_control_diagnostics,
    get_application_service,
    get_automation_service,
    get_clipboard_service,
    get_diagnostics_service,
    get_file_service,
    get_monitor_service,
    get_power_service,
    get_window_service,
    list_desktop_services,
)

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
