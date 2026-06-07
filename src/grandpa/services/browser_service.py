"""Service facade for visible-browser diagnostics."""

from __future__ import annotations

import json
from typing import Any

from grandpa.services.base import safe_call


def diagnostics() -> dict[str, Any]:
    from grandpa.browser_control import execute_browser_action

    result = execute_browser_action("diagnostics", "browser")
    details: dict[str, Any] = {}
    try:
        details = json.loads(result.target) if result.target else {}
    except Exception:
        details = {"raw": result.target}
    return {
        "status": result.status,
        "ready": result.status == "handled",
        "message": result.message,
        "risk_level": result.risk_level,
        "details": details,
        "context": result.context.to_dict() if result.context else {},
        "local_only": True,
    }


def health() -> dict[str, Any]:
    payload = safe_call("browser", diagnostics)
    return {
        "name": "browser",
        "ready": bool(payload.get("ready")),
        "status": payload.get("status", "unknown"),
        "dependencies": {
            "extension_connected": bool(payload.get("details", {}).get("extension_connected")) if isinstance(payload.get("details"), dict) else False,
            "visible_page": bool(payload.get("context", {}).get("supported")) if isinstance(payload.get("context"), dict) else False,
        },
    }


def readiness() -> dict[str, Any]:
    payload = safe_call("browser", diagnostics)
    return {"ready": bool(payload.get("ready")), "message": payload.get("message", ""), "local_only": True}
