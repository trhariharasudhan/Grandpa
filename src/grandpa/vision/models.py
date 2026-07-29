"""Structured contracts for Grandpa Vision Engine V1."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class VisionBounds:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def intersection_over_union(self, other: "VisionBounds") -> float:
        left = max(self.left, other.left)
        top = max(self.top, other.top)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        area = max(0, right - left) * max(0, bottom - top)
        union = self.area + other.area - area
        return area / union if union else 0.0


@dataclass(frozen=True)
class VisionNode:
    id: str
    type: str
    name: str = ""
    text: str = ""
    confidence: float = 0.0
    bounds: VisionBounds = field(default_factory=lambda: VisionBounds(0, 0, 0, 0))
    parent: str | None = None
    children: tuple[str, ...] = ()
    source: str = "unknown"
    clickable: bool = False
    editable: bool = False
    scrollable: bool = False
    enabled: bool = True
    visible: bool = True
    focused: bool = False
    selected: bool = False
    value: str = ""
    automation_id: str = ""
    runtime_id: tuple[int, ...] = ()

    @property
    def label(self) -> str:
        return self.name.strip() or self.text.strip() or self.value.strip()

    def to_dict(self, *, include_runtime: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if not include_runtime:
            data.pop("runtime_id", None)
        return data


@dataclass(frozen=True)
class VisionCaptureMetadata:
    width: int
    height: int
    monitor: int | None
    window_title: str
    window_handle: int
    process_id: int
    timestamp: datetime
    source: str
    backend: str
    region: tuple[int, int, int, int]

    def to_dict(self, *, include_private: bool = False) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        if not include_private:
            data.pop("window_handle", None)
            data.pop("process_id", None)
        return data


@dataclass(frozen=True)
class ElementGraph:
    nodes: tuple[VisionNode, ...]
    capture: VisionCaptureMetadata
    active_node_id: str | None = None
    ocr_available: bool = False
    uia_available: bool = False
    warnings: tuple[str, ...] = ()

    def node(self, node_id: str) -> VisionNode | None:
        return next((item for item in self.nodes if item.id == node_id), None)

    def to_dict(self, *, include_runtime: bool = False) -> dict[str, Any]:
        return {
            "capture": self.capture.to_dict(include_private=include_runtime),
            "active_node_id": self.active_node_id,
            "ocr_available": self.ocr_available,
            "uia_available": self.uia_available,
            "warnings": list(self.warnings),
            "nodes": [
                item.to_dict(include_runtime=include_runtime) for item in self.nodes
            ],
        }


@dataclass(frozen=True)
class VisionMatch:
    node: VisionNode
    confidence: float
    reasons: tuple[str, ...] = ()

    def to_dict(self, *, include_runtime: bool = False) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "node": self.node.to_dict(include_runtime=include_runtime),
        }


@dataclass(frozen=True)
class VisionResult:
    status: str
    message: str
    graph: ElementGraph | None = None
    matches: tuple[VisionMatch, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ElementGraph",
    "VisionBounds",
    "VisionCaptureMetadata",
    "VisionMatch",
    "VisionNode",
    "VisionResult",
]
