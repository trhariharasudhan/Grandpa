"""Risk classification and approval policy for PC-control actions."""

from __future__ import annotations

from typing import Any


def classify(request: Any) -> str:
    from grandpa import pc_control

    return pc_control._classify_risk_impl(request)


def requires_approval(request: Any) -> bool:
    risk = classify(request)
    return bool(getattr(request, "require_approval", False) or risk == "HIGH")


def readiness() -> dict[str, Any]:
    from grandpa import pc_control

    return {
        "status": "ready",
        "low_risk_actions": len(pc_control.LOW_RISK_ACTIONS),
        "medium_risk_actions": len(pc_control.MEDIUM_RISK_ACTIONS),
        "high_risk_actions": len(pc_control.HIGH_RISK_ACTIONS),
        "blocked_actions": len(pc_control.BLOCKED_ACTIONS),
    }
