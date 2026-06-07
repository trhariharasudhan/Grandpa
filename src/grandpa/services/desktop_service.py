"""Service facade for desktop domain diagnostics."""

from __future__ import annotations

from typing import Any

from grandpa.services.base import safe_call


def diagnostics() -> dict[str, Any]:
    from grandpa.desktop.control import desktop_control_diagnostics

    return desktop_control_diagnostics()


def health() -> dict[str, Any]:
    payload = safe_call("desktop", diagnostics)
    service_count = int(payload.get("service_count", 0) or 0)
    ready_count = int(payload.get("ready_count", 0) or 0)
    ready = service_count > 0 and ready_count > 0
    return {
        "name": "desktop",
        "ready": ready,
        "status": payload.get("status", "ready" if ready else "partial"),
        "dependencies": {"service_count": service_count, "ready_count": ready_count},
    }


def readiness() -> dict[str, Any]:
    payload = safe_call("desktop", diagnostics)
    return {
        "ready": health()["ready"],
        "service_count": payload.get("service_count", 0),
        "ready_count": payload.get("ready_count", 0),
        "local_only": payload.get("local_only", True),
    }
