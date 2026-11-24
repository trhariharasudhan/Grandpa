"""Tool-loop replies shown word by word in the desktop app.

The adapter's ``generate_streaming`` gives the same result as ``generate`` but
passes the reply's words to a callback as they arrive. The tool loop uses it
only when an interface asked for it (``set_stream_sink``).
"""

from __future__ import annotations

import json
from contextlib import contextmanager

from grandpa.action_layer import loop
from grandpa.runtime.ollama_adapter import OllamaBackendAdapter


class _StreamResponse:
    status_code = 200
    request = None

    def __init__(self, chunks: list[dict]) -> None:
        self._lines = [json.dumps(c) for c in chunks]

    def iter_lines(self):
        yield from self._lines

    def read(self) -> bytes:
        return b""


def _adapter(chunks: list[dict], captured: dict) -> OllamaBackendAdapter:
    adapter = OllamaBackendAdapter(keep_alive="17m")

    @contextmanager
    def fake_stream(method, path, json=None):
        captured.update(json or {})
        yield _StreamResponse(chunks)

    adapter._client.stream = fake_stream
    return adapter


def test_words_arrive_as_they_are_written_and_the_result_matches_generate() -> None:
    captured: dict = {}
    adapter = _adapter(
        [
            {"message": {"content": "Hello"}},
            {"message": {"content": " there"}},
            {"done": True, "prompt_eval_count": 12, "eval_count": 2},
        ],
        captured,
    )
    seen: list[str] = []
    result = adapter.generate_streaming([], model="m", on_text=seen.append)

    assert seen == ["Hello", " there"]
    assert result["content"] == "Hello there"
    assert "tool_calls" not in result
    # the same options as generate(), or Ollama reloads the model
    assert captured["stream"] is True
    assert captured["keep_alive"] == "17m"
    assert captured["options"]["num_ctx"] == adapter._num_ctx


def test_tool_calls_come_back_like_generate() -> None:
    adapter = _adapter(
        [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "open_app",
                                "arguments": {"name": "notepad"},
                            }
                        }
                    ],
                }
            },
            {"done": True},
        ],
        {},
    )
    result = adapter.generate_streaming([], model="m", on_text=lambda _t: None)
    assert result["tool_calls"] == [
        {"id": "call_0", "name": "open_app", "arguments": '{"name": "notepad"}'}
    ]


def test_a_failure_before_any_word_falls_back_to_generate() -> None:
    adapter = OllamaBackendAdapter()

    @contextmanager
    def broken(*_a, **_k):
        raise OSError("no stream for you")
        yield  # pragma: no cover

    adapter._client.stream = broken
    adapter.generate = lambda *a, **k: {"content": "plain answer"}
    assert adapter.generate_streaming([], model="m", on_text=print)["content"] == (
        "plain answer"
    )


def test_the_loop_streams_only_when_an_interface_asks() -> None:
    calls: list[str] = []

    class Engine:
        def generate(self, *_a, **_k):
            calls.append("generate")
            return {"content": "done"}

        def generate_streaming(self, *_a, on_text, **_k):
            calls.append("stream")
            on_text("do")
            on_text("ne")
            return {"content": "done"}

    shown: list[str] = []
    loop._ask_model(Engine(), "m", [], [], 0.0)
    loop.set_stream_sink(shown.append)
    try:
        loop._ask_model(Engine(), "m", [], [], 0.0)
    finally:
        loop.set_stream_sink(None)
    assert calls == ["generate", "stream"]
    assert shown == ["do", "ne"]


def test_a_tool_call_clears_what_was_shown() -> None:
    class Engine:
        def generate_streaming(self, *_a, on_text, **_k):
            on_text("Let me open it")
            return {
                "content": "",
                "tool_calls": [{"name": "open_app", "arguments": "{}"}],
            }

    shown: list[str] = []
    loop.set_stream_sink(shown.append)
    try:
        turn = loop._ask_model(Engine(), "m", [], [], 0.0)
    finally:
        loop.set_stream_sink(None)
    assert turn.calls and shown == ["Let me open it", ""]
