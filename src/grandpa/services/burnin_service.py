"""Service facade for daily-use burn-in validation."""

from __future__ import annotations

from typing import Any

from grandpa.services.base import safe_call


def latest() -> dict[str, Any]:
    from grandpa.burnin import latest_report

    return latest_report()


def status() -> dict[str, Any]:
    from grandpa.burnin import status as burnin_status

    return burnin_status()


def diagnostics() -> dict[str, Any]:
    from grandpa.burnin import diagnostics as burnin_diagnostics

    return burnin_diagnostics()


def health() -> dict[str, Any]:
    payload = safe_call("burnin", status)
    return {
        "name": "burnin",
        "ready": bool(payload.get("pass")),
        "status": payload.get("overall_status", payload.get("status", "unknown")),
        "dependencies": {
            "latest_report": bool(payload.get("finished_at")),
            "score": payload.get("score", 0),
        },
    }


def readiness() -> dict[str, Any]:
    payload = safe_call("burnin", status)
    return {
        "ready": bool(payload.get("pass")),
        "score": payload.get("score", 0),
        "recommendation": payload.get("recommendation", ""),
        "summary": payload.get("summary", {}),
    }
