"""Keyboard and mouse automation service for PC control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
            return LocalActionResponse(True, None, "completed", "Typed text.", False, "MEDIUM", {"characters": len(text)})
        if action == "keyboard_hotkey":
            keys = request.args.get("keys", request.target)
            if isinstance(keys, str):
                keys = [part.strip() for part in keys.split("+") if part.strip()]
            pyautogui.hotkey(*keys)
            return LocalActionResponse(True, None, "completed", "Pressed hotkey.", False, "MEDIUM", {"keys": keys})
        if action == "mouse_move":
            pyautogui.moveTo(int(request.args.get("x", 0)), int(request.args.get("y", 0)))
            return LocalActionResponse(True, None, "completed", "Moved mouse.", False, "MEDIUM", {"x": request.args.get("x"), "y": request.args.get("y")})
        if action == "mouse_click":
            pyautogui.click(int(request.args.get("x", 0)), int(request.args.get("y", 0)))
            return LocalActionResponse(True, None, "completed", "Clicked mouse.", False, "MEDIUM", {"x": request.args.get("x"), "y": request.args.get("y")})
        if action == "mouse_scroll":
            pyautogui.scroll(int(request.args.get("amount", request.target or 0)))
            return LocalActionResponse(True, None, "completed", "Scrolled mouse.", False, "MEDIUM", {"amount": request.args.get("amount", request.target)})
        if action == "mouse_drag":
            start_x = int(request.args.get("start_x", request.args.get("x", 0)))
            start_y = int(request.args.get("start_y", request.args.get("y", 0)))
            end_x = int(request.args.get("end_x", request.args.get("to_x", 0)))
            end_y = int(request.args.get("end_y", request.args.get("to_y", 0)))
            duration = max(0.1, min(2.0, float(request.args.get("duration", 0.25))))
            pyautogui.moveTo(start_x, start_y)
            pyautogui.dragTo(end_x, end_y, duration=duration, button=str(request.args.get("button", "left")))
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Dragged the mouse.",
                False,
                "MEDIUM",
                {"start": [start_x, start_y], "end": [end_x, end_y], "duration": duration},
            )
        if action == "desktop_navigate":
            direction = str(request.args.get("direction", request.target)).lower()
            if direction not in {"up", "down", "left", "right"}:
                return LocalActionResponse(False, None, "blocked", "I blocked this navigation action for safety.", False, "BLOCKED", error="blocked_by_policy")
            pyautogui.press(direction)
            return LocalActionResponse(True, None, "completed", f"Moved selection {direction}.", False, "MEDIUM", {"direction": direction})
        return LocalActionResponse(False, None, "blocked", "I blocked this automation action for safety.", False, "BLOCKED", error="blocked_by_policy")

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
