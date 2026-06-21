"""Voice-stack health checks that do not require Tauri or real microphone access."""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class VoiceDoctorCheck:
    name: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


StatusProvider = Callable[[], dict[str, Any]]


def run_voice_doctor(
    *,
    voice_status_provider: StatusProvider | None = None,
    stt_status_provider: StatusProvider | None = None,
    wake_word_status_provider: StatusProvider | None = None,
    loop_status_provider: StatusProvider | None = None,
    conversation_status_provider: StatusProvider | None = None,
    voice_history_provider: Callable[[], list[dict[str, Any]]] | None = None,
    command_provider: StatusProvider | None = None,
) -> dict[str, Any]:
    """Run safe voice checks without microphone capture or desktop execution."""

    checks = [
        _check_server_import(),
        _check_voice_status(voice_status_provider),
        _check_stt_status(stt_status_provider),
        _check_wake_word_status(wake_word_status_provider),
        _check_loop_status(loop_status_provider),
        _check_conversation_status(conversation_status_provider),
        _check_voice_history(voice_history_provider),
        _check_voice_command_logic(command_provider),
        _check_speech_dependencies(),
        _check_ffmpeg_available(),
        _check_local_model_readiness(stt_status_provider),
    ]
    return {
        "ok": not any(check.status == "fail" for check in checks),
        "checks": [check.to_dict() for check in checks],
    }


def _check_server_import() -> VoiceDoctorCheck:
    try:
        from grandpa.server.app import create_app  # noqa: F401

        return VoiceDoctorCheck("server import", "pass", "Server app imports successfully.")
    except Exception as exc:
        return VoiceDoctorCheck("server import", "fail", f"Server import failed: {exc}")


def _runtime() -> Any:
    from grandpa.voice import get_voice_runtime

    return get_voice_runtime()


def _check_voice_status(provider: StatusProvider | None) -> VoiceDoctorCheck:
    try:
        status = provider() if provider else _runtime().status()
        mode = status.get("mode") or status.get("status") or "available"
        return VoiceDoctorCheck("voice status", "pass", f"Voice runtime status available ({mode}).")
    except Exception as exc:
        return VoiceDoctorCheck("voice status", "fail", f"Voice runtime status failed: {exc}")


def _check_stt_status(provider: StatusProvider | None) -> VoiceDoctorCheck:
    try:
        status = provider() if provider else _runtime().speech_input.stt_status()
        engine = status.get("engine", "unknown")
        ready = bool(status.get("ready"))
        state = "ready" if ready else "transcript fallback"
        return VoiceDoctorCheck("stt status", "pass", f"STT status available ({engine}, {state}).")
    except Exception as exc:
        return VoiceDoctorCheck("stt status", "fail", f"STT status failed: {exc}")


def _check_wake_word_status(provider: StatusProvider | None) -> VoiceDoctorCheck:
    try:
        if provider:
            status = provider()
        else:
            from grandpa.voice.wake_word import WakeWordSession

            status = WakeWordSession().status()
        phrase = status.get("wake_phrase", "hey grandpa")
        return VoiceDoctorCheck("wake-word status", "pass", f"Wake-word status available ({phrase}).")
    except Exception as exc:
        return VoiceDoctorCheck("wake-word status", "fail", f"Wake-word status failed: {exc}")


def _check_loop_status(provider: StatusProvider | None) -> VoiceDoctorCheck:
    try:
        if provider:
            status = provider()
        else:
            from grandpa.voice.loop import VoiceLoopSession
            from grandpa.voice.wake_word import WakeWordSession

            status = VoiceLoopSession(WakeWordSession()).status()
        mode = status.get("mode", "idle")
        return VoiceDoctorCheck("continuous loop status", "pass", f"Loop status available ({mode}).")
    except Exception as exc:
        return VoiceDoctorCheck("continuous loop status", "fail", f"Loop status failed: {exc}")


def _check_conversation_status(provider: StatusProvider | None) -> VoiceDoctorCheck:
    try:
        if provider:
            status = provider()
        else:
            from grandpa.memory.conversation import ConversationSession

            status = ConversationSession().status()
        count = status.get("message_count", 0)
        return VoiceDoctorCheck("conversation status", "pass", f"Conversation status available ({count} messages).")
    except Exception as exc:
        return VoiceDoctorCheck("conversation status", "fail", f"Conversation status failed: {exc}")


def _check_voice_history(provider: Callable[[], list[dict[str, Any]]] | None) -> VoiceDoctorCheck:
    try:
        if provider:
            history = provider()
        else:
            from grandpa.voice.history import VoiceCommandHistoryStore

            with tempfile.TemporaryDirectory(prefix="grandpa-voice-doctor-") as tmp:
                history = VoiceCommandHistoryStore(Path(tmp) / "voice_history.db").list()
        return VoiceDoctorCheck("voice history", "pass", f"Voice history available ({len(history)} entries).")
    except Exception as exc:
        return VoiceDoctorCheck("voice history", "fail", f"Voice history failed: {exc}")


def _check_voice_command_logic(provider: StatusProvider | None) -> VoiceDoctorCheck:
    try:
        result = provider() if provider else _runtime().command(text="what is my voice status")
        status = result.get("status", "unknown")
        if status in {"handled", "unsupported", "completed"} or result.get("ok") is True:
            return VoiceDoctorCheck("voice command logic", "pass", f"Safe transcript command callable ({status}).")
        return VoiceDoctorCheck("voice command logic", "warn", f"Safe transcript command returned {status}.")
    except Exception as exc:
        return VoiceDoctorCheck("voice command logic", "fail", f"Voice command logic failed: {exc}")


def _check_speech_dependencies() -> VoiceDoctorCheck:
    engines = [
        name
        for name in ("faster_whisper", "whisper")
        if importlib.util.find_spec(name) is not None
    ]
    if engines:
        return VoiceDoctorCheck("speech dependencies", "pass", f"Installed: {', '.join(engines)}.")
    return VoiceDoctorCheck(
        "speech dependencies",
        "warn",
        "Local speech packages are missing. Install with `uv sync --extra speech` for audio transcription.",
    )


def _check_ffmpeg_available() -> VoiceDoctorCheck:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return VoiceDoctorCheck("ffmpeg", "pass", f"ffmpeg available at {ffmpeg}.")
    return VoiceDoctorCheck("ffmpeg", "warn", "ffmpeg is not on PATH; local MP3/WEBM/M4A transcription may fail.")


def _check_local_model_readiness(provider: StatusProvider | None) -> VoiceDoctorCheck:
    try:
        status = provider() if provider else _runtime().speech_input.stt_status()
        model = status.get("model", "base")
        if status.get("ready"):
            return VoiceDoctorCheck("local model readiness", "pass", f"Local STT model is ready ({model}).")
        return VoiceDoctorCheck(
            "local model readiness",
            "warn",
            f"Local STT model is not ready ({model}); browser transcript mode still works.",
        )
    except Exception as exc:
        return VoiceDoctorCheck("local model readiness", "warn", f"Could not check local model readiness: {exc}")


__all__ = ["VoiceDoctorCheck", "run_voice_doctor"]
