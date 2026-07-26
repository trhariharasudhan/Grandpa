"""Keyboard action payload builders for the existing PC-control layer."""

from __future__ import annotations

from typing import Any

from grandpa.automation.models import AutomationAction


def keyboard_payload(action: AutomationAction) -> dict[str, Any]:
    if action.kind == "type":
        return {
            "action_type": "keyboard_type",
            "target": "focused app",
            "args": {"text": action.args.get("text", action.target)},
        }
    if action.kind in {"press", "paste"}:
        keys = action.args.get("keys", [])
        return {
            "action_type": "keyboard_hotkey",
            "target": "+".join(str(key) for key in keys),
            "args": {"keys": keys},
        }
    raise ValueError(f"Unsupported keyboard action: {action.kind}")


__all__ = ["keyboard_payload"]
