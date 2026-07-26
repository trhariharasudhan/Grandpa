"""Volume, brightness, and power action service for PC control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PowerControlService:
    """System power and hardware controls behind facade approval checks."""

    name: str = "power"

    def execute_volume(self, request: Any, action: str, *, platform: str):
        from grandpa.pc_control import LocalActionResponse

        if platform != "win32":
            return LocalActionResponse(False, None, "unsupported", "Volume control is only supported on Windows desktop.", False, "LOW", error="unsupported")
        key = {
            "volume_up": "volumeup",
            "volume_down": "volumedown",
            "volume_mute": "volumemute",
            "volume_unmute": "volumemute",
        }.get(action)
        if action == "volume_set":
            return self._execute_volume_set(request, platform=platform)
        import pyautogui  # type: ignore

        pyautogui.press(key)
        label = action.replace("volume_", "volume ").replace("_", " ")
        return LocalActionResponse(True, None, "completed", f"Adjusted {label}.", False, "LOW", {"key": key})

    def _execute_volume_set(self, request: Any, *, platform: str):
        from grandpa.pc_control import LocalActionResponse

        if platform != "win32":
            return LocalActionResponse(False, None, "unsupported", "Volume control is only supported on Windows desktop.", False, "LOW", error="unsupported")
        level = max(0, min(100, int(request.args.get("level", request.target or 0))))
        try:
            from comtypes import CLSCTX_ALL  # type: ignore
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            volume.SetMasterVolumeLevelScalar(level / 100, None)
        except Exception:
            return LocalActionResponse(
                False,
                None,
                "unsupported",
                "Volume percentage control requires the optional pycaw Windows audio backend.",
                False,
                "LOW",
                {"level": level},
                error="missing_volume_backend",
            )
        return LocalActionResponse(True, None, "completed", f"Volume set to {level}%.", False, "LOW", {"level": level})

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

    def execute_empty_recycle_bin(self, *, platform: str):
        from grandpa.pc_control import LocalActionResponse

        if platform != "win32":
            return LocalActionResponse(False, None, "unsupported", "Recycle Bin cleanup is only supported on Windows desktop.", False, "HIGH", error="unsupported")
        import ctypes

        flags = 0x00000001 | 0x00000002 | 0x00000004
        result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
        if result != 0:
            return LocalActionResponse(False, None, "failed", "Recycle Bin could not be emptied.", False, "HIGH", {"win32_result": result}, error="recycle_bin_failed")
        return LocalActionResponse(True, None, "completed", "Recycle Bin emptied.", False, "HIGH", {"recycle_bin": "emptied"})

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
                "volume_set": "LOW",
                "brightness_get": "LOW",
                "brightness_set": "LOW",
                "system_sleep": "HIGH",
                "system_restart": "HIGH",
                "system_shutdown": "HIGH",
                "system_lock": "HIGH",
                "empty_recycle_bin": "HIGH",
            },
            "dependencies": {"platform": platform, "pyautogui": pyautogui_available, "screen_brightness_control": brightness_available},
            "safety": {"power_actions_require_approval": True},
        }


__all__ = ["PowerControlService"]
