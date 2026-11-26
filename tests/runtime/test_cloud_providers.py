"""Cloud providers through their OpenAI-compatible APIs (grandpa.engine.cloud)."""

from __future__ import annotations

import json

import httpx
import pytest

from grandpa.engine import cloud
from grandpa.engine.cloud import CloudClient, Provider


def _client(handler) -> CloudClient:
    client = CloudClient(
        Provider("groq", "Groq", "https://api.groq.com/openai/v1", ("m",)), "k"
    )
    client._client = httpx.Client(
        base_url="https://api.groq.com/openai/v1",
        transport=httpx.MockTransport(handler),
    )
    return client


def test_generate_returns_the_same_shape_as_ollama() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "function": {
                                        "name": "open_app",
                                        "arguments": '{"name":"notepad"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 1,
                    "total_tokens": 6,
                },
            },
        )

    result = _client(handler).generate(
        [], model="m", tools=[{"name": "open_app", "parameters": {}}]
    )
    assert result["tool_calls"] == [
        {"id": "c1", "name": "open_app", "arguments": '{"name":"notepad"}'}
    ]
    assert seen["tools"][0]["type"] == "function"  # wrapped the way OpenAI wants


def test_streaming_passes_words_and_collects_tool_calls() -> None:
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c","function":{"name":"time","arguments":"{"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"}"}}]}}]}',
        "data: [DONE]",
    ]

    def handler(request):
        return httpx.Response(200, content="\n".join(lines).encode())

    shown: list[str] = []
    result = _client(handler).generate_streaming([], model="m", on_text=shown.append)
    assert shown == ["Hel", "lo"] and result["content"] == "Hello"
    assert result["tool_calls"] == [{"id": "c", "name": "time", "arguments": "{}"}]


def test_a_bad_key_says_so() -> None:
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "Invalid API Key"}})

    with pytest.raises(RuntimeError, match="check the API key"):
        _client(handler).generate([], model="m")


def test_cloud_model_names_never_collide_with_ollama_names() -> None:
    assert cloud.is_cloud("@groq/llama") and not cloud.is_cloud("llama3:latest")
    assert cloud.split_model("@openrouter/meta-llama/llama-3-8b") == (
        "openrouter",
        "meta-llama/llama-3-8b",
    )
    with pytest.raises(ValueError):
        cloud.split_model("groq/llama")


def test_the_ollama_adapter_hands_cloud_models_over(monkeypatch) -> None:
    from grandpa.runtime.ollama_adapter import OllamaBackendAdapter

    class Fake:
        def generate(self, messages, *, model, **_k):
            return {"content": f"cloud {model}"}

    monkeypatch.setattr(
        cloud, "client_for", lambda model: (Fake(), model.split("/", 1)[1])
    )
    adapter = OllamaBackendAdapter()
    assert adapter.generate([], model="@groq/llama")["content"] == "cloud llama"
