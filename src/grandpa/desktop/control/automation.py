"""Keyboard and mouse automation service for PC control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Key aliases normalised before checking the hotkey denylist, so "Windows+R",
# "win + r" and "WIN+r" are all recognised as the same combination.
_HOTKEY_ALIASES = {
    "windows": "win",
    "super": "win",
    "meta": "win",
    "cmd": "win",
    "command": "win",
    "control": "ctrl",
    "escape": "esc",
    "del": "delete",
    "return": "enter",
}

# Key combinations that open a command-execution surface. These are blocked
# outright rather than gated on approval: approving "press Win+R" is in effect
# approving shell access, which BLOCKED_ACTIONS (script_run / shell_run) exists
# to prevent. Compared as unordered key sets.
_BLOCKED_HOTKEYS = (
    frozenset({"win", "r"}),  # Run dialog
    frozenset({"win", "x"}),  # Power User menu -> Terminal / PowerShell
    frozenset({"ctrl", "shift", "esc"}),  # Task Manager
    frozenset({"ctrl", "alt", "delete"}),  # Secure attention sequence
)


def _normalise_hotkey(keys: Any) -> list[str]:
    """Split and canonicalise a hotkey spec into a list of lowercase key names."""
    if isinstance(keys, str):
        parts = [part for part in keys.split("+")]
    elif isinstance(keys, (list, tuple)):
        parts = [str(part) for part in keys]
    else:
        parts = [str(keys)]
    normalised: list[str] = []
    for part in parts:
        token = str(part).strip().lower()
        if not token:
            continue
        normalised.append(_HOTKEY_ALIASES.get(token, token))
    return normalised


def is_blocked_hotkey(keys: Any) -> bool:
    """Return ``True`` when *keys* names a denied command-execution shortcut."""
    pressed = frozenset(_normalise_hotkey(keys))
    return any(combo <= pressed for combo in _BLOCKED_HOTKEYS)


@dataclass(frozen=True)
class AutomationControlService:
    """Visible-screen keyboard and mouse actions."""

    name: str = "automation"

    def execute(self, request: Any, action: str, *, platform: str):
        from grandpa.pc_control import LocalActionResponse

        if platform != "win32":
            return LocalActionResponse(
                False,
                None,
                "unsupported",
                "Keyboard and mouse control is only supported on Windows desktop.",
                False,
                "MEDIUM",
                error="unsupported",
            )
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True
        if action == "keyboard_type":
            text = str(request.args.get("text", request.target))
            pyautogui.write(text, interval=0.01)
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Typed text.",
                False,
                "MEDIUM",
                {"characters": len(text)},
            )
        if action == "keyboard_hotkey":
            raw_keys = request.args.get("keys", request.target)
            keys = _normalise_hotkey(raw_keys)
            if not keys:
                return LocalActionResponse(
                    False,
                    None,
                    "blocked",
                    "I blocked this hotkey because no keys were supplied.",
                    False,
                    "BLOCKED",
                    error="blocked_by_policy",
                )
            if is_blocked_hotkey(keys):
                return LocalActionResponse(
                    False,
                    None,
                    "blocked",
                    "I blocked this hotkey because it opens a command-execution surface.",
                    False,
                    "BLOCKED",
                    {"keys": keys},
                    error="blocked_by_policy",
                )
            pyautogui.hotkey(*keys)
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Pressed hotkey.",
                False,
                "MEDIUM",
                {"keys": keys},
            )
        if action == "mouse_move":
            if "relative_x" in request.args or "relative_y" in request.args:
                pyautogui.moveRel(
                    int(request.args.get("relative_x", 0)),
                    int(request.args.get("relative_y", 0)),
                    duration=max(
                        0.0, min(1.0, float(request.args.get("duration", 0.15)))
                    ),
                )
            else:
                pyautogui.moveTo(
                    int(request.args.get("x", 0)),
                    int(request.args.get("y", 0)),
                    duration=max(
                        0.0, min(1.0, float(request.args.get("duration", 0.15)))
                    ),
                )
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Moved mouse.",
                False,
                "MEDIUM",
                {"x": request.args.get("x"), "y": request.args.get("y")},
            )
        if action == "mouse_click":
            pyautogui.click(
                int(request.args.get("x", 0)),
                int(request.args.get("y", 0)),
                clicks=max(1, min(2, int(request.args.get("clicks", 1)))),
                interval=max(0.0, min(0.5, float(request.args.get("interval", 0.12)))),
                button=str(request.args.get("button", "left")),
            )
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Clicked mouse.",
                False,
                "MEDIUM",
                {"x": request.args.get("x"), "y": request.args.get("y")},
            )
        if action == "mouse_scroll":
            pyautogui.scroll(int(request.args.get("amount", request.target or 0)))
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Scrolled mouse.",
                False,
                "MEDIUM",
                {"amount": request.args.get("amount", request.target)},
            )
        if action == "mouse_drag":
            start_x = int(request.args.get("start_x", request.args.get("x", 0)))
            start_y = int(request.args.get("start_y", request.args.get("y", 0)))
            end_x = int(request.args.get("end_x", request.args.get("to_x", 0)))
            end_y = int(request.args.get("end_y", request.args.get("to_y", 0)))
            duration = max(0.1, min(2.0, float(request.args.get("duration", 0.25))))
            pyautogui.moveTo(start_x, start_y)
            pyautogui.dragTo(
                end_x,
                end_y,
                duration=duration,
                button=str(request.args.get("button", "left")),
            )
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Dragged the mouse.",
                False,
                "MEDIUM",
                {
                    "start": [start_x, start_y],
                    "end": [end_x, end_y],
                    "duration": duration,
                },
            )
        if action == "desktop_navigate":
            direction = str(request.args.get("direction", request.target)).lower()
            if direction not in {"up", "down", "left", "right"}:
                return LocalActionResponse(
                    False,
                    None,
                    "blocked",
                    "I blocked this navigation action for safety.",
                    False,
                    "BLOCKED",
                    error="blocked_by_policy",
                )
            pyautogui.press(direction)
            return LocalActionResponse(
                True,
                None,
                "completed",
                f"Moved selection {direction}.",
                False,
                "MEDIUM",
                {"direction": direction},
            )
        return LocalActionResponse(
            False,
            None,
            "blocked",
            "I blocked this automation action for safety.",
            False,
            "BLOCKED",
            error="blocked_by_policy",
        )

    def diagnostics(self, *, platform: str) -> dict[str, Any]:
        try:
            import pyautogui  # noqa: F401

            pyautogui_available = True
        except Exception:
            pyautogui_available = False
        return {
            "service": self.name,
            "ready": platform == "win32" and pyautogui_available,
            "risk_levels": {
                "keyboard_type": "MEDIUM",
                "keyboard_hotkey": "MEDIUM",
                "mouse_move": "MEDIUM",
                "mouse_click": "MEDIUM",
                "mouse_scroll": "MEDIUM",
                "mouse_drag": "MEDIUM",
                "desktop_navigate": "MEDIUM",
            },
            "dependencies": {"pyautogui": pyautogui_available, "platform": platform},
            "safety": {"failsafe": True, "protected_window_preflight": True},
        }


__all__ = ["AutomationControlService"]
