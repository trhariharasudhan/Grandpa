"""Execution orchestration for PC-control actions."""

from __future__ import annotations

from typing import Any


def execute(request: Any, risk: str):
    from grandpa import pc_control

    return pc_control._execute(request, risk)


def preflight_guard(request: Any, risk: str):
    from grandpa import pc_control

    return pc_control._preflight_guard(request, risk)


def dry_run_message(request: Any, risk: str) -> str:
    from grandpa import pc_control

    return pc_control._dry_run_message(request, risk)


def approval_message(request: Any) -> str:
    from grandpa import pc_control

    return pc_control._approval_message(request)


def readiness() -> dict[str, Any]:
    from grandpa.desktop.control import desktop_control_diagnostics

    diagnostics = desktop_control_diagnostics()
    return {
        "status": diagnostics.get("status", "ready"),
        "service_count": diagnostics.get("service_count", 0),
        "ready_count": diagnostics.get("ready_count", 0),
        "support_matrix": diagnostics.get("support_matrix", {}),
    }
