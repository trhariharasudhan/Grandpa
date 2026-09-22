"""What a parsed phrase reports back.

The type lived in ``local_actions`` next to 2,300 lines of parsing and
dispatch, so a module that only wanted to *describe* a result -- the action
modules, the router's legacy adapter -- had to import all of it. It is its own
module now, ahead of ``local_actions`` being deleted: the shape outlives the
module it grew up in, and ``natural_actions.PhraseResult`` is the same shape for
actions that have moved onto the action layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ActionStatus = Literal[
    "handled",
    "requires_confirmation",
    "blocked",
    "unsupported",
    "no_match",
    "error",
    "cancelled",
]
PermissionStatus = Literal["allowed", "requires_confirmation", "blocked", "unsupported"]
ActionKind = Literal[
    "app",
    "folder",
    "url",
    "time",
    "system_info",
    "screen",
    "screenshot",
    "browser",
    "automation",
    "window",
    "app_lookup",
    "pc_control",
    "agent_plan",
    "blocked",
]


@dataclass(frozen=True)
class LocalActionResult:
    status: ActionStatus
    kind: ActionKind | None = None
    target: str = ""
    message: str = ""
    tts_text: str = ""
    permission: PermissionStatus | None = None
    pending_action: dict[str, Any] | None = None

    @property
    def should_fallback(self) -> bool:
        """True when the assistant's normal pipeline should answer instead."""
        return self.status == "no_match"


__all__ = [
    "ActionKind",
    "ActionStatus",
    "LocalActionResult",
    "PermissionStatus",
]
