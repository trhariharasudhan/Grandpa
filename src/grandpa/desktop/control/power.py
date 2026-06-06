"""Volume, brightness, and power action service for PC control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PowerControlService:
    """System power and hardware controls behind facade approval checks."""

    name: str = "power"

    def execute_volume(self, action: str, *, platform: str):
        from grandpa.pc_control import LocalActionResponse

        if platform != "win32":
            return LocalActionResponse(False, None, "unsupported", "Volume control is only supported on Windows desktop.", False, "LOW", error="unsupported")
        key = {
            "volume_up": "volumeup",
            "volume_down": "volumedown",
            "volume_mute": "volumemute",
            "volume_unmute": "volumemute",
        }[action]
        import pyautogui  # type: ignore

        pyautogui.press(key)
        label = action.replace("volume_", "volume ").replace("_", " ")
        return LocalActionResponse(True, None, "completed", f"Adjusted {label}.", False, "LOW", {"key": key})

    def execute_brightness(self, request: Any, action: str):
        from grandpa.pc_control import LocalActionResponse

        try:
            import screen_brightness_control as sbc  # type: ignore
        except Exception:
            return LocalActionResponse(False, None, "unsupported", "Brightness control is not supported on this system.", False, "LOW", error="unsupported")
        if action == "brightness_get":
            value = sbc.get_brightness()
            return LocalActionResponse(True, None, "completed", "Brightness read.", False, "LOW", {"brightness": value})
        value = int(request.args.get("level", request.target or 0))
        sbc.set_brightness(max(0, min(100, value)))
        return LocalActionResponse(True, None, "completed", f"Brightness set to {value}%.", False, "LOW", {"brightness": value})

    def execute_system(self, action: str, *, platform: str):
        from grandpa.pc_control import LocalActionResponse

        if platform != "win32":
            return LocalActionResponse(False, None, "unsupported", "Power control is only supported on Windows desktop.", False, "HIGH", error="unsupported")
        if action == "system_lock":
            import ctypes

            ctypes.windll.user32.LockWorkStation()
            return LocalActionResponse(True, None, "completed", "Locked the screen.", False, "HIGH", {"system_action": "lock"})
        command = {
            "system_sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            "system_restart": ["shutdown", "/r", "/t", "0"],
            "system_shutdown": ["shutdown", "/s", "/t", "0"],
        }[action]
        import subprocess

        subprocess.Popen(command)
        return LocalActionResponse(True, None, "completed", "Started the requested power action.", False, "HIGH", {"system_action": action})

    def diagnostics(self, *, platform: str) -> dict[str, Any]:
        try:
            import pyautogui  # noqa: F401

            pyautogui_available = True
        except Exception:
            pyautogui_available = False
        try:
            import screen_brightness_control  # noqa: F401

            brightness_available = True
        except Exception:
            brightness_available = False
        return {
            "service": self.name,
            "ready": True,
            "risk_levels": {
                "volume_up": "LOW",
                "volume_down": "LOW",
                "volume_mute": "LOW",
                "volume_unmute": "LOW",
                "brightness_get": "LOW",
                "brightness_set": "LOW",
                "system_sleep": "HIGH",
                "system_restart": "HIGH",
                "system_shutdown": "HIGH",
                "system_lock": "HIGH",
            },
            "dependencies": {"platform": platform, "pyautogui": pyautogui_available, "screen_brightness_control": brightness_available},
            "safety": {"power_actions_require_approval": True},
        }


__all__ = ["PowerControlService"]
