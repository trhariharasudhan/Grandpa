"""Domain action handlers behind the legacy local action facade."""

from grandpa.actions.router import (
    action_audit_summary,
    action_diagnostics,
    reset_action_diagnostics,
    route_action,
)

__all__ = [
    "action_audit_summary",
    "action_diagnostics",
    "reset_action_diagnostics",
    "route_action",
]
