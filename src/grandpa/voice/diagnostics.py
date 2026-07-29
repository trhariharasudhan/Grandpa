"""Microphone diagnostics for Grandpa voice mode."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import shutil
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.jarvis.voice_input import (
    SoundDeviceMicrophoneRecorder,
)
from grandpa.voice.device_manager import MicrophoneDeviceManager
from grandpa.voice.errors import (
    MicrophoneUnavailableError,
    VoiceDependencyError,
)
from grandpa.voice.speech_input import SpeechInputEngine
from grandpa.voice.speech_output import SpeechOutputEngine

logger = logging.getLogger(__name__)

VOICE_PACKAGES = (
    ("sounddevice", True),
    ("faster_whisper", True),
    ("numpy", True),
    ("pyttsx3", False),
)


@dataclass(frozen=True)
class VoiceDeviceInfo:
    index: int
    name: str
    input_channels: int
    default: bool = False
    default_communications: bool | None = None
    sample_rate: int = 16_000
    driver: str = ""
    transport: str = "unknown"
    virtual: bool = False
    low_input_latency: float | None = None
    high_input_latency: float | None = None


@dataclass(frozen=True)
class VoiceDependencyCheck:
    module: str
    status: str
    required: bool
    detail: str = ""


@dataclass(frozen=True)
class VoiceDependencyStatus:
    checks: tuple[VoiceDependencyCheck, ...]

    @property
    def missing_required(self) -> tuple[str, ...]:
        return tuple(
            check.module
            for check in self.checks
            if check.required and check.status == "missing"
        )

    @property
    def initialization_errors(self) -> tuple[VoiceDependencyCheck, ...]:
        return tuple(check for check in self.checks if check.status == "error")


def check_voice_dependencies() -> VoiceDependencyStatus:
    """Import voice packages independently without misclassifying internal failures."""

    checks: list[VoiceDependencyCheck] = []
    for module_name, required in VOICE_PACKAGES:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            status = "missing" if exc.name == module_name else "error"
            checks.append(
                VoiceDependencyCheck(
                    module_name, status, required, f"{type(exc).__name__}: {exc}"
                )
            )
        except Exception as exc:
            checks.append(
                VoiceDependencyCheck(
                    module_name, "error", required, f"{type(exc).__name__}: {exc}"
                )
            )
        else:
            checks.append(VoiceDependencyCheck(module_name, "installed", required))
    return VoiceDependencyStatus(tuple(checks))


def voice_runtime_diagnostics() -> dict[str, Any]:
    """Return active interpreter and local-development environment facts."""

    project_root = Path(__file__).resolve().parents[3]
    expected_venv = project_root / ".venv"
    active_venv = Path(os.environ.get("VIRTUAL_ENV") or sys.prefix)
    executable = Path(sys.executable).resolve()
    try:
        in_project_venv = executable.is_relative_to(expected_venv.resolve())
    except (OSError, ValueError):
        in_project_venv = False
    return {
        "python_executable": str(executable),
        "virtual_environment": str(active_venv),
        "grandpa_executable": shutil.which("grandpa") or sys.argv[0],
        "project_root": str(project_root),
        "expected_virtual_environment": str(expected_venv),
        "in_project_virtual_environment": in_project_venv,
        "environment_processes": _environment_processes(expected_venv),
    }


def voice_diagnostic_log_path() -> Path:
    from grandpa.core.config import DEFAULT_CONFIG_DIR

    return DEFAULT_CONFIG_DIR / "voice.log"


def log_voice_initialization_error(exc: BaseException) -> Path:
    """Write original initialization traceback without exposing it in normal UI."""

    path = voice_diagnostic_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        runtime = voice_runtime_diagnostics()
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\nVoice initialization failure\n")
            handle.write(f"Python: {runtime['python_executable']}\n")
            handle.write(f"Virtual environment: {runtime['virtual_environment']}\n")
            handle.write(f"Exception: {type(exc).__name__}: {exc}\n")
            handle.write(
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            )
    except OSError:
        logger.debug("Could not write voice diagnostic log", exc_info=True)
    return path


def list_input_devices() -> tuple[VoiceDeviceInfo, ...]:
    sounddevice = _import_sounddevice()
    manager = MicrophoneDeviceManager(sounddevice)
    return tuple(
        VoiceDeviceInfo(
            index=device.index,
            name=device.name,
            input_channels=device.input_channels,
            default=device.is_default,
            default_communications=device.is_default_communications,
            sample_rate=device.default_sample_rate,
            driver=device.driver,
            transport=device.transport,
            virtual=device.is_virtual,
            low_input_latency=device.low_input_latency,
            high_input_latency=device.high_input_latency,
        )
        for device in manager.enumerate()
    )


def run_voice_doctor(
    *, duration_seconds: float = 2.0, device: int | None = None
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    runtime = voice_runtime_diagnostics()
    checks.extend(
        [
            _check("Python executable", "pass", runtime["python_executable"]),
            _check(
                "Virtual environment",
                "pass" if runtime["in_project_virtual_environment"] else "warn",
                runtime["virtual_environment"],
            ),
            _check("Grandpa executable", "pass", runtime["grandpa_executable"]),
        ]
    )
    environment_processes = runtime["environment_processes"]
    if environment_processes:
        process_summary = ", ".join(
            f"{process['name']} (PID {process['pid']})"
            for process in environment_processes[:8]
        )
        checks.append(
            _check(
                "Environment file-lock risk",
                "warn",
                f"Processes are using the project environment: {process_summary}. "
                "Stop them before `uv sync` if Windows reports Access is denied for a native .pyd file.",
            )
        )
    else:
        checks.append(
            _check(
                "Environment file-lock risk",
                "pass",
                "No other project-environment processes detected.",
            )
        )
    for dependency in check_voice_dependencies().checks:
        status = "pass" if dependency.status == "installed" else "warn"
        detail = "Installed." if dependency.status == "installed" else dependency.detail
        checks.append(_check(f"{dependency.module} status", status, detail))
    try:
        sounddevice = _import_sounddevice()
        checks.append(_check("sounddevice import", "pass", "sounddevice is installed."))
    except VoiceDependencyError as exc:
        checks.append(_check("sounddevice import", "warn", str(exc)))
        checks.extend(_stt_checks())
        checks.extend(_tts_checks())
        checks.append(
            _check("Windows microphone permission", "warn", _windows_permission_hint())
        )
        return checks

    try:
        devices = list_input_devices()
        if devices:
            checks.append(
                _check(
                    "input devices", "pass", f"{len(devices)} input device(s) found."
                )
            )
        else:
            checks.append(
                _check(
                    "input devices",
                    "warn",
                    "No input devices were reported by sounddevice.",
                )
            )
    except Exception as exc:
        checks.append(
            _check("input devices", "warn", f"Could not list input devices: {exc}")
        )
        devices = ()

    default_index = _default_input_device(sounddevice)
    try:
        manager = MicrophoneDeviceManager(sounddevice)
        selection = manager.select(requested_index=device)
    except MicrophoneUnavailableError as exc:
        selection = None
        checks.append(_check("selected input device", "warn", str(exc)))
    else:
        selected = selection.device
        details = (
            f"{selected.index}: {selected.name}; channels={selected.input_channels}; "
            f"sample_rate={selected.default_sample_rate}; driver={selected.driver or 'unknown'}; "
            f"transport={selected.transport}; low_latency={selected.low_input_latency}"
        )
        checks.append(_check("selected input device", "pass", details))
        if selection.warning:
            checks.append(_check("microphone fallback", "warn", selection.warning))
    checks.append(
        _check(
            "default input device",
            "pass" if default_index is not None or selection is not None else "warn",
            (
                str(default_index)
                if default_index is not None
                else "No default index reported; Grandpa selected a usable input device."
                if selection is not None
                else "No default input device reported."
            ),
        )
    )
    checks.append(
        _check("sample rate", "pass", "Using 16000 Hz for push-to-talk capture.")
    )

    if devices and duration_seconds > 0:
        try:
            recorder = SoundDeviceMicrophoneRecorder(
                duration_seconds=duration_seconds, device=device
            )
            recorder.record_wav()
            status = "pass" if recorder.last_rms >= 250 else "warn"
            message = (
                f"Recorded {duration_seconds:g}s. RMS level: {recorder.last_rms:.1f}."
            )
            if status == "warn":
                message += (
                    " I did not hear much audio; check microphone or speak louder."
                )
            checks.append(_check("record test", status, message))
            diagnostics = recorder.last_diagnostics
            if diagnostics is not None:
                checks.append(
                    _check(
                        "captured frames",
                        "pass",
                        (
                            f"device={diagnostics.selected_device_id} "
                            f"name={diagnostics.device_name}; "
                            f"channels={diagnostics.channels}; "
                            f"sample_rate={diagnostics.sample_rate}; "
                            f"frames={diagnostics.captured_frame_count}"
                        ),
                    )
                )
        except MicrophoneUnavailableError as exc:
            checks.append(_check("record test", "warn", str(exc)))

    checks.extend(_stt_checks())
    checks.extend(_tts_checks())
    checks.append(
        _check("Windows microphone permission", "pass", _windows_permission_hint())
    )
    return checks


def _stt_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    faster_whisper = importlib.util.find_spec("faster_whisper") is not None
    checks.append(
        _check(
            "faster-whisper import",
            "pass" if faster_whisper else "warn",
            "Installed."
            if faster_whisper
            else "Install with: uv sync --extra voice or uv sync --extra speech",
        )
    )
    status = SpeechInputEngine().stt_status()
    checks.append(
        _check(
            "STT backend",
            "pass" if status.get("ready") else "warn",
            f"{status.get('engine')} model={status.get('model')} compute={status.get('compute_type')}",
        )
    )
    if faster_whisper:
        checks.append(
            _check(
                "model availability",
                "warn",
                "First transcription may download/load the configured Whisper model.",
            )
        )
    return checks


def _tts_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    engine = SpeechOutputEngine()
    info = engine.diagnostics()
    ready = info.get("status") == "ready"
    backend = str(info.get("engine") or "print_only")
    voice = str(info.get("voice") or "default")
    checks.append(
        _check(
            "TTS backend",
            "pass" if ready else "warn",
            f"{backend} available."
            if ready
            else "No audible TTS backend found; print-only fallback will be used.",
        )
    )
    checks.append(_check("TTS selected voice", "pass" if ready else "warn", voice))
    try:
        result = engine.speak("Hello, I am Grandpa.", interrupt=True, dry_run=True)
        checks.append(
            _check(
                "TTS speech test",
                "pass" if result.status in {"dry_run", "completed"} else "warn",
                result.message,
            )
        )
    except Exception as exc:
        checks.append(_check("TTS speech test", "warn", str(exc)))
    return checks


def _import_sounddevice():
    try:
        import sounddevice  # type: ignore
    except ModuleNotFoundError as exc:
        if exc.name == "sounddevice":
            raise VoiceDependencyError(
                "The optional package `sounddevice` is not installed.\nInstall voice support with:\nuv sync --extra voice",
                detail=str(exc),
            ) from exc
        raise VoiceDependencyError(
            "The `sounddevice` package could not initialize because one of its dependencies is unavailable.",
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
    except ImportError as exc:
        raise VoiceDependencyError(
            "The `sounddevice` package is installed but could not initialize.",
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
    return sounddevice


def _environment_processes(expected_venv: Path) -> list[dict[str, Any]]:
    try:
        import psutil
    except ImportError:
        return []
    root = os.path.normcase(str(expected_venv.resolve()))
    current_process = psutil.Process(os.getpid())
    ignored_pids = {os.getpid(), *(parent.pid for parent in current_process.parents())}
    matches: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            if process.info["pid"] in ignored_pids:
                continue
            values = [
                str(process.info.get("exe") or ""),
                *(process.info.get("cmdline") or []),
            ]
            if any(
                os.path.normcase(value).startswith(root) for value in values if value
            ):
                matches.append(
                    {
                        "pid": process.info["pid"],
                        "name": process.info.get("name") or "python",
                    }
                )
        except (psutil.Error, OSError, ValueError):
            continue
    return matches[:25]


def _default_input_device(sounddevice) -> int | None:
    try:
        default = sounddevice.default.device
        if isinstance(default, (list, tuple)):
            value = default[0]
        else:
            value = default
        return int(value) if value is not None and int(value) >= 0 else None
    except Exception:
        return None


def _windows_permission_hint() -> str:
    return "On Windows, check Settings > Privacy & security > Microphone and allow desktop apps to access the microphone."


def _check(name: str, status: str, message: str) -> dict[str, Any]:
    return {"name": name, "status": status, "message": message}


__all__ = [
    "VoiceDependencyCheck",
    "VoiceDependencyStatus",
    "VoiceDeviceInfo",
    "check_voice_dependencies",
    "list_input_devices",
    "log_voice_initialization_error",
    "run_voice_doctor",
    "voice_diagnostic_log_path",
    "voice_runtime_diagnostics",
]
