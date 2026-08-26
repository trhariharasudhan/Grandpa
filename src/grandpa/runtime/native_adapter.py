"""Native in-process inference backend adapter for local GGUF models.

Runs local models in-process using ``llama_cpp`` without requiring an external
daemon (such as Ollama), while conforming to Grandpa's ``ModelRuntime`` interface.
"""

from __future__ import annotations

import gc
import logging
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, Dict, List, Optional

from grandpa.core import config as core_config
from grandpa.core.registry import EngineRegistry, ModelRegistry
from grandpa.core.types import Message
from grandpa.prompt.identity import ensure_grandpa_identity
from grandpa.response_cleanup import clean_assistant_response
from grandpa.runtime.adapter import BackendAdapter
from grandpa.runtime.exceptions import (
    RuntimeModelLoadError,
    RuntimeModelNotFoundError,
)
from grandpa.runtime.interface import ResponseFormat, StreamChunk
from grandpa.runtime.utils import estimate_prompt_tokens, messages_to_dicts

logger = logging.getLogger(__name__)

_DEFAULT_MODELS_DIR = core_config.DEFAULT_CONFIG_DIR / "models"


@EngineRegistry.register("native")
class NativeBackendAdapter(BackendAdapter):
    """In-process GGUF inference backend adapter powered by llama.cpp."""

    adapter_name = "native"
    supports_streaming = True

    def __init__(
        self,
        *,
        models_dir: str | Path | None = None,
        n_threads: int = 0,
        n_gpu_layers: int = 0,
        n_ctx: int = 8192,
        use_mmap: bool = True,
        use_mlock: bool = False,
        verbose: bool = False,
    ) -> None:
        self.models_dir = (
            Path(models_dir).expanduser() if models_dir else _DEFAULT_MODELS_DIR
        )
        self.n_threads = n_threads
        self.n_gpu_layers = n_gpu_layers
        self.n_ctx = n_ctx
        self.use_mmap = use_mmap
        self.use_mlock = use_mlock
        self.verbose = verbose
        # In-memory cache of loaded Llama instances: model_id -> Llama
        self._loaded_models: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Model Resolution & Lifecycle
    # ------------------------------------------------------------------

    def resolve_model_path(self, model: str) -> Path:
        """Resolve a model name or spec identifier to an absolute GGUF Path."""
        # 1. Check ModelRegistry if registered
        if ModelRegistry.contains(model):
            try:
                spec = ModelRegistry.get(model)
                if spec.local_path:
                    cand = Path(spec.local_path).expanduser()
                    if cand.is_file():
                        return cand
            except Exception:
                pass

        # 2. Check direct filesystem path
        direct_path = Path(model).expanduser()
        if direct_path.is_file():
            return direct_path

        # 3. Check models_dir / model or models_dir / f"{model}.gguf"
        candidates = [
            self.models_dir / model,
            self.models_dir / f"{model}.gguf",
            self.models_dir / f"{model}.Q4_K_M.gguf",
            self.models_dir / f"{model}.Q8_0.gguf",
        ]
        # Also check model without tag suffix e.g. "grandpa-mini:latest" -> "grandpa-mini.gguf"
        if ":" in model:
            base_name = model.split(":", 1)[0]
            candidates.extend(
                [
                    self.models_dir / base_name,
                    self.models_dir / f"{base_name}.gguf",
                    self.models_dir / f"{base_name}.Q4_K_M.gguf",
                ]
            )

        for cand in candidates:
            if cand.is_file():
                return cand

        raise RuntimeModelNotFoundError(
            model,
            f"Local GGUF model file not found for {model!r}. Searched: {candidates}",
        )

    def _get_or_load_model(self, model: str, **kwargs: Any) -> Any:
        """Retrieve a cached in-memory Llama instance or load it from disk."""
        if model in self._loaded_models:
            return self._loaded_models[model]

        try:
            import llama_cpp  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeModelLoadError(
                model,
                "The 'llama-cpp-python' package is required for native in-process inference. "
                "Install with `pip install llama-cpp-python`.",
            ) from exc

        model_path = self.resolve_model_path(model)

        ctx_len = kwargs.get("n_ctx", self.n_ctx)
        threads = kwargs.get("n_threads", self.n_threads) or None
        gpu_layers = kwargs.get("n_gpu_layers", self.n_gpu_layers)

        try:
            instance = llama_cpp.Llama(
                model_path=str(model_path),
                n_ctx=ctx_len,
                n_threads=threads,
                n_gpu_layers=gpu_layers,
                use_mmap=self.use_mmap,
                use_mlock=self.use_mlock,
                verbose=self.verbose,
            )
            self._loaded_models[model] = instance
            return instance
        except Exception as exc:
            raise RuntimeModelLoadError(
                model,
                f"Failed to load native GGUF model from {model_path}: {exc}",
            ) from exc

    def unload(self, model: Optional[str] = None) -> None:
        """Unload loaded in-memory models to release memory."""
        if model is not None:
            inst = self._loaded_models.pop(model, None)
            if inst is not None:
                del inst
        else:
            self._loaded_models.clear()
        gc.collect()

    # ------------------------------------------------------------------
    # ModelRuntime Interface Implementation
    # ------------------------------------------------------------------

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Execute non-streaming in-process chat generation."""
        messages = ensure_grandpa_identity(messages, model)
        msg_dicts = messages_to_dicts(messages)

        llama = self._get_or_load_model(model, **kwargs)

        chat_kwargs: Dict[str, Any] = {
            "messages": msg_dicts,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        # Apply response format / structured schema if requested
        response_format = kwargs.get("response_format")
        if response_format is not None:
            if isinstance(response_format, ResponseFormat):
                if response_format.schema:
                    chat_kwargs["response_format"] = {
                        "type": "json_object",
                        "schema": response_format.schema,
                    }
                else:
                    chat_kwargs["response_format"] = {"type": "json_object"}
            elif isinstance(response_format, dict):
                chat_kwargs["response_format"] = response_format

        try:
            raw = llama.create_chat_completion(**chat_kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"Native generation failed for model {model!r}: {exc}"
            ) from exc

        choice = raw.get("choices", [{}])[0]
        raw_msg = choice.get("message", {})
        content = clean_assistant_response(raw_msg.get("content", "") or "")

        usage_raw = raw.get("usage", {})
        prompt_tokens = usage_raw.get("prompt_tokens") or estimate_prompt_tokens(
            messages
        )
        completion_tokens = usage_raw.get("completion_tokens", 0)

        result: Dict[str, Any] = {
            "content": content,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model": model,
            "finish_reason": choice.get("finish_reason", "stop") or "stop",
        }

        # Handle tool calls if present
        tool_calls = raw_msg.get("tool_calls")
        if tool_calls:
            result["tool_calls"] = tool_calls

        return result

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream generated text chunks asynchronously."""
        async for chunk in self.stream_full(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            if chunk.content:
                yield chunk.content

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Stream rich ``StreamChunk``s asynchronously."""
        messages = ensure_grandpa_identity(messages, model)
        msg_dicts = messages_to_dicts(messages)

        llama = self._get_or_load_model(model, **kwargs)

        chat_kwargs: Dict[str, Any] = {
            "messages": msg_dicts,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            chunks = llama.create_chat_completion(**chat_kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"Native stream initialization failed for {model!r}: {exc}"
            ) from exc

        last_finish_reason = "stop"
        usage_data: Optional[Dict[str, Any]] = None

        for raw_chunk in chunks:
            choices = raw_chunk.get("choices", [])
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta", {})
            content = delta.get("content")
            if content:
                yield StreamChunk(content=content)

            tool_calls = delta.get("tool_calls")
            if tool_calls:
                yield StreamChunk(tool_calls=tool_calls)

            finish_reason = choice.get("finish_reason")
            if finish_reason:
                last_finish_reason = finish_reason

            if "usage" in raw_chunk:
                usage_data = raw_chunk["usage"]

        if usage_data is None:
            usage_data = {
                "prompt_tokens": estimate_prompt_tokens(messages),
                "completion_tokens": 0,
                "total_tokens": estimate_prompt_tokens(messages),
            }

        yield StreamChunk(
            finish_reason=last_finish_reason,
            usage=usage_data,
        )

    def list_models(self) -> List[str]:
        """Return list of locally available GGUF model identifiers."""
        found: set[str] = set()

        # 1. Scan models_dir for .gguf files
        if self.models_dir.is_dir():
            try:
                for entry in self.models_dir.glob("*.gguf"):
                    name = entry.stem
                    found.add(name)
            except Exception as exc:
                logger.debug("Failed scanning models_dir %s: %s", self.models_dir, exc)

        # 2. Add any registered models with valid local_path
        for spec in ModelRegistry.list_models():
            if spec.backend == "native" and spec.local_path:
                if Path(spec.local_path).is_file():
                    found.add(spec.model_id)

        # 3. Include currently loaded models in memory
        for m in self._loaded_models:
            found.add(m)

        return sorted(found)

    def health(self) -> bool:
        """Check if native runtime is available."""
        try:
            import llama_cpp  # noqa: F401

            return True
        except ImportError:
            return False

    def prepare(self, model: str) -> None:
        """Pre-load model weights into memory."""
        self._get_or_load_model(model)

    def close(self) -> None:
        """Release all model resources."""
        self.unload()


__all__ = ["NativeBackendAdapter"]
