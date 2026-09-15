"""Volume, brightness, and power action service for PC control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class VolumeBackendError(RuntimeError):
    """The audio endpoint could not be reached, and why."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _endpoint_volume():
    """Return the Core Audio endpoint-volume interface for the default speakers.

    pycaw changed shape: ``AudioUtilities.GetSpeakers()`` used to hand back a
    raw ``IMMDevice`` you called ``.Activate`` on, and now returns an
    ``AudioDevice`` wrapper that exposes ``.EndpointVolume`` directly and keeps
    the raw device at ``._dev``. The old call raised
    ``AttributeError: 'AudioDevice' object has no attribute 'Activate'``, which
    the callers swallowed into "the optional pycaw backend is missing" -- so
    with pycaw installed and working, volume control still reported itself as
    unavailable. Both shapes are handled here, once.
    """
    try:
        from pycaw.pycaw import AudioUtilities  # type: ignore
    except ImportError as exc:
        raise VolumeBackendError(
            "Volume control needs the optional pycaw Windows audio backend "
            "(install the 'desktop-hardware' extra).",
            code="missing_volume_backend",
        ) from exc

    try:
        speakers = AudioUtilities.GetSpeakers()
        endpoint = getattr(speakers, "EndpointVolume", None)
        if endpoint is not None:
            return endpoint
        # pycaw older than the AudioDevice wrapper.
        from comtypes import CLSCTX_ALL  # type: ignore
        from pycaw.pycaw import IAudioEndpointVolume  # type: ignore

        device = getattr(speakers, "_dev", speakers)
        interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return interface.QueryInterface(IAudioEndpointVolume)
    except Exception as exc:
        # Not "the backend is missing" -- it is here and it failed. Say which.
        raise VolumeBackendError(
            f"The Windows audio endpoint could not be opened: "
            f"{type(exc).__name__}: {exc}",
            code="volume_backend_failed",
        ) from exc


