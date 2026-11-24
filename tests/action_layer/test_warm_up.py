"""warm_up sends the same opening as a real chat turn, so Ollama's cache hits."""

from __future__ import annotations

from grandpa.action_layer import loop


class RecordingEngine:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, messages, **kwargs):
        self.calls.append({"messages": list(messages), **kwargs})
        return {"content": "hello"}

    def list_models(self):
        return ["grandpa-brain:latest"]


def test_warm_up_matches_the_opening_of_a_real_turn(monkeypatch) -> None:
    monkeypatch.setattr(loop, "_require_tool_support", lambda *_a, **_k: None)
    engine = RecordingEngine()
    assert loop.warm_up(engine, "grandpa-brain:latest") is True
    loop.run("hi there", engine=engine, model="grandpa-brain:latest")

    warm, real = engine.calls
    assert warm["max_tokens"] == 1
    assert warm["messages"][0].content == real["messages"][0].content  # system prompt
    assert warm["tools"] == real["tools"]
    assert warm["model"] == real["model"]


def test_a_failed_warm_up_is_quiet() -> None:
    class Broken:
        def generate(self, *_a, **_k):
            raise RuntimeError("ollama is not running")

    assert loop.warm_up(Broken(), "grandpa-brain:latest") is False
