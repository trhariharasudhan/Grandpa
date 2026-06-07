"""Request coercion and validation for the PC-control kernel."""

from __future__ import annotations

from typing import Any


def coerce_request(payload: dict[str, Any] | Any):
    """Normalize public API payloads into ``LocalActionRequest``."""

    from grandpa import pc_control

    return pc_control._coerce_request(payload)


def validate_request(payload: dict[str, Any] | Any) -> dict[str, Any]:
    request = coerce_request(payload)
    return {
        "valid": bool(request.action_type),
        "action_type": request.action_type,
        "target": request.target,
        "dry_run": request.dry_run,
        "require_approval": request.require_approval,
    }


def readiness() -> dict[str, Any]:
    return {"status": "ready", "normalization": "ready", "validation": "ready"}