@dataclass(frozen=True)
class PowerControlService:
    """System power and hardware controls behind facade approval checks."""

    name: str = "power"

    def execute_volume(self, request: Any, action: str, *, platform: str):
        from grandpa.pc_control import LocalActionResponse

        if platform != "win32":
            return LocalActionResponse(
                False,
                None,
                "unsupported",
                "Volume control is only supported on Windows desktop.",
                False,
                "LOW",
                error="unsupported",
            )
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
        return LocalActionResponse(
            True, None, "completed", f"Adjusted {label}.", False, "LOW", {"key": key}
        )

    def _execute_volume_set(self, request: Any, *, platform: str):
        from grandpa.pc_control import LocalActionResponse

        if platform != "win32":
            return LocalActionResponse(
                False,
                None,
                "unsupported",
                "Volume control is only supported on Windows desktop.",
                False,
                "LOW",
                error="unsupported",
            )
        level = max(0, min(100, int(request.args.get("level", request.target or 0))))
        try:
            _endpoint_volume().SetMasterVolumeLevelScalar(level / 100, None)
        except VolumeBackendError as exc:
            return LocalActionResponse(
                False,
                None,
                "unsupported",
                str(exc),
                False,
                "LOW",
                {"level": level},
                error=exc.code,
            )
        return LocalActionResponse(
            True,
            None,
            "completed",
            f"Volume set to {level}%.",
            False,
            "LOW",
            {"level": level},
        )

    def execute_volume_get(self, *, platform: str):
        """Read the current volume, so it can be reported instead of guessed.

        The mirror of ``_execute_volume_set``, through the same endpoint: there
        was a setter and no getter, which is why anything asking "what is my
        volume set to" could only be answered by inventing a number.
        """
        from grandpa.pc_control import LocalActionResponse

        if platform != "win32":
            return LocalActionResponse(
                False,
                None,
                "unsupported",
                "Volume control is only supported on Windows desktop.",
                False,
                "LOW",
                error="unsupported",
            )
        try:
            endpoint = _endpoint_volume()
            level = int(round(endpoint.GetMasterVolumeLevelScalar() * 100))
            muted = bool(endpoint.GetMute())
        except VolumeBackendError as exc:
            return LocalActionResponse(
                False,
                None,
                "unsupported",
                str(exc),
                False,
                "LOW",
                error=exc.code,
            )
        state = f"Volume is {level}%" + (" and muted." if muted else ".")
        return LocalActionResponse(
            True,
            None,
            "completed",
            state,
            False,
            "LOW",
            {"level": level, "muted": muted},
        )

    def execute_brightness(self, request: Any, action: str):
        from grandpa.pc_control import LocalActionResponse

        try:
            import screen_brightness_control as sbc  # type: ignore
        except Exception:
            return LocalActionResponse(
                False,
                None,
                "unsupported",
                "Brightness control is not supported on this system.",
                False,
                "LOW",
                error="unsupported",
            )
        if action == "brightness_get":
            value = sbc.get_brightness()
            # sbc returns one reading per display. Put the number in the
            # sentence too: "Brightness read." told a model nothing it could
            # repeat back, which is how a read action ends up being guessed at.
            levels = value if isinstance(value, (list, tuple)) else [value]
            if len(levels) == 1:
                summary = f"Brightness is {levels[0]}%."
            else:
                summary = "Brightness per display: " + ", ".join(
                    f"{index}: {level}%" for index, level in enumerate(levels)
                )
            return LocalActionResponse(
                True,
                None,
                "completed",
                summary,
                False,
                "LOW",
                {"brightness": value},
            )
        value = int(request.args.get("level", request.target or 0))
        sbc.set_brightness(max(0, min(100, value)))
        return LocalActionResponse(
            True,
            None,
            "completed",
            f"Brightness set to {value}%.",
            False,
            "LOW",
            {"brightness": value},
        )

    def execute_system(self, action: str, *, platform: str):
        from grandpa.pc_control import LocalActionResponse

        if platform != "win32":
            return LocalActionResponse(
                False,
                None,
                "unsupported",
                "Power control is only supported on Windows desktop.",
                False,
                "HIGH",
                error="unsupported",
            )
        if action == "system_lock":
            import ctypes

            ctypes.windll.user32.LockWorkStation()
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Locked the screen.",
                False,
                "HIGH",
                {"system_action": "lock"},
            )
        command = {
            "system_sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            "system_restart": ["shutdown", "/r", "/t", "0"],
            "system_shutdown": ["shutdown", "/s", "/t", "0"],
        }[action]
        import subprocess

        subprocess.Popen(command)
        return LocalActionResponse(
            True,
            None,
            "completed",
            "Started the requested power action.",
            False,
            "HIGH",
            {"system_action": action},
        )

    def execute_empty_recycle_bin(self, *, platform: str):
        from grandpa.pc_control import LocalActionResponse

        if platform != "win32":
            return LocalActionResponse(
                False,
                None,
                "unsupported",
                "Recycle Bin cleanup is only supported on Windows desktop.",
                False,
                "HIGH",
                error="unsupported",
            )
        import ctypes

        flags = 0x00000001 | 0x00000002 | 0x00000004
        result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
        if result != 0:
            return LocalActionResponse(
                False,
                None,
                "failed",
                "Recycle Bin could not be emptied.",
                False,
                "HIGH",
                {"win32_result": result},
                error="recycle_bin_failed",
            )
        return LocalActionResponse(
            True,
            None,
            "completed",
            "Recycle Bin emptied.",
            False,
            "HIGH",
            {"recycle_bin": "emptied"},
        )

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
                "volume_get": "LOW",
                "brightness_get": "LOW",
                "brightness_set": "LOW",
                "system_sleep": "HIGH",
                "system_restart": "HIGH",
                "system_shutdown": "HIGH",
                "system_lock": "HIGH",
                "empty_recycle_bin": "HIGH",
            },
            "dependencies": {
                "platform": platform,
                "pyautogui": pyautogui_available,
                "screen_brightness_control": brightness_available,
            },
            "safety": {"power_actions_require_approval": True},
        }


__all__ = ["PowerControlService", "VolumeBackendError"]
