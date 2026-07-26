"""Volume parsing helpers for high-level desktop automation."""

from __future__ import annotations


def clamp_volume(value: int) -> int:
    """Clamp a volume percentage to the Windows mixer range."""

    return max(0, min(100, int(value)))


__all__ = ["clamp_volume"]
