"""Tests for the Ollama engine backend."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from grandpa.core.registry import EngineRegistry
from grandpa.core.types import Message, Role
from grandpa.engine._base import (
    EngineConnectionError,
    EngineModelLoadError,
    EngineModelNotFoundError,
    EngineModelPullError,
)
from grandpa.engine.ollama import OllamaEngine, normalize_ollama_host


@pytest.fixture()
def engine() -> OllamaEngine:
    EngineRegistry.register_value("ollama", OllamaEngine)
    return OllamaEngine(host="http://testhost:11434")


class TestOllamaGenerate:
    @pytest.mark.parametrize("num_ctx", (0, 255, 262_145))
    def test_rejects_invalid_context(self, num_ctx: int) -> None:
        with pytest.raises(ValueError, match="engine.ollama.num_ctx"):
            OllamaEngine(host="http://testhost:11434", num_ctx=num_ctx)

    def test_generate_returns_content(self, engine: OllamaEngine) -> None:
        with respx.mock:
            route = respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {"role": "assistant", "content": "Hello!"},
                        "model": "qwen3:8b",
                        "prompt_eval_count": 10,
                        "eval_count": 5,
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            )
        assert result["content"] == "Hello!"
        assert result["usage"]["prompt_tokens"] >= 10
        assert result["usage"]["completion_tokens"] == 5
        assert result["usage"]["total_tokens"] == (result["usage"]["prompt_tokens"] + 5)
        sent_messages = route.calls.last.request.read()
        assert b"Canonical Grandpa Identity" in sent_messages
        assert b"General Conversation Reliability" in sent_messages
        assert b"Lack of live web access is not a reason to refuse" in sent_messages
        payload = json.loads(route.calls.last.request.content)
        assert payload["think"] is False
        assert payload["options"]["num_predict"] == 1024
        assert payload["options"]["num_ctx"] == 8192
        assert payload["options"]["repeat_penalty"] == 1.08
        assert "<|endoftext|>" in payload["options"]["stop"]

    def test_generate_uses_configured_context(self) -> None:
        configured = OllamaEngine(host="http://testhost:11434", num_ctx=1024)
        with respx.mock:
            route = respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={"message": {"role": "assistant", "content": "Hello!"}},
                )
            )
            configured.generate(
                [Message(role=Role.USER, content="Hi")], model="qwen2.5:0.5b"
            )

        payload = json.loads(route.calls.last.request.content)
        assert payload["options"]["num_ctx"] == 1024

    def test_generate_cleans_reasoning_leak(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {
                            "role": "assistant",
                            "content": "I should reason privately.</think>\nDone.",
                        },
                        "model": "qwen3:8b",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            )
        assert result["content"] == "Done."

    def test_generate_clamps_large_token_request(self, engine: OllamaEngine) -> None:
        with respx.mock:
            route = respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={"message": {"role": "assistant", "content": "Hello!"}},
                )
            )
            engine.generate(
                [Message(role=Role.USER, content="Hi")],
                model="qwen3:8b",
                max_tokens=999999,
            )
        payload = json.loads(route.calls.last.request.content)
        assert payload["options"]["num_predict"] == 2048

    def test_generate_connection_error(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
                )

    def test_generate_timeout_error(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                side_effect=httpx.ReadTimeout("slow")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
                )

    def test_generate_model_not_found_error(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    404,
                    text='model "missing:latest" not found, try pulling it first',
                )
            )
            with pytest.raises(EngineModelNotFoundError) as exc_info:
                engine.generate(
                    [Message(role=Role.USER, content="Hi")],
                    model="missing:latest",
                )

        assert exc_info.value.model == "missing:latest"

    def test_generate_low_memory_model_load_error(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    500,
                    json={
                        "error": (
                            "model requires more system memory than is available: "
                            "8.4 GiB required, 1.1 GiB available"
                        )
                    },
                )
            )
            with pytest.raises(EngineModelLoadError) as exc_info:
                engine.generate(
                    [Message(role=Role.USER, content="Hi")],
                    model="grandpa-fast:latest",
                )

        assert exc_info.value.model == "grandpa-fast:latest"
        assert exc_info.value.low_memory is True
        assert "available memory is too low" in str(exc_info.value)
        assert "grandpa-mini:latest" in str(exc_info.value)


class TestOllamaListModels:
    def test_list_models(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:11434/api/tags").mock(
                return_value=httpx.Response(
                    200,
                    json={"models": [{"name": "qwen3:8b"}, {"name": "llama3.2:3b"}]},
                )
            )
            models = engine.list_models()
        assert models == ["qwen3:8b", "llama3.2:3b"]


class TestOllamaPullModel:
    def test_pull_model_uses_ollama_pull_endpoint(self, engine: OllamaEngine) -> None:
        with respx.mock:
            route = respx.post("http://testhost:11434/api/pull").mock(
                return_value=httpx.Response(200, json={"status": "success"})
            )
            result = engine.pull_model("qwen2.5:3b")

        payload = json.loads(route.calls.last.request.content)
        assert payload == {"name": "qwen2.5:3b", "stream": False}
        assert result == {"model": "qwen2.5:3b", "status": "success"}

    def test_pull_model_connection_error(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/pull").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(EngineConnectionError):
                engine.pull_model("qwen2.5:3b")

    def test_pull_model_http_error_remains_distinguishable(
        self,
        engine: OllamaEngine,
    ) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/pull").mock(
                return_value=httpx.Response(500, text="internal error")
            )
            with pytest.raises(
                EngineModelPullError, match="Ollama pull failed with 500"
            ):
                engine.pull_model("qwen2.5:3b")


class TestOllamaHealth:
    def test_host_normalization(self) -> None:
        assert normalize_ollama_host("") == "http://127.0.0.1:11434"
        assert normalize_ollama_host("127.0.0.1:11434/") == "http://127.0.0.1:11434"
        assert (
            normalize_ollama_host("http://localhost:11434/") == "http://localhost:11434"
        )

    def test_health_true(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:11434/api/tags").mock(
                return_value=httpx.Response(200, json={"models": []})
            )
            assert engine.health() is True

    def test_health_false(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:11434/api/tags").mock(
                side_effect=httpx.ConnectError("refused")
            )
            assert engine.health() is False


class TestOllamaStream:
    @pytest.mark.asyncio
    async def test_stream_yields_content(self, engine: OllamaEngine) -> None:
        lines = [
            json.dumps({"message": {"content": "Hello"}, "done": False}),
            json.dumps({"message": {"content": " world"}, "done": True}),
        ]
        body = "\n".join(lines)
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(200, text=body)
            )
            tokens = []
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            ):
                tokens.append(tok)
        assert "Hello" in tokens

    @pytest.mark.asyncio
    async def test_stream_ignores_malformed_chunks(self, engine: OllamaEngine) -> None:
        body = "\n".join(
            (
                "not-json",
                json.dumps({"message": {"content": "Visible"}, "done": True}),
            )
        )
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(200, text=body)
            )
            tokens = [
                token
                async for token in engine.stream(
                    [Message(role=Role.USER, content="Hi")],
                    model="qwen3:8b",
                )
            ]

        assert tokens == ["Visible"]

    @pytest.mark.asyncio
    async def test_stream_model_not_found_is_typed(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(404, text="model missing not found")
            )
            with pytest.raises(EngineModelNotFoundError):
                async for _token in engine.stream(
                    [Message(role=Role.USER, content="Hi")],
                    model="missing:latest",
                ):
                    pass

    @pytest.mark.asyncio
    async def test_stream_connection_loss_is_typed_and_closes_response(
        self,
        engine: OllamaEngine,
    ) -> None:
        closed = False

        class BrokenResponse:
            is_success = True

            def raise_for_status(self):
                return None

            def iter_lines(self):
                yield json.dumps({"message": {"content": "Partial"}, "done": False})
                raise httpx.ReadError(
                    "connection lost",
                    request=httpx.Request("POST", "http://testhost:11434/api/chat"),
                )

        class ResponseContext:
            def __enter__(self):
                return BrokenResponse()

            def __exit__(self, *_exc):
                nonlocal closed
                closed = True

        engine._client.stream = MagicMock(return_value=ResponseContext())
        tokens: list[str] = []

        with pytest.raises(EngineConnectionError, match="interrupted"):
            async for token in engine.stream(
                [Message(role=Role.USER, content="Hi")],
                model="qwen3:8b",
            ):
                tokens.append(token)

        assert tokens == ["Partial"]
        assert closed is True

    @pytest.mark.asyncio
    async def test_stream_suppresses_tagged_reasoning(
        self, engine: OllamaEngine
    ) -> None:
        lines = [
            json.dumps({"message": {"content": "<think>private"}, "done": False}),
            json.dumps({"message": {"content": " thought</think>"}, "done": False}),
            json.dumps({"message": {"content": "Visible"}, "done": True}),
        ]
        body = "\n".join(lines)
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(200, text=body)
            )
            tokens = []
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            ):
                tokens.append(tok)
        assert tokens == ["Visible"]
