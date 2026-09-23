"""The vocabulary the local router's modules share."""

from __future__ import annotations

from collections.abc import Callable

ConfirmationCallback = Callable[[str, str], bool]
"""What a caller passes to be asked before synthetic input runs."""

BLOCKED_MESSAGE = "I blocked this action for safety."
