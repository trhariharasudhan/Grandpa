"""Emergency stop state for PC-control kernel."""

from __future__ import annotations


def activate():
    from grandpa import pc_control

    return pc_control._emergency_stop_impl()


def reset() -> None:
    from grandpa import pc_control

    pc_control._reset_emergency_stop_impl()


def is_active() -> bool:
    from grandpa import pc_control

    return bool(pc_control._EMERGENCY_STOP_ACTIVE)


def readiness() -> dict[str, object]:
    return {
        "status": "ready",
        "active": is_active(),
        "mode": "blocks medium/high risk actions",
    }
