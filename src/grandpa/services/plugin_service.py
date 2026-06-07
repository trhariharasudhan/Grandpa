"""Service facade for local plugin runtime routes."""

from __future__ import annotations

from typing import Any

from grandpa.services.base import safe_call, summarize_ready


def diagnostics() -> dict[str, Any]:
    from grandpa.plugins import plugin_diagnostics

    return plugin_diagnostics()


def get(name: str) -> dict[str, Any] | None:
    from grandpa.plugins import get_plugin

    return get_plugin(name)


def reload() -> dict[str, Any]:
    from grandpa.plugins import plugin_diagnostics, reload_plugins

    return {"reload": reload_plugins(), "diagnostics": plugin_diagnostics()}


def enable(name: str) -> dict[str, Any]:
    from grandpa.plugins import enable_plugin

    return enable_plugin(name)


def disable(name: str) -> dict[str, Any]:
    from grandpa.plugins import disable_plugin

    return disable_plugin(name)


def health() -> dict[str, Any]:
    payload = safe_call("plugins", diagnostics)
    return {
        "name": "plugins",
        "ready": summarize_ready(payload),
        "status": payload.get("status", "ready"),
        "dependencies": {"manifests": payload.get("plugin_count", 0), "enabled": payload.get("enabled_count", 0)},
    }


def readiness() -> dict[str, Any]:
    payload = safe_call("plugins", diagnostics)
    return {
        "ready": summarize_ready(payload),
        "plugin_count": payload.get("plugin_count", 0),
        "invalid_count": payload.get("invalid_count", 0),
        "local_only": payload.get("local_only", True),
    }
