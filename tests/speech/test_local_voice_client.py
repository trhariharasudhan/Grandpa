from __future__ import annotations

from unittest.mock import Mock

import httpx
import pytest

from grandpa.speech.local_voice.service_client import (
    DEFAULT_HEALTH_TIMEOUT_SECONDS,
    DEFAULT_SYNTHESIS_TIMEOUT_SECONDS,
    LocalVoiceServiceClient,
    LocalVoiceServiceError,
)


def test_health_requires_explicit_ready_true(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {
        "ready": False,
        "engine": "f5",
        "reason": "dependency_not_installed",
        "voice_id": "grandpa",
    }
    monkeypatch.setattr(
        "grandpa.speech.local_voice.service_client.httpx.get",
        lambda *args, **kwargs: response,
    )

    client = LocalVoiceServiceClient("http://127.0.0.1:8765")

    assert client.health() is False
    assert client.health_details()["reason"] == "dependency_not_installed"


def test_health_is_false_when_service_is_unreachable(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(
        "grandpa.speech.local_voice.service_client.httpx.get", unavailable
    )

    assert LocalVoiceServiceClient().health() is False


def test_health_uses_short_timeout_independent_of_synthesis(monkeypatch):
    captured = {}
    response = Mock(status_code=200)
    response.json.return_value = {"ready": True, "engine": "f5"}

    def get(url, *, timeout):
        captured.update(url=url, timeout=timeout)
        return response

    monkeypatch.setattr("grandpa.speech.local_voice.service_client.httpx.get", get)

    client = LocalVoiceServiceClient(synthesis_timeout_seconds=900.0)

    assert client.health() is True
    assert captured["timeout"] == DEFAULT_HEALTH_TIMEOUT_SECONDS


def test_synthesis_payload_is_bounded_and_uses_voice_id(monkeypatch):
    captured = {}
    response = Mock(status_code=200, content=b"wav")

    def post(url, *, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return response

    monkeypatch.setattr("grandpa.speech.local_voice.service_client.httpx.post", post)

    audio = LocalVoiceServiceClient("http://127.0.0.1:8765").synthesize(
        "Hello", voice="grandpa", speed=1.25, timeout_seconds=4.0
    )

    assert audio == b"wav"
    assert captured == {
        "url": "http://127.0.0.1:8765/synthesize",
        "json": {"text": "Hello", "voice_id": "grandpa", "speed": 1.25},
        "timeout": 4.0,
    }


def test_synthesis_uses_dedicated_default_timeout(monkeypatch):
    captured = {}
    response = Mock(status_code=200, content=b"wav")

    def post(url, *, json, timeout):
        captured.update(timeout=timeout)
        return response

    monkeypatch.setattr("grandpa.speech.local_voice.service_client.httpx.post", post)

    client = LocalVoiceServiceClient()

    assert client.synthesis_timeout_seconds == DEFAULT_SYNTHESIS_TIMEOUT_SECONDS
    assert client.synthesize("Hello") == b"wav"
    assert captured["timeout"] == 600.0


def test_synthesis_failure_raises_controlled_error(monkeypatch):
    def unavailable(*args, **kwargs):
        raise httpx.ReadTimeout(
            "secret transport detail",
            request=httpx.Request("POST", "http://127.0.0.1:8765/synthesize"),
        )

    monkeypatch.setattr(
        "grandpa.speech.local_voice.service_client.httpx.post", unavailable
    )

    with pytest.raises(
        LocalVoiceServiceError,
        match="Local voice service synthesis is unavailable",
    ):
        LocalVoiceServiceClient().synthesize("Hello")


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
def test_invalid_synthesis_timeout_is_rejected(timeout):
    with pytest.raises(ValueError, match="finite positive number"):
        LocalVoiceServiceClient(synthesis_timeout_seconds=timeout)
