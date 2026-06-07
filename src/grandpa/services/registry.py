"""Registry for Grandpa API service facades."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from grandpa.services.base import safe_call

SERVICE_MODULES: tuple[tuple[str, str, str], ...] = (
    ("skills", "grandpa.services.skill_service", "Runtime skill registry and execution"),
    ("desktop", "grandpa.services.desktop_service", "Desktop and PC-control services"),
    ("browser", "grandpa.services.browser_service", "Visible browser context and diagnostics"),
    ("vision", "grandpa.services.vision_service", "Screen awareness and visual diagnostics"),
    ("workflows", "grandpa.services.workflow_service", "Automation and workflow runtime"),
    ("planner", "grandpa.services.planner_service", "Planner, agent runtime, MCP, and intent routing"),
    ("plugins", "grandpa.services.plugin_service", "Manifest-driven plugin runtime"),
    ("release_gate", "grandpa.services.release_service", "Production release readiness gate"),
)


def _service_payload(name: str, module_path: str, description: str) -> dict[str, Any]:
    module = import_module(module_path)
    health = safe_call(name, module.health)
    readiness = safe_call(name, module.readiness)
    diagnostics = safe_call(name, module.diagnostics)
    ready = bool(health.get("ready")) and bool(readiness.get("ready", health.get("ready")))
    return {
        "name": name,
        "description": description,
        "ready": ready,
        "health": health,
        "readiness": readiness,
        "dependencies": health.get("dependencies", {}),
        "diagnostics": diagnostics,
    }


def service_diagnostics() -> dict[str, Any]:
    services = []
    for name, module_path, description in SERVICE_MODULES:
        services.append(_service_payload(name, module_path, description))
    ready_count = sum(1 for service in services if service.get("ready"))
    return {
        "status": "ready" if ready_count == len(services) else "partial",
        "service_count": len(services),
        "ready_count": ready_count,
        "services": services,
        "local_only": True,
    }


def service_names() -> list[str]:
    return [name for name, _, _ in SERVICE_MODULES]
