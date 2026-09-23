"""The local action router.

``handle_local_action`` takes what a person typed or said and, when it matches
one of the allowlisted phrases, describes and optionally performs it. It never
runs an arbitrary shell, PowerShell or cmd string.
"""

from grandpa.local.permissions import approve_pending_action, deny_pending_action
from grandpa.local.router import handle_local_action, refuse_confirmation
from grandpa.local.types import BLOCKED_MESSAGE, ConfirmationCallback

__all__ = [
    "BLOCKED_MESSAGE",
    "ConfirmationCallback",
    "approve_pending_action",
    "deny_pending_action",
    "handle_local_action",
    "refuse_confirmation",
]
