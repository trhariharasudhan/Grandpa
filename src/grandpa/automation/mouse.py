"""Mouse action payload builders for the existing PC-control layer."""

from __future__ import annotations

from typing import Any

from grandpa.automation.models import AutomationAction, Point


def mouse_payload(action: AutomationAction, point: Point | None = None) -> dict[str, Any]:
    args = dict(action.args)
    if point is not None:
        args.update({"x": point.x, "y": point.y})
    if action.kind == "move":
        return _payload("mouse_move", action.target, args)
    if action.kind in {"click", "double_click", "right_click", "middle_click"}:
        args.setdefault("button", _button(action.kind))
        args.setdefault("clicks", 2 if action.kind == "double_click" else 1)
        return _payload("mouse_click", action.target, args)
    if action.kind == "scroll":
        return _payload("mouse_scroll", action.target, args)
    if action.kind == "drag":
        return _payload("mouse_drag", action.target, args)
    raise ValueError(f"Unsupported mouse action: {action.kind}")


def _button(kind: str) -> str:
    return {"right_click": "right", "middle_click": "middle"}.get(kind, "left")


def _payload(action_type: str, target: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"action_type": action_type, "target": target, "args": args}


__all__ = ["mouse_payload"]
