"""Unit and regression tests for Phase 5A NativeBackendAdapter."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from grandpa.agents.operative import OperativeAgent
from grandpa.core.config import GrandpaConfig
from grandpa.core.registry import EngineRegistry, ModelRegistry
from grandpa.core.types import Message, ModelSpec, Role
from grandpa.runtime.exceptions import (
    RuntimeModelLoadError,
    RuntimeModelNotFoundError,
)
from grandpa.runtime.interface import ModelRuntime, StreamChunk
from grandpa.runtime.manager import get_runtime
from grandpa.runtime.native_adapter import NativeBackendAdapter


class FakeLlamaInstance:
    """Fake in-process llama_cpp.Llama for deterministic unit testing."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.closed = False

    def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        if stream:
            return self._stream_generator()
        return {
            "id": "chatcmpl-test-native",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello from native in-process GGUF engine!",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 14,
                "completion_tokens": 9,
                "total_tokens": 23,
            },
        }

    def _stream_generator(self):
        words = ["Hello", " from", " native", " stream!"]
        for w in words:
            yield {
                "choices": [
                    {
                        "delta": {"content": w},
                        "finish_reason": None,
                    }
                ]
            }
        yield {
            "choices": [
                {
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 14,
                "completion_tokens": 4,
                "total_tokens": 18,
            },
        }


class TestNativeBackendAdapter:
    def test_registered_in_engine_registry(self) -> None:
        EngineRegistry.register_or_replace("native", NativeBackendAdapter)
        assert EngineRegistry.contains("native")
        cls = EngineRegistry.get("native")
        assert cls is NativeBackendAdapter

    def test_missing_model_file_raises_not_found(self, tmp_path: Path) -> None:
        adapter = NativeBackendAdapter(models_dir=tmp_path)
        with pytest.raises(RuntimeModelNotFoundError, match="Local GGUF model file not found"):
            adapter.resolve_model_path("non_existent_model:latest")

    def test_resolves_model_from_models_dir(self, tmp_path: Path) -> None:
        gguf_file = tmp_path / "grandpa-mini.gguf"
        gguf_file.write_bytes(b"GGUF_MAGIC_TEST")

        adapter = NativeBackendAdapter(models_dir=tmp_path)
        resolved = adapter.resolve_model_path("grandpa-mini")
        assert resolved == gguf_file

        resolved_with_tag = adapter.resolve_model_path("grandpa-mini:latest")
        assert resolved_with_tag == gguf_file

    def test_resolves_model_from_model_registry(self, tmp_path: Path) -> None:
        custom_gguf = tmp_path / "custom_model.gguf"
        custom_gguf.write_bytes(b"GGUF_MAGIC_TEST")

        ModelRegistry.register_or_replace(
            "custom-native-model",
            ModelSpec(
                model_id="custom-native-model",
                name="Custom Native Model",
                backend="native",
                local_path=str(custom_gguf),
            ),
        )

        adapter = NativeBackendAdapter(models_dir=tmp_path)
        resolved = adapter.resolve_model_path("custom-native-model")
        assert resolved == custom_gguf

    def test_missing_llama_cpp_package_raises_load_error(self, tmp_path: Path) -> None:
        gguf_file = tmp_path / "test.gguf"
        gguf_file.write_bytes(b"GGUF")

        adapter = NativeBackendAdapter(models_dir=tmp_path)

        with patch.dict(sys.modules, {"llama_cpp": None}):
            with pytest.raises(RuntimeModelLoadError, match="llama-cpp-python"):
                adapter._get_or_load_model("test")

    def test_successful_generate(self, tmp_path: Path) -> None:
        gguf_file = tmp_path / "model.gguf"
        gguf_file.write_bytes(b"GGUF")

        adapter = NativeBackendAdapter(models_dir=tmp_path)

        fake_llama = FakeLlamaInstance()
        mock_module = MagicMock()
        mock_module.Llama.return_value = fake_llama

        with patch.dict(sys.modules, {"llama_cpp": mock_module}):
            result = adapter.generate(
                [Message(role=Role.USER, content="Hello")],
                model="model",
                temperature=0.5,
            )

        assert result["content"] == "Hello from native in-process GGUF engine!"
        assert result["model"] == "model"
        assert result["usage"]["total_tokens"] == 23
        assert result["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_successful_stream(self, tmp_path: Path) -> None:
        gguf_file = tmp_path / "model.gguf"
        gguf_file.write_bytes(b"GGUF")

        adapter = NativeBackendAdapter(models_dir=tmp_path)

        fake_llama = FakeLlamaInstance()
        mock_module = MagicMock()
        mock_module.Llama.return_value = fake_llama

        tokens = []
        with patch.dict(sys.modules, {"llama_cpp": mock_module}):
            async for tok in adapter.stream(
                [Message(role=Role.USER, content="Stream hello")],
                model="model",
            ):
                tokens.append(tok)

        assert "".join(tokens) == "Hello from native stream!"

    @pytest.mark.asyncio
    async def test_successful_stream_full(self, tmp_path: Path) -> None:
        gguf_file = tmp_path / "model.gguf"
        gguf_file.write_bytes(b"GGUF")

        adapter = NativeBackendAdapter(models_dir=tmp_path)

        fake_llama = FakeLlamaInstance()
        mock_module = MagicMock()
        mock_module.Llama.return_value = fake_llama

        chunks: list[StreamChunk] = []
        with patch.dict(sys.modules, {"llama_cpp": mock_module}):
            async for chk in adapter.stream_full(
                [Message(role=Role.USER, content="Stream full")],
                model="model",
            ):
                chunks.append(chk)

        assert len(chunks) == 5
        assert chunks[0].content == "Hello"
        assert chunks[-1].finish_reason == "stop"
        assert chunks[-1].usage["total_tokens"] == 18

    def test_unload_and_close(self, tmp_path: Path) -> None:
        gguf_file = tmp_path / "model.gguf"
        gguf_file.write_bytes(b"GGUF")

        adapter = NativeBackendAdapter(models_dir=tmp_path)
        fake_llama = FakeLlamaInstance()
        adapter._loaded_models["model"] = fake_llama

        assert "model" in adapter._loaded_models
        adapter.unload("model")
        assert "model" not in adapter._loaded_models

        adapter._loaded_models["model2"] = fake_llama
        adapter.close()
        assert len(adapter._loaded_models) == 0

    def test_list_models_scans_models_dir_and_registry(self, tmp_path: Path) -> None:
        (tmp_path / "alpha.gguf").write_bytes(b"GGUF")
        (tmp_path / "beta.Q4_K_M.gguf").write_bytes(b"GGUF")

        adapter = NativeBackendAdapter(models_dir=tmp_path)
        models = adapter.list_models()
        assert "alpha" in models
        assert "beta.Q4_K_M" in models

    def test_get_runtime_resolves_native_adapter(self, tmp_path: Path) -> None:
        cfg = GrandpaConfig()
        cfg.engine.default = "native"
        cfg.engine.native.models_dir = str(tmp_path)
        cfg.engine.native.n_ctx = 4096

        runtime = get_runtime(cfg)
        assert isinstance(runtime, NativeBackendAdapter)
        assert isinstance(runtime, ModelRuntime)
        assert runtime.models_dir == tmp_path
        assert runtime.n_ctx == 4096

    def test_agent_operates_transparently_over_native_adapter(self, tmp_path: Path) -> None:
        gguf_file = tmp_path / "grandpa-mini.gguf"
        gguf_file.write_bytes(b"GGUF")

        adapter = NativeBackendAdapter(models_dir=tmp_path)
        fake_llama = FakeLlamaInstance()
        mock_module = MagicMock()
        mock_module.Llama.return_value = fake_llama

        with patch.dict(sys.modules, {"llama_cpp": mock_module}):
            agent = OperativeAgent(
                engine=adapter,
                model="grandpa-mini",
            )
            result = agent.run("Hello Grandpa")

        assert result.content == "Hello from native in-process GGUF engine!"
        assert result.turns >= 1
