"""Ollama inference engine backend."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Sequence
from typing import Any, Dict, List

import httpx

from grandpa.core.registry import EngineRegistry
from grandpa.core.types import Message
from grandpa.engine._base import (
    EngineConnectionError,
    EngineModelLoadError,
    EngineModelNotFoundError,
    EngineModelPullError,
    InferenceEngine,
    estimate_prompt_tokens,
    messages_to_dicts,
)
from grandpa.engine._network import local_port_is_open
from grandpa.engine._stubs import StreamChunk
from grandpa.response_cleanup import clean_assistant_response

logger = logging.getLogger(__name__)

_MAX_NUM_PREDICT = 2048
_DEFAULT_STOP_SEQUENCES = ["<|im_end|>", "<|endoftext|>"]
_DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
_LOW_MEMORY_MARKERS = (
    "not enough memory",
    "out of memory",
    "insufficient memory",
    "memory required",
    "system memory",
    "available memory",
    "failed to allocate",
    "cuda out of memory",
)


def normalize_ollama_host(host: str | None) -> str:
    """Return a usable Ollama HTTP base URL."""

    value = (host or "").strip() or _DEFAULT_OLLAMA_HOST
    if "://" not in value:
        value = f"http://{value}"
    return value.rstrip("/")


def _generation_options(
    temperature: float,
    max_tokens: int,
    kwargs: dict[str, Any],
) -> Dict[str, Any]:
    requested = _coerce_positive_int(max_tokens, default=1024)
    options: Dict[str, Any] = {
        "temperature": temperature,
        "num_predict": min(requested, _MAX_NUM_PREDICT),
        "num_ctx": kwargs.get("num_ctx", 8192),
        "repeat_penalty": kwargs.get("repeat_penalty", 1.08),
    }
    stop = kwargs.get("stop", _DEFAULT_STOP_SEQUENCES)
    if isinstance(stop, str):
        stop = [stop]
    if stop:
        options["stop"] = list(stop)
    return options


def _coerce_positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _visible_stream_delta(content: str, state: dict[str, bool]) -> str:
    """Drop explicit streamed reasoning tags without delaying normal tokens."""

    if not content:
        return ""
    text = str(content)
    lower = text.lower()
    if state.get("in_reasoning"):
        end = _first_reasoning_end(lower)
        if end is None:
            return ""
        text = text[end:]
        lower = text.lower()
        state["in_reasoning"] = False

    visible = ""
    while text:
        lower = text.lower()
        start = _first_reasoning_start(lower)
        if start is None:
            visible += text
            break
        visible += text[: start[0]]
        text = text[start[1] :]
        lower = text.lower()
        end = _first_reasoning_end(lower)
        if end is None:
            state["in_reasoning"] = True
            break
        text = text[end:]
    return visible


def _first_reasoning_start(lower_text: str) -> tuple[int, int] | None:
    starts = [
        (lower_text.find(tag), len(tag))
        for tag in ("<think>", "<thinking>", "<analysis>", "<reasoning>")
        if lower_text.find(tag) >= 0
    ]
    if not starts:
        return None
    index, length = min(starts)
    return index, index + length


def _first_reasoning_end(lower_text: str) -> int | None:
    ends = [
        (lower_text.find(tag), len(tag))
        for tag in ("</think>", "</thinking>", "</analysis>", "</reasoning>")
        if lower_text.find(tag) >= 0
    ]
    if not ends:
        return None
    index, length = min(ends)
    return index + length


@EngineRegistry.register("ollama")
class OllamaEngine(InferenceEngine):
    """Ollama backend via its native HTTP API."""

    engine_id = "ollama"
    supports_streaming = True

    _DEFAULT_HOST = _DEFAULT_OLLAMA_HOST

    def __init__(
        self,
        host: str | None = None,
        *,
        timeout: float = 180.0,
    ) -> None:
        # Priority: explicit host (from config.toml) > OLLAMA_HOST env var > default
        if host is None:
            env_host = os.environ.get("OLLAMA_HOST")
            host = env_host or self._DEFAULT_HOST
        self._host = normalize_ollama_host(host)
        self._client = httpx.Client(base_url=self._host, timeout=timeout)
        # Last stream usage — captured from Ollama's final chunk
        self._last_stream_usage: Dict[str, int] = {}

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        msg_dicts = messages_to_dicts(messages)
        # Ollama expects tool_call arguments as dicts, not JSON strings
        for md in msg_dicts:
            for tc in md.get("tool_calls", []):
                fn = tc.get("function", {})
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        fn["arguments"] = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        pass
        payload: Dict[str, Any] = {
            "model": model,
            "messages": msg_dicts,
            "stream": False,
            "options": _generation_options(temperature, max_tokens, kwargs),
        }
        # Disable extended thinking by default (Qwen3.5 etc.).
        # When enabled, thinking tokens consume the entire budget and
        # the visible content comes back empty.
        if "think" not in kwargs:
            payload["think"] = False
        elif kwargs["think"] is not None:
            payload["think"] = kwargs["think"]
        # Pass tools if provided
        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools

        # Apply structured output / JSON mode
        response_format = kwargs.get("response_format")
        if response_format is not None:
            from grandpa.engine._stubs import ResponseFormat

            if isinstance(response_format, ResponseFormat):
                payload["format"] = "json"
            elif isinstance(response_format, dict):
                payload["format"] = "json"
        try:
            resp = self._client.post("/api/chat", json=payload)
            if resp.status_code == 400 and tools:
                # Model may not support function calling -- retry without tools
                payload.pop("tools", None)
                resp = self._client.post("/api/chat", json=payload)
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise EngineConnectionError(
                f"Ollama not reachable at {self._host}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500] if exc.response else ""
            if _is_model_not_found_error(exc.response.status_code, body):
                raise EngineModelNotFoundError(
                    model,
                    f"Ollama model {model!r} is not installed.",
                ) from exc
            if _is_model_load_error(body):
                raise EngineModelLoadError(
                    model,
                    _format_model_load_error(model, body),
                    low_memory=_is_low_memory_error(body),
                ) from exc
            raise RuntimeError(
                f"Ollama returned {exc.response.status_code}: {_extract_ollama_error(body)}"
            ) from exc
        data = resp.json()
        # prompt_eval_count = tokens actually evaluated (KV-cache-aware).
        # estimate_prompt_tokens = full prompt size (for cost comparison).
        # We report both so downstream can use the right one:
        #   prompt_tokens        → full size (what cloud would charge)
        #   prompt_tokens_evaluated → actual compute (with KV cache)
        reported_prompt = data.get("prompt_eval_count", 0)
        estimated_prompt = estimate_prompt_tokens(messages)
        prompt_tokens = max(reported_prompt, estimated_prompt)
        prompt_tokens_evaluated = (
            reported_prompt if reported_prompt > 0 else prompt_tokens
        )
        completion_tokens = data.get("eval_count", 0)
        content = clean_assistant_response(
            data.get("message", {}).get("content", ""),
            fallback="",
        )
        result: Dict[str, Any] = {
            "content": content,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "prompt_tokens_evaluated": prompt_tokens_evaluated,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model": data.get("model", model),
            "finish_reason": "stop",
        }
        # Extract timing from Ollama response (nanoseconds → seconds)
        result["ttft"] = data.get("prompt_eval_duration", 0) / 1e9
        result["engine_timing"] = {
            k: data[k]
            for k in (
                "total_duration",
                "load_duration",
                "prompt_eval_duration",
                "eval_duration",
            )
            if k in data
        }
        # Extract tool calls if present
        raw_tool_calls = data.get("message", {}).get("tool_calls", [])
        if raw_tool_calls:
            tool_calls = []
            for i, tc in enumerate(raw_tool_calls):
                raw_args = tc.get("function", {}).get(
                    "arguments",
                    "{}",
                )
                tool_calls.append(
                    {
                        "id": tc.get("id", f"call_{i}"),
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": (
                            json.dumps(raw_args)
                            if isinstance(raw_args, dict)
                            else raw_args
                        ),
                    }
                )
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
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages_to_dicts(messages),
            "stream": True,
            "options": _generation_options(temperature, max_tokens, kwargs),
        }
        # Mirror generate()'s default: disable extended thinking unless the
        # caller opted in. Qwen3/etc. with thinking on can stall the visible
        # stream for 60+ seconds before any tokens reach the client, which
        # clients interpret as a "Load failed" timeout.
        if "think" not in kwargs:
            payload["think"] = False
        elif kwargs["think"] is not None:
            payload["think"] = kwargs["think"]
        try:
            with self._client.stream("POST", "/api/chat", json=payload) as resp:
                if not resp.is_success:
                    resp.read()
                resp.raise_for_status()
                stream_state = {"in_reasoning": False}
                for line in resp.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Ignoring malformed Ollama stream chunk")
                        continue
                    content = _visible_stream_delta(
                        chunk.get("message", {}).get("content", ""),
                        stream_state,
                    )
                    if content:
                        yield content
                    if chunk.get("done", False):
                        reported_prompt = chunk.get("prompt_eval_count", 0)
                        est_prompt = estimate_prompt_tokens(messages)
                        full_prompt = max(reported_prompt, est_prompt)
                        evaluated = (
                            reported_prompt if reported_prompt > 0 else full_prompt
                        )
                        comp = chunk.get("eval_count", 0)
                        self._last_stream_usage = {
                            "prompt_tokens": full_prompt,
                            "prompt_tokens_evaluated": evaluated,
                            "completion_tokens": comp,
                            "total_tokens": full_prompt + comp,
                        }
                        break
        except httpx.RequestError as exc:
            raise EngineConnectionError(
                f"Ollama stream was interrupted at {self._host}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500] if exc.response else ""
            if _is_model_not_found_error(exc.response.status_code, body):
                raise EngineModelNotFoundError(
                    model,
                    f"Ollama model {model!r} is not installed.",
                ) from exc
            if _is_model_load_error(body):
                raise EngineModelLoadError(
                    model,
                    _format_model_load_error(model, body),
                    low_memory=_is_low_memory_error(body),
                ) from exc
            raise RuntimeError(
                f"Ollama returned {exc.response.status_code}: "
                f"{_extract_ollama_error(body)}"
            ) from exc

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Yield ``StreamChunk``s including tool_calls.

        Unlike the default ``stream_full`` in the base class (which wraps
        ``stream()`` and drops tools), this posts to ``/api/chat`` with
        ``tools`` from kwargs and parses tool_calls out of the streamed
        response. Falls back to a tools-less retry on 400 (mirrors
        ``generate()``'s behaviour for models that don't support tools).
        """
        msg_dicts = messages_to_dicts(messages)
        for md in msg_dicts:
            for tc in md.get("tool_calls", []):
                fn = tc.get("function", {})
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        fn["arguments"] = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        pass

        payload: Dict[str, Any] = {
            "model": model,
            "messages": msg_dicts,
            "stream": True,
            "options": _generation_options(temperature, max_tokens, kwargs),
        }
        if "think" not in kwargs:
            payload["think"] = False
        elif kwargs["think"] is not None:
            payload["think"] = kwargs["think"]

        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools

        async for chunk in self._run_stream(
            payload, messages, retry_without_tools=bool(tools)
        ):
            yield chunk

    async def _run_stream(
        self,
        payload: Dict[str, Any],
        messages: Sequence[Message],
        *,
        retry_without_tools: bool,
    ) -> AsyncIterator[StreamChunk]:
        """Execute the streaming request and yield parsed StreamChunks."""
        try:
            with self._client.stream("POST", "/api/chat", json=payload) as resp:
                if resp.status_code == 400 and retry_without_tools:
                    # Model doesn't support tools — retry without them.
                    payload.pop("tools", None)
                    async for c in self._run_stream(
                        payload, messages, retry_without_tools=False
                    ):
                        yield c
                    return
                resp.raise_for_status()

                finish_reason: str | None = None
                stream_state = {"in_reasoning": False}
                for line in resp.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    message = chunk.get("message", {}) or {}
                    content = _visible_stream_delta(
                        message.get("content", ""),
                        stream_state,
                    )
                    raw_tool_calls = message.get("tool_calls") or []

                    if content:
                        yield StreamChunk(content=content)

                    if raw_tool_calls:
                        # Ollama emits fully-formed tool_calls in a single
                        # chunk (not fragmented). Convert to the
                        # OpenAI-compatible delta fragment shape for local streaming
                        # expects in _merge_tool_call_fragments.
                        fragments: List[Dict[str, Any]] = []
                        for i, tc in enumerate(raw_tool_calls):
                            fn = tc.get("function", {}) or {}
                            raw_args = fn.get("arguments", "{}")
                            args_str = (
                                json.dumps(raw_args)
                                if isinstance(raw_args, dict)
                                else str(raw_args)
                            )
                            fragments.append(
                                {
                                    "index": i,
                                    "id": tc.get("id", f"call_{i}"),
                                    "type": "function",
                                    "function": {
                                        "name": fn.get("name", ""),
                                        "arguments": args_str,
                                    },
                                }
                            )
                        yield StreamChunk(tool_calls=fragments)
                        finish_reason = "tool_calls"

                    if chunk.get("done", False):
                        reported_prompt = chunk.get("prompt_eval_count", 0)
                        est_prompt = estimate_prompt_tokens(messages)
                        full_prompt = max(reported_prompt, est_prompt)
                        evaluated = (
                            reported_prompt if reported_prompt > 0 else full_prompt
                        )
                        comp = chunk.get("eval_count", 0)
                        self._last_stream_usage = {
                            "prompt_tokens": full_prompt,
                            "prompt_tokens_evaluated": evaluated,
                            "completion_tokens": comp,
                            "total_tokens": full_prompt + comp,
                        }
                        if finish_reason is None:
                            finish_reason = chunk.get("done_reason") or "stop"
                        yield StreamChunk(
                            finish_reason=finish_reason,
                            usage=dict(self._last_stream_usage),
                        )
                        break
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise EngineConnectionError(
                f"Ollama not reachable at {self._host}"
            ) from exc

    def list_models(self) -> List[str]:
        try:
            resp = self._client.get("/api/tags")
            resp.raise_for_status()
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.HTTPStatusError,
        ) as exc:
            logger.warning(
                "Failed to list models from Ollama at %s: %s",
                self._host,
                exc,
            )
            return []
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]

    def pull_model(self, model: str) -> Dict[str, Any]:
        """Pull an Ollama model through the local Ollama HTTP API."""
        payload = {"name": model, "stream": False}
        try:
            resp = self._client.post("/api/pull", json=payload)
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise EngineConnectionError(
                f"Ollama not reachable at {self._host}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500] if exc.response else ""
            raise EngineModelPullError(
                model, f"Ollama pull failed with {exc.response.status_code}: {body}"
            ) from exc
        try:
            data = resp.json() if resp.content else {}
        except ValueError as exc:
            raise EngineModelPullError(
                model, "Ollama returned an invalid pull response."
            ) from exc
        if data.get("error"):
            raise EngineModelPullError(model, str(data["error"]))
        return {"model": model, "status": data.get("status", "success")}

    def health(self) -> bool:
        try:
            if not local_port_is_open(self._host):
                return False
            timeout = httpx.Timeout(
                1.0,
                connect=0.25,
                read=0.75,
                write=0.25,
                pool=0.25,
            )
            resp = self._client.get("/api/tags", timeout=timeout)
            return resp.status_code == 200
        except Exception as exc:
            logger.debug("Ollama health check failed at %s: %s", self._host, exc)
            return False

    def close(self) -> None:
        self._client.close()


def _is_model_not_found_error(status_code: int, body: str) -> bool:
    lowered = body.lower()
    return status_code == 404 or (
        "model" in lowered
        and ("not found" in lowered or "pull" in lowered or "not installed" in lowered)
    )


def _extract_ollama_error(body: str) -> str:
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body[:500]
    if isinstance(parsed, dict):
        error = parsed.get("error") or parsed.get("message")
        if error:
            return str(error)[:500]
    return body[:500]


def _is_model_load_error(body: str) -> bool:
    lowered = _extract_ollama_error(body).lower()
    return (
        "load" in lowered
        or "memory" in lowered
        or "allocate" in lowered
        or "runner" in lowered
    ) and any(
        marker in lowered
        for marker in (
            "memory",
            "allocate",
            "runner",
            "load model",
            "loading model",
        )
    )


def _is_low_memory_error(body: str) -> bool:
    lowered = _extract_ollama_error(body).lower()
    return any(marker in lowered for marker in _LOW_MEMORY_MARKERS)


def _format_model_load_error(model: str, body: str) -> str:
    detail = _extract_ollama_error(body)
    if _is_low_memory_error(body):
        return (
            f"Ollama could not load {model} because available memory is too low. "
            "Close memory-heavy apps or use grandpa-light:latest."
        )
    return f"Ollama could not load {model}: {detail}"


__all__ = [
    "OllamaEngine",
    "normalize_ollama_host",
]
