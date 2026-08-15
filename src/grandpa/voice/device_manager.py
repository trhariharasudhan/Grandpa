"""Shared microphone discovery, selection, and recovery policy."""

from __future__ import annotations

import importlib
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

import tomllib

from grandpa.voice.errors import MicrophoneUnavailableError, VoiceDependencyError

PHYSICAL_DEVICE_HINTS = ("microphone array", "realtek microphone", "microphone")
VIRTUAL_DEVICE_HINTS = (
    "primary sound capture",
    "sound mapper",
    "stereo mix",
    "virtual",
    "voicemeeter",
)


@dataclass(frozen=True)
class MicrophoneDevice:
    """Normalized input-device metadata."""

    index: int
    name: str
    input_channels: int
    default_sample_rate: int
    host_api: int | None = None
    driver: str = ""
    low_input_latency: float | None = None
    high_input_latency: float | None = None
    is_default: bool = False
    is_default_communications: bool | None = None
    is_virtual: bool = False
    transport: str = "unknown"

    def to_sounddevice_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "max_input_channels": self.input_channels,
            "default_samplerate": self.default_sample_rate,
            "hostapi": self.host_api,
            "default_low_input_latency": self.low_input_latency,
            "default_high_input_latency": self.high_input_latency,
        }


@dataclass(frozen=True)
class MicrophoneIdentity:
    """Stable microphone metadata persisted independently of PortAudio indexes."""

    name: str
    host_api: str = ""
    input_channels: int | None = None
    default_sample_rate: int | None = None

    @classmethod
    def from_device(cls, device: MicrophoneDevice) -> MicrophoneIdentity:
        return cls(
            name=device.name,
            host_api=device.driver,
            input_channels=device.input_channels,
            default_sample_rate=device.default_sample_rate,
        )


@dataclass(frozen=True)
class MicrophoneSelection:
    """A selected microphone and any truthful fallback warning."""

    device: MicrophoneDevice
    requested_index: int | None = None
    requested_name: str | None = None
    warning: str | None = None


