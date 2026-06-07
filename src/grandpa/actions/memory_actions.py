"""Reserved low-risk memory action handlers.

Memory commands still live in the existing memory/context pipeline. This
module exists so the action router can report domain ownership without moving
stateful memory behavior prematurely.
"""

from __future__ import annotations

HANDLERS: set[str] = set()


def try_handle(command: str):
    return None
