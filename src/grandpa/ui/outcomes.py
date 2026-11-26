"""Did a reply *do* something on this machine, or only answer?

Kept from the retired tkinter bubble (``grandpa bubble``, removed 2026-11-26):
the orb uses it to decide when the ring shows "done".
"""

from __future__ import annotations

from typing import Any

#: Kinds that are not "done": a plan was produced (not performed), a request was
#: refused, or a question was answered. Named so a test can assert each one is a
#: real ``ActionKind`` -- a typo here would exclude nothing and go unnoticed.
NOT_DONE_KINDS = frozenset({"agent_plan", "blocked", "app_lookup"})


def done_kinds() -> frozenset[str]:
    """The action kinds that mean something on this machine actually changed.

    Derived from the action layer's own ``ActionKind`` literal, so a kind added
    there cannot be silently missed. A kind not in ``ActionKind`` at all
    (``voice``, ``assistant``, ``local``) is conversation, not an action.
    """
    from typing import get_args

    from grandpa.local_action_result import ActionKind

    return frozenset(get_args(ActionKind)) - NOT_DONE_KINDS


def completed_an_operation(reply: Any) -> bool:
    """``status == "handled"`` *and* an action kind: an operation finished.

    Either alone is not enough: "handled" is also said of a plain chat answer,
    and an action kind is also reported when it was refused or only staged.
    """
    status = str(getattr(reply, "status", "") or "")
    kind = str(getattr(reply, "kind", "") or "")
    return status == "handled" and kind in done_kinds()


__all__ = ["NOT_DONE_KINDS", "completed_an_operation", "done_kinds"]
