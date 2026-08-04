"""Service facade for final release gate routes."""

from __future__ import annotations

from typing import Any

from grandpa.services.base import safe_call


def latest() -> dict[str, Any]:
    from grandpa.release_gate import latest_release_gate_report

    return latest_release_gate_report()


def status() -> dict[str, Any]:
    from grandpa.release_gate import release_gate_status

    return release_gate_status()


def diagnostics() -> dict[str, Any]:
    return latest()


def health() -> dict[str, Any]:
    payload = safe_call("release_gate", status)
    return {
        "name": "release_gate",
        "ready": bool(payload.get("pass") or payload.get("overall_status") == "ready"),
        "status": str(
            payload.get("overall_status") or payload.get("status") or "unknown"
        ),
        "dependencies": {
            "latest_report": bool(
                payload.get("report_path") or payload.get("last_run_at")
            )
        },
    }


def readiness() -> dict[str, Any]:
    payload = safe_call("release_gate", status)
    return {
        "ready": bool(payload.get("pass") or payload.get("overall_status") == "ready"),
        "recommendation": payload.get("recommendation", ""),
        "warnings": payload.get("summary", {}).get("warnings", 0)
        if isinstance(payload.get("summary"), dict)
        else 0,
        "blockers": payload.get("summary", {}).get("blockers", 0)
        if isinstance(payload.get("summary"), dict)
        else 0,
    }
