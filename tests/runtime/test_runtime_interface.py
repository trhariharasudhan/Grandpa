"""Unit tests proving core Grandpa components depend on ModelRuntime and BackendAdapter without Ollama couplings."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Dict, List

import pytest

from grandpa.agents.operative import OperativeAgent
from grandpa.core.config import GrandpaConfig
from grandpa.core.registry import EngineRegistry
from grandpa.core.types import Message, Role
from grandpa.runtime.adapter import BackendAdapter
from grandpa.runtime.interface import ModelRuntime, StreamChunk
from grandpa.runtime.manager import get_runtime
from grandpa.runtime.ollama_adapter import OllamaBackendAdapter


class MockBackendAdapter(BackendAdapter):
    """A completely synthetic backend adapter with zero Ollama dependencies."""

    adapter_name = "mock_adapter"

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or ["Mock response from synthetic adapter"]
        self._call_count = 0

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        resp_text = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1
        return {
            "content": resp_text,
            "model": model,
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
            },
            "finish_reason": "stop",
        }

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        resp_text = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1
        for word in resp_text.split():
            yield word + " "

    def list_models(self) -> List[str]:
        return ["synthetic-model-1:latest", "synthetic-model-2:latest"]

    def health(self) -> bool:
        return True


class TestModelRuntimeInterface:
    def test_mock_adapter_satisfies_model_runtime(self) -> None:
        runtime: ModelRuntime = MockBackendAdapter()
        assert isinstance(runtime, ModelRuntime)
        assert runtime.runtime_id == "mock_adapter"
        assert runtime.health() is True
        assert runtime.list_models() == [
            "synthetic-model-1:latest",
            "synthetic-model-2:latest",
        ]

    def test_mock_adapter_generate(self) -> None:
        runtime: ModelRuntime = MockBackendAdapter(["Hello from Grandpa runtime!"])
        result = runtime.generate(
            [Message(role=Role.USER, content="Say hello")],
            model="custom-grandpa-model",
        )
        assert result["content"] == "Hello from Grandpa runtime!"
        assert result["model"] == "custom-grandpa-model"
        assert result["usage"]["total_tokens"] == 20

    @pytest.mark.asyncio
    async def test_mock_adapter_stream(self) -> None:
        runtime: ModelRuntime = MockBackendAdapter(["Streamed token sequence"])
        tokens = []
        async for tok in runtime.stream(
            [Message(role=Role.USER, content="Stream test")],
            model="stream-model",
        ):
            tokens.append(tok)
        assert "".join(tokens).strip() == "Streamed token sequence"

    @pytest.mark.asyncio
    async def test_mock_adapter_stream_full(self) -> None:
        runtime: ModelRuntime = MockBackendAdapter(["Stream full chunk"])
        chunks: list[StreamChunk] = []
        async for chk in runtime.stream_full(
            [Message(role=Role.USER, content="Stream full test")],
            model="stream-model",
        ):
            chunks.append(chk)
        assert len(chunks) >= 2
        assert chunks[-1].finish_reason == "stop"


class TestAgentDecoupledFromOllama:
    def test_operative_agent_runs_with_pure_runtime_adapter(self) -> None:
        # Prove Grandpa agents can execute against pure ModelRuntime without Ollama
        runtime = MockBackendAdapter(
            ["I am an autonomous agent running on Grandpa runtime."]
        )
        agent = OperativeAgent(
            engine=runtime,
            model="grandpa-mini:latest",
        )

        response = agent.run("Hello Grandpa")
        assert (
            response.content == "I am an autonomous agent running on Grandpa runtime."
        )
        assert response.turns >= 1


class TestOllamaBackendAdapterContract:
    def test_ollama_adapter_is_backend_adapter_and_model_runtime(self) -> None:
        adapter = OllamaBackendAdapter(host="http://localhost:11434")
        assert isinstance(adapter, BackendAdapter)
        assert isinstance(adapter, ModelRuntime)
        assert adapter.runtime_id == "ollama"


class TestRuntimeManager:
    def test_get_runtime_resolves_registered_adapter(self) -> None:
        if not EngineRegistry.contains("mock_rt"):
            EngineRegistry.register_value("mock_rt", MockBackendAdapter)

        cfg = GrandpaConfig()
        cfg.engine.default = "mock_rt"

        runtime = get_runtime(cfg)
        assert isinstance(runtime, ModelRuntime)
        assert runtime.health() is True

    def test_get_runtime_unknown_raises(self) -> None:
        cfg = GrandpaConfig()
        with pytest.raises(RuntimeError, match="not registered"):
            get_runtime(cfg, engine_key="unknown_backend_xyz")
