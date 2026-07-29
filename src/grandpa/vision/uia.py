"""Best-effort read-only Windows UI Automation extraction."""

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from typing import Any

from grandpa.screen.models import WindowInfo
from grandpa.vision.models import VisionBounds, VisionNode

logger = logging.getLogger(__name__)

CONTROL_TYPES = {
    50000: "button",
    50001: "calendar",
    50002: "checkbox",
    50003: "combo_box",
    50004: "edit",
    50005: "hyperlink",
    50006: "image",
    50007: "list_item",
    50008: "list",
    50009: "menu",
    50010: "menu_bar",
    50011: "menu_item",
    50012: "progress_bar",
    50013: "radio_button",
    50014: "scroll_bar",
    50015: "slider",
    50016: "spinner",
    50017: "status_bar",
    50018: "tab",
    50019: "tab_item",
    50020: "text",
    50021: "toolbar",
    50022: "tooltip",
    50023: "tree",
    50024: "tree_item",
    50025: "custom",
    50026: "group",
    50027: "thumb",
    50028: "data_grid",
    50029: "data_item",
    50030: "document",
    50031: "split_button",
    50032: "window",
    50033: "pane",
    50034: "header",
    50035: "header_item",
    50036: "table",
    50037: "title_bar",
    50038: "separator",
}
CLICKABLE_TYPES = {
    "button",
    "checkbox",
    "combo_box",
    "hyperlink",
    "list_item",
    "menu_item",
    "radio_button",
    "tab_item",
    "tree_item",
}
EDITABLE_TYPES = {"edit", "document"}
SCROLLABLE_TYPES = {"list", "pane", "scroll_bar", "table", "tree"}


class UiAutomationExtractor:
    """Extract a bounded active-window UIA tree without invoking controls."""

    def __init__(self, *, max_nodes: int = 1500) -> None:
        self.max_nodes = max(1, max_nodes)
        self.last_error = ""

    def extract(self, window: WindowInfo | None) -> tuple[VisionNode, ...]:
        if sys.platform != "win32" or window is None or not window.handle:
            return ()
        try:
            from grandpa.windows_window_control import _uia

            automation, _module = _uia()
            root = automation.ElementFromHandle(window.handle)
            elements = root.FindAll(4, automation.CreateTrueCondition())
            raw = [root]
            raw.extend(
                elements.GetElement(index)
                for index in range(min(int(elements.Length), self.max_nodes - 1))
            )
            nodes = [
                self._node(element, index, automation, window.pid)
                for index, element in enumerate(raw)
            ]
            nodes = [item for item in nodes if item is not None]
            return _attach_children(nodes)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.debug("UI Automation extraction unavailable: %s", exc)
            return ()

    def _node(
        self, element: Any, index: int, automation: Any, process_id: int
    ) -> VisionNode | None:
        try:
            element_pid = int(_safe_property(element, "CurrentProcessId", 0))
            if process_id and element_pid and element_pid != process_id:
                return None
            runtime_id = _runtime_id(element)
            node_id = _node_id(runtime_id, index)
            control_type = CONTROL_TYPES.get(
                int(_safe_property(element, "CurrentControlType", 0)),
                "unknown",
            )
            bounds = _bounds(_safe_property(element, "CurrentBoundingRectangle", None))
            if bounds.width <= 0 or bounds.height <= 0:
                visible = False
            else:
                visible = not bool(_safe_property(element, "CurrentIsOffscreen", False))
            parent_id = None
            try:
                parent = automation.ControlViewWalker.GetParentElement(element)
                if parent is not None:
                    parent_id = _node_id(_runtime_id(parent), -1)
            except Exception:
                pass
            enabled = bool(_safe_property(element, "CurrentIsEnabled", True))
            return VisionNode(
                id=node_id,
                type=control_type,
                name=str(_safe_property(element, "CurrentName", "") or "").strip(),
                text=str(_safe_property(element, "CurrentHelpText", "") or "").strip(),
                confidence=1.0,
                bounds=bounds,
                parent=parent_id,
                source="uia",
                clickable=enabled and control_type in CLICKABLE_TYPES,
                editable=enabled and control_type in EDITABLE_TYPES,
                scrollable=control_type in SCROLLABLE_TYPES,
                enabled=enabled,
                visible=visible,
                focused=bool(_safe_property(element, "CurrentHasKeyboardFocus", False)),
                selected=_safe_bool_property(element, 30079),
                value=str(_safe_property(element, "CurrentItemStatus", "") or "").strip(),
                automation_id=str(
                    _safe_property(element, "CurrentAutomationId", "") or ""
                ).strip(),
                runtime_id=runtime_id,
            )
        except Exception:
            return None


def _attach_children(nodes: list[VisionNode]) -> tuple[VisionNode, ...]:
    ids = {item.id for item in nodes}
    children: dict[str, list[str]] = {}
    normalized: list[VisionNode] = []
    for node in nodes:
        parent = node.parent if node.parent in ids else None
        normalized.append(replace(node, parent=parent))
        if parent:
            children.setdefault(parent, []).append(node.id)
    return tuple(
        replace(node, children=tuple(children.get(node.id, ()))) for node in normalized
    )


def _safe_property(element: Any, name: str, default: Any) -> Any:
    try:
        return getattr(element, name)
    except Exception:
        return default


def _runtime_id(element: Any) -> tuple[int, ...]:
    try:
        values = element.GetRuntimeId()
        return tuple(int(value) for value in values)
    except Exception:
        return ()


def _safe_bool_property(element: Any, property_id: int) -> bool:
    try:
        value = element.GetCurrentPropertyValue(property_id)
        return bool(value) if isinstance(value, (bool, int)) else False
    except Exception:
        return False


def _node_id(runtime_id: tuple[int, ...], fallback: int) -> str:
    return "uia:" + (".".join(str(value) for value in runtime_id) or str(fallback))


def _bounds(rect: Any) -> VisionBounds:
    if rect is None:
        return VisionBounds(0, 0, 0, 0)
    try:
        left = int(rect.left)
        top = int(rect.top)
        right = int(rect.right)
        bottom = int(rect.bottom)
    except Exception:
        try:
            left, top, right, bottom = (int(value) for value in rect)
        except Exception:
            return VisionBounds(0, 0, 0, 0)
    return VisionBounds(left, top, max(0, right - left), max(0, bottom - top))


__all__ = ["CONTROL_TYPES", "UiAutomationExtractor"]
