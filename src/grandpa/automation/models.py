"""Typed contracts for Screen Automation V2."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

AutomationStatus = Literal[
    "handled",
    "success",
    "partial_success",
    "failed",
    "needs_confirmation",
    "confirmation_required",
    "blocked",
    "target_lost",
    "unsupported",
    "not_found",
    "ambiguous",
    "error",
    "no_match",
]


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class BoundingBox:
    left: int
    top: int
    width: int
    height: int

    @property
    def center(self) -> Point:
        return Point(self.left + self.width // 2, self.top + self.height // 2)


@dataclass(frozen=True)
class LocatedElement:
    text: str
    role: str
    confidence: float
    bounds: BoundingBox
    source: str = "ocr"
    window_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AutomationAction:
    kind: str
    target: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    confirmation_reason: str = ""
    sensitive: bool = False


@dataclass(frozen=True)
class AutomationResult:
    status: AutomationStatus
    message: str
    action: AutomationAction | None = None
    element: LocatedElement | None = None
    confirmation_token: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"

    @property
    def execution_status(self) -> str:
        """Return the canonical cross-entrypoint execution status."""

        return {
            "handled": "success",
            "needs_confirmation": "confirmation_required",
            "not_found": "failed",
            "ambiguous": "failed",
            "error": "failed",
            "no_match": "unsupported",
        }.get(self.status, self.status)


__all__ = [
    "AutomationAction",
    "AutomationResult",
    "AutomationStatus",
    "BoundingBox",
    "LocatedElement",
    "Point",
]
