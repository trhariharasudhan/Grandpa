"""HTTP client for communicating with the standalone local voice service."""

from __future__ import annotations

import logging
import math
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SYNTHESIS_TIMEOUT_SECONDS = 600.0
DEFAULT_HEALTH_TIMEOUT_SECONDS = 2.0


class LocalVoiceServiceError(RuntimeError):
    """Controlled failure raised when the optional local service is unavailable."""


class LocalVoiceServiceClient:
    """Client for the standalone local voice service API."""

    def __init__(
        self,
        service_url: str = "http://127.0.0.1:8765",
        *,
        synthesis_timeout_seconds: float = DEFAULT_SYNTHESIS_TIMEOUT_SECONDS,
    ) -> None:
        self.service_url = service_url.rstrip("/")
        self.synthesis_timeout_seconds = _validated_timeout(
            synthesis_timeout_seconds,
            setting="synthesis_timeout_seconds",
        )

    def synthesize(
        self,
        text: str,
        *,
        voice: str = "grandpa",
        speed: float = 1.0,
        timeout_seconds: float | None = None,
    ) -> bytes:
        """Send a synthesis request to the local service and return the WAV bytes."""
        synthesis_timeout = self.synthesis_timeout_seconds
        if timeout_seconds is not None:
            synthesis_timeout = _validated_timeout(
                timeout_seconds,
                setting="timeout_seconds",
            )
        url = f"{self.service_url}/synthesize"
        payload = {
            "text": text,
            "voice_id": voice,
            "speed": speed,
        }
        try:
            response = httpx.post(url, json=payload, timeout=synthesis_timeout)
            if response.status_code == 200:
                return response.content
            raise LocalVoiceServiceError(
                f"Local voice service returned HTTP {response.status_code}."
            )
        except LocalVoiceServiceError:
            raise
        except Exception as exc:
            logger.error("Failed to connect to local voice service /synthesize: %s", exc)
            raise LocalVoiceServiceError(
                "Local voice service synthesis is unavailable."
            ) from exc

    def health(self, timeout_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS) -> bool:
        """Perform a quick GET check against the service health endpoint."""
        return bool(self.health_details(timeout_seconds).get("ready", False))

    def health_details(
        self, timeout_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS
    ) -> dict[str, Any]:
        """Return bounded service readiness details, or an unavailable result."""
        url = f"{self.service_url}/health"
        try:
            response = httpx.get(url, timeout=timeout_seconds)
            if response.status_code != 200:
                return {"ready": False, "reason": "service_unavailable"}
            payload = response.json()
            if not isinstance(payload, dict):
                return {"ready": False, "reason": "invalid_health_response"}
            return {
                "ready": payload.get("ready") is True,
                "engine": str(payload.get("engine", "")),
                "reason": str(payload.get("reason", "unknown")),
                "voice_id": str(payload.get("voice_id", "")),
            }
        except Exception:
            return {"ready": False, "reason": "service_unavailable"}


def _validated_timeout(value: float, *, setting: str) -> float:
    """Return a finite positive timeout suitable for an HTTP request."""
    if isinstance(value, bool):
        raise ValueError(f"{setting} must be a finite positive number.")
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{setting} must be a finite positive number.") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError(f"{setting} must be a finite positive number.")
    return timeout


__all__ = [
    "DEFAULT_HEALTH_TIMEOUT_SECONDS",
    "DEFAULT_SYNTHESIS_TIMEOUT_SECONDS",
    "LocalVoiceServiceClient",
    "LocalVoiceServiceError",
]
