"""Small shims for the oldest Python that ``pyproject.toml`` promises to run on.

``requires-python`` says 3.10, but CI runs 3.12 and the installer 3.11, so a
3.11-only name can land without anything noticing. ``enum.StrEnum`` did: three
state enums (the bubble, the avatar and the voice session) imported it, and on
3.10 importing any of them raised ``ImportError`` before Grandpa could say why.

Import such names from here instead of from the standard library.
"""

from __future__ import annotations

import sys
from enum import Enum

__all__ = ["StrEnum"]


class _StrEnumFallback(str, Enum):
    """The parts of 3.11's ``enum.StrEnum`` that Grandpa relies on.

    A plain ``(str, Enum)`` already compares and hashes as its value. What it
    gets wrong is text: ``str(member)`` and ``f"{member}"`` give
    ``"Class.NAME"`` instead of the value, and that text is what the bubble
    and the avatar socket publish. ``auto()`` also differs: StrEnum gives the
    lower-cased name.
    """

    def __str__(self) -> str:
        return str(self.value)

    def __format__(self, format_spec: str) -> str:
        return format(str(self.value), format_spec)

    @staticmethod
    def _generate_next_value_(
        name: str, start: int, count: int, last_values: list
    ) -> str:
        return name.lower()


if sys.version_info >= (3, 11):
    from enum import StrEnum
else:  # pragma: no cover - exercised on 3.10 only; the fallback itself is tested directly
    StrEnum = _StrEnumFallback
