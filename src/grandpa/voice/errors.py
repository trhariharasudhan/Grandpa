"""Expected voice-mode errors and user-facing guidance."""

from __future__ import annotations

from typing import Any


VOICE_DEPENDENCY_MESSAGE = (
    "Voice mode is not fully installed.\n"
    "Install it with:\n"
    "uv sync --extra speech\n"
    "Then retry the command."
)
MICROPHONE_UNAVAILABLE_MESSAGE = (
    "No usable microphone was detected.\n"
    "Check Windows microphone permissions and your default input device.\n"
    "Then retry voice mode."
)
VOICE_RECOGNITION_MESSAGE = "I could not understand the audio.\nPlease try speaking again."


class VoiceError(Exception):
    """Base class for expected voice-mode setup/runtime failures."""

    status = "voice_error"
    user_message = "Voice mode could not complete that request."

    def __init__(self, message: str | None = None, *, detail: str | None = None) -> None:
        self.detail = detail
        super().__init__(message or self.user_message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "status": self.status,
            "message": str(self),
            "detail": self.detail,
        }


class VoiceDependencyError(VoiceError):
    """Raised when optional local speech dependencies are not installed."""

    status = "dependency_missing"
    user_message = VOICE_DEPENDENCY_MESSAGE


class MicrophoneUnavailableError(VoiceError):
    """Raised when no usable microphone/input payload is available."""

    status = "microphone_unavailable"
    user_message = MICROPHONE_UNAVAILABLE_MESSAGE


class VoiceRecognitionError(VoiceError):
    """Raised for expected temporary speech recognition failures."""

    status = "recognition_failed"
    user_message = VOICE_RECOGNITION_MESSAGE


__all__ = [
    "MICROPHONE_UNAVAILABLE_MESSAGE",
    "VOICE_DEPENDENCY_MESSAGE",
    "VOICE_RECOGNITION_MESSAGE",
    "MicrophoneUnavailableError",
    "VoiceDependencyError",
    "VoiceError",
    "VoiceRecognitionError",
]