class MicrophoneDeviceManager:
    """Own microphone selection and bounded recovery for one voice session."""

    def __init__(
        self,
        sounddevice: Any,
        *,
        preference_loader: Callable[[], MicrophoneIdentity | str | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.sounddevice = sounddevice
        self.preference_loader = preference_loader or load_preferred_microphone_identity
        self.clock = clock
        self._failed_indexes: set[int] = set()
        self._recent_errors: list[str] = []
        self._last_refresh_at: float | None = None

    @property
    def recent_errors(self) -> tuple[str, ...]:
        return tuple(self._recent_errors[-10:])

    def enumerate(self) -> tuple[MicrophoneDevice, ...]:
        try:
            raw_devices = list(self.sounddevice.query_devices())
        except Exception as exc:
            self._record_error(
                f"Device enumeration failed: {type(exc).__name__}: {exc}"
            )
            return ()
        default_index = _default_input_device(self.sounddevice)
        host_apis = _host_apis(self.sounddevice)
        devices: list[MicrophoneDevice] = []
        for index, raw in enumerate(raw_devices):
            info = _device_dict(raw)
            channels = _as_int(info.get("max_input_channels"), 0)
            if channels <= 0:
                continue
            name = str(info.get("name") or f"Input device {index}")
            host_api_index = _optional_int(info.get("hostapi"))
            driver = ""
            if host_api_index is not None and 0 <= host_api_index < len(host_apis):
                driver = str(host_apis[host_api_index].get("name") or "")
            devices.append(
                MicrophoneDevice(
                    index=index,
                    name=name,
                    input_channels=channels,
                    default_sample_rate=_as_int(info.get("default_samplerate"), 16_000),
                    host_api=host_api_index,
                    driver=driver,
                    low_input_latency=_optional_float(
                        info.get("default_low_input_latency")
                    ),
                    high_input_latency=_optional_float(
                        info.get("default_high_input_latency")
                    ),
                    is_default=index == default_index,
                    # PortAudio does not expose the Windows communications role.
                    is_default_communications=None,
                    is_virtual=_contains_hint(name, VIRTUAL_DEVICE_HINTS),
                    transport=_transport(name),
                )
            )
        self._last_refresh_at = self.clock()
        return tuple(devices)

    def select(
        self,
        *,
        requested_index: int | None = None,
        requested_name: str | None = None,
        allow_fallback: bool = True,
    ) -> MicrophoneSelection:
        devices = self.enumerate()
        if requested_index is not None:
            if requested_index < 0:
                raise self._selection_error(
                    f"Invalid microphone device index: {requested_index}", devices
                )
            match = next(
                (item for item in devices if item.index == requested_index), None
            )
            if match is None:
                raw = self._raw_device(requested_index)
                if raw is not None and _as_int(raw.get("max_input_channels"), 0) <= 0:
                    raise self._selection_error(
                        f"Microphone device {requested_index} has no input channels.",
                        devices,
                    )
                raise self._selection_error(
                    f"Microphone device {requested_index} was not found.", devices
                )
            return MicrophoneSelection(match, requested_index=requested_index)

        preference = self.preference_loader()
        identity = _coerce_identity(preference)
        clean_name = (requested_name or "").strip() or (
            identity.name if identity is not None else ""
        )
        warning = None
        if clean_name:
            match = _find_by_identity(
                devices,
                MicrophoneIdentity(name=clean_name)
                if requested_name
                else identity or MicrophoneIdentity(name=clean_name),
            )
            if match is not None and match.index not in self._failed_indexes:
                return MicrophoneSelection(match, requested_name=clean_name)
            if requested_name and not allow_fallback:
                raise self._selection_error(
                    f"Microphone named '{requested_name}' was not found.", devices
                )
            warning = f"Configured microphone '{clean_name}' was not found."

        candidates = [
            item for item in devices if item.index not in self._failed_indexes
        ]
        selected = _best_device(candidates)
        if selected is None and self._failed_indexes:
            self._failed_indexes.clear()
            selected = _best_device(list(devices))
        if selected is None:
            raise self._selection_error("No usable microphone was detected.", devices)
        if warning:
            warning = f"{warning} Using {selected.name}."
        return MicrophoneSelection(
            selected,
            requested_name=clean_name,
            warning=warning,
        )

    def mark_failed(self, device: MicrophoneDevice, exc: BaseException) -> None:
        self._failed_indexes.add(device.index)
        self._record_error(
            f"{device.name} (device {device.index}) failed: {type(exc).__name__}: {exc}"
        )

    def recover(
        self, failed_device: MicrophoneDevice, exc: BaseException
    ) -> MicrophoneSelection:
        """Re-enumerate devices and select a replacement after a capture failure."""

        self.mark_failed(failed_device, exc)
        selection = self.select(allow_fallback=True)
        warning = (
            f"Microphone disconnected or became unavailable. "
            f"Switched from {failed_device.name} to {selection.device.name}."
        )
        return MicrophoneSelection(selection.device, warning=warning)

    def _record_error(self, message: str) -> None:
        self._recent_errors.append(message)
        del self._recent_errors[:-10]

    def _raw_device(self, index: int) -> dict[str, Any] | None:
        try:
            devices = list(self.sounddevice.query_devices())
        except Exception:
            return None
        if 0 <= index < len(devices):
            return _device_dict(devices[index])
        return None

    def replacement_for_stale_index(self, index: int) -> MicrophoneDevice | None:
        """Find the current input endpoint corresponding to an old index."""

        devices = self.enumerate()
        raw = self._raw_device(index)
        raw_name = str((raw or {}).get("name") or "").strip()
        if raw_name:
            match = _find_by_identity(devices, MicrophoneIdentity(name=raw_name))
            if match is not None:
                return match
        identity = _coerce_identity(self.preference_loader())
        return _find_by_identity(devices, identity) if identity is not None else None

    @staticmethod
    def _selection_error(
        message: str, devices: tuple[MicrophoneDevice, ...]
    ) -> MicrophoneUnavailableError:
        available = "\n".join(
            f"- {item.index}: {item.name} ({item.input_channels} input channel(s))"
            for item in devices
        )
        detail = f"{message}\nAvailable input devices:\n{available or '- none'}"
        return MicrophoneUnavailableError(detail, detail=detail)


def load_preferred_microphone_identity() -> MicrophoneIdentity | None:
    """Load persisted stable metadata without requiring the full config model."""

    try:
        from grandpa.core import config as core_config

        path = core_config.DEFAULT_CONFIG_PATH
        if not path.exists():
            return None
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        voice = data.get("voice") if isinstance(data, dict) else None
        if not isinstance(voice, dict):
            return None
        name = str(voice.get("preferred_microphone") or "").strip()
        if not name:
            return None
        return MicrophoneIdentity(
            name=name,
            host_api=str(voice.get("preferred_microphone_host_api") or "").strip(),
            input_channels=_optional_int(
                voice.get("preferred_microphone_input_channels")
            ),
            default_sample_rate=_optional_int(
                voice.get("preferred_microphone_sample_rate")
            ),
        )

    except Exception:
        return None


def load_preferred_microphone_name() -> str | None:
    """Backward-compatible preferred microphone name accessor."""

    identity = load_preferred_microphone_identity()
    return identity.name if identity is not None else None


def import_sounddevice() -> Any:
    """Import PortAudio support with stable user-facing errors."""

    try:
        return importlib.import_module("sounddevice")
    except ModuleNotFoundError as exc:
        if exc.name == "sounddevice":
            raise VoiceDependencyError(
                "The optional package `sounddevice` is not installed.\n"
                "Install voice support with:\nuv sync --extra voice",
                detail=str(exc),
            ) from exc
        raise VoiceDependencyError(
            "The `sounddevice` package could not initialize.",
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
    except (ImportError, OSError) as exc:
        raise VoiceDependencyError(
            "The `sounddevice` package is installed but could not initialize.",
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc


def _best_device(devices: list[MicrophoneDevice]) -> MicrophoneDevice | None:
    if not devices:
        return None
    default = next((item for item in devices if item.is_default), None)
    if default is not None and not default.is_virtual:
        return default
    physical = [item for item in devices if not item.is_virtual]
    for hint in PHYSICAL_DEVICE_HINTS:
        matches = [
            item for item in physical if hint in normalize_device_name(item.name)
        ]
        if matches:
            return max(
                matches,
                key=lambda item: (
                    "wasapi" in normalize_device_name(item.driver),
                    item.input_channels > 0,
                ),
            )
    return physical[0] if physical else (default or devices[0])


def _find_by_identity(
    devices: tuple[MicrophoneDevice, ...], identity: MicrophoneIdentity
) -> MicrophoneDevice | None:
    normalized = normalize_device_name(identity.name)
    matches = [
        item
        for item in devices
        if normalize_device_name(item.name) == normalized
        or normalized in normalize_device_name(item.name)
    ]
    if not matches:
        return None
    requested_api = normalize_device_name(identity.host_api)
    return max(
        matches,
        key=lambda item: (
            bool(requested_api and normalize_device_name(item.driver) == requested_api),
            item.input_channels > 0,
            item.is_default,
            "wasapi" in normalize_device_name(item.driver),
            not item.is_virtual,
        ),
    )


def _coerce_identity(
    value: MicrophoneIdentity | str | None,
) -> MicrophoneIdentity | None:
    if isinstance(value, MicrophoneIdentity):
        return value
    name = str(value or "").strip()
    return MicrophoneIdentity(name=name) if name else None


def normalize_device_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _default_input_device(sounddevice: Any) -> int | None:
    try:
        default = sounddevice.default.device
        value = default[0] if isinstance(default, (list, tuple)) else default
        value = int(value)
        return value if value >= 0 else None
    except Exception:
        return None


def _host_apis(sounddevice: Any) -> list[dict[str, Any]]:
    try:
        return [_device_dict(item) for item in sounddevice.query_hostapis()]
    except Exception:
        return []


def _device_dict(device: Any) -> dict[str, Any]:
    if isinstance(device, dict):
        return device
    try:
        return dict(device)
    except Exception:
        return {
            "name": getattr(device, "name", "Input device"),
            "max_input_channels": getattr(device, "max_input_channels", 0),
        }


def _contains_hint(name: str, hints: tuple[str, ...]) -> bool:
    normalized = normalize_device_name(name)
    return any(hint in normalized for hint in hints)


def _transport(name: str) -> str:
    normalized = normalize_device_name(name)
    if (
        "bluetooth" in normalized
        or "hands-free" in normalized
        or "headset" in normalized
    ):
        return "bluetooth"
    if "usb" in normalized:
        return "usb"
    if _contains_hint(name, VIRTUAL_DEVICE_HINTS):
        return "virtual"
    return "built-in"


def _as_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "MicrophoneDevice",
    "MicrophoneIdentity",
    "MicrophoneDeviceManager",
    "MicrophoneSelection",
    "import_sounddevice",
    "load_preferred_microphone_identity",
    "load_preferred_microphone_name",
    "normalize_device_name",
]
