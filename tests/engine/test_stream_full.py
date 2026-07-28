"""Tests for the local engine streaming contract."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Dict, List

import pytest

from grandpa.core.types import Message, Role
from grandpa.engine._stubs import InferenceEngine, StreamChunk


class TestStreamChunk:
    def test_defaults(self):
        chunk = StreamChunk()
        assert chunk.content is None
        assert chunk.tool_calls is None
        assert chunk.finish_reason is None
        assert chunk.usage is None

    def test_all_fields(self):
        chunk = StreamChunk(
            content="hi",
            tool_calls=[{"index": 0}],
            finish_reason="tool_calls",
            usage={"total_tokens": 1},
        )
        assert chunk.content == "hi"
        assert chunk.tool_calls is not None
        assert chunk.finish_reason == "tool_calls"
        assert chunk.usage == {"total_tokens": 1}


class _FakeEngine(InferenceEngine):
    engine_id = "fake"

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    def generate(self, messages, *, model, **kwargs) -> Dict[str, Any]:
        return {"content": "".join(self._tokens), "usage": {}}

    async def stream(self, messages, *, model, **kwargs) -> AsyncIterator[str]:
        for token in self._tokens:
            yield token

    def list_models(self) -> List[str]:
        return ["fake-model"]

    def health(self) -> bool:
        return True


class TestDefaultStreamFull:
    @pytest.mark.asyncio
    async def test_wraps_stream_tokens(self):
        engine = _FakeEngine(["Hello", " world", "!"])
        chunks = [
            chunk
            async for chunk in engine.stream_full(
                [Message(role=Role.USER, content="test")],
                model="fake-model",
            )
        ]

        assert [chunk.content for chunk in chunks[:-1]] == [
            "Hello",
            " world",
            "!",
        ]
        assert chunks[-1].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_empty_stream_finishes(self):
        engine = _FakeEngine([])
        chunks = [
            chunk
            async for chunk in engine.stream_full(
                [Message(role=Role.USER, content="test")],
                model="fake-model",
            )
        ]
        assert len(chunks) == 1
        assert chunks[0].finish_reason == "stop"
