"""Standalone localhost service for Grandpa's optional cloned voice."""

from grandpa.voice_service.service import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    VoiceServiceRuntime,
    create_app,
)

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "VoiceServiceRuntime", "create_app"]
