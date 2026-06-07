"""PC-control kernel package.

The kernel isolates approvals, audits, risk policy, request normalization,
execution orchestration, and emergency-stop state behind narrow modules while
``grandpa.pc_control`` remains the public compatibility facade.
"""

from __future__ import annotations

from typing import Any


def diagnostics() -> dict[str, Any]:
    from grandpa.desktop.kernel import (
        approvals,
        audits,
        emergency,
        execution,
        requests,
        risk,
    )

    return {
        "status": "ready",
        "approvals": approvals.readiness(),
        "audits": audits.readiness(),
        "risk": risk.readiness(),
        "requests": requests.readiness(),
        "execution": execution.readiness(),
        "emergency": emergency.readiness(),
        "local_only": True,
    }


__all__ = ["diagnostics"]
