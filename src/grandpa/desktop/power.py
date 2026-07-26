"""Power action names for high-level desktop automation."""

from __future__ import annotations

POWER_ACTIONS: dict[str, tuple[str, str, bool]] = {
    "lock": ("system_lock", "PC locked.", False),
    "sleep": ("system_sleep", "Sleep requested.", True),
    "restart": ("system_restart", "Restart requested.", True),
    "shutdown": ("system_shutdown", "Shutdown requested.", True),
}


def resolve_power_action(value: str) -> tuple[str, str, bool] | None:
    """Resolve a natural power action to a PC-control action."""

    return POWER_ACTIONS.get(value.strip().casefold())


__all__ = ["POWER_ACTIONS", "resolve_power_action"]
