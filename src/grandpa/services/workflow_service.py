"""Service facade for workflow and automation diagnostics."""

from __future__ import annotations

from typing import Any

from grandpa.services.base import safe_call, summarize_ready


def diagnostics() -> dict[str, Any]:
    from grandpa.smart_automation import diagnostics as workflow_diagnostics

    return workflow_diagnostics()


def health() -> dict[str, Any]:
    payload = safe_call("workflows", diagnostics)
    return {
        "name": "workflows",
        "ready": summarize_ready(payload),
        "status": payload.get("status", "ready"),
        "dependencies": {
            "workflow_count": payload.get("workflow_count", payload.get("count", 0)),
            "schema": payload.get("schema", payload.get("schema_version", "unknown")),
        },
    }


def readiness() -> dict[str, Any]:
    payload = safe_call("workflows", diagnostics)
    return {"ready": summarize_ready(payload), "diagnostics": payload}
