"""keep_alive, and the cold-start cost it exists to stop repeating.

Ollama's own default is 5 minutes and the adapter never set one, so a user who
asked something, thought for six minutes and asked again paid the whole
cold-start cost twice. Measured with the action catalogue in the prompt, that
cost was 559.9s against 9.8s for the same request held in memory.
"""

from __future__ import annotations

import pytest
from rich.console import Console

from grandpa.core.config import GrandpaConfig
from grandpa.runtime.ollama_adapter import (
    DEFAULT_KEEP_ALIVE,
    OllamaBackendAdapter,
    resolve_keep_alive,
)


@pytest.fixture(autouse=True)
def no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRANDPA_OLLAMA_KEEP_ALIVE", raising=False)


def test_the_default_is_longer_than_ollamas_own() -> None:
    """Ollama keeps a model 5 minutes. That is shorter than a person thinks."""
    assert DEFAULT_KEEP_ALIVE == "30m"


def test_precedence_is_env_then_caller_then_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert resolve_keep_alive() == DEFAULT_KEEP_ALIVE
    assert resolve_keep_alive("5m") == "5m"

    monkeypatch.setenv("GRANDPA_OLLAMA_KEEP_ALIVE", "2h")
    assert resolve_keep_alive("5m") == "2h"


def test_the_config_field_reaches_the_adapter() -> None:
    from grandpa.engine._discovery import _make_engine

    config = GrandpaConfig()
    config.engine.ollama.keep_alive = "45m"

    assert _make_engine("ollama", config)._keep_alive == "45m"


def test_an_empty_config_value_means_the_default() -> None:
    from grandpa.engine._discovery import _make_engine

    config = GrandpaConfig()
    assert config.engine.ollama.keep_alive == ""

    assert _make_engine("ollama", config)._keep_alive == DEFAULT_KEEP_ALIVE


def test_generate_actually_sends_it() -> None:
    """The setting is worthless if it does not reach the request."""
    adapter = OllamaBackendAdapter(keep_alive="17m")
    captured: dict = {}

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"message": {"content": "ok"}}

    def fake_post(path, json=None):
        captured.update(json or {})
        return _Response()

    adapter._client.post = fake_post
    adapter.generate([], model="m", tools=[{"type": "function"}])

    assert captured["keep_alive"] == "17m"


def test_zero_is_passed_through_for_anyone_who_wants_the_old_behaviour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRANDPA_OLLAMA_KEEP_ALIVE", "0")

    assert resolve_keep_alive() == "0"


# --- the cold-start notice ----------------------------------------------------


class _Probe:
    """Stands in for the adapter's HTTP client answering /api/ps."""

    def __init__(self, loaded: list[str]) -> None:
        self.loaded = loaded
        self.asked: list[str] = []

    def get(self, path: str):
        self.asked.append(path)
        probe = self

        class _Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"models": [{"model": name} for name in probe.loaded]}

        return _Response()


class _Engine:
    def __init__(self, loaded: list[str]) -> None:
        self._client = _Probe(loaded)


def _tools(count: int) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": f"action_{index}",
                "description": "x" * 200,
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for index in range(count)
    ]


def test_a_cold_model_is_announced(capsys: pytest.CaptureFixture) -> None:
    from grandpa.cli._tool_loop import warn_if_cold

    warned = warn_if_cold(
        Console(force_terminal=False), _Engine([]), "grandpa-brain:latest", _tools(50)
    )

    assert warned is True
    printed = capsys.readouterr().out
    assert "grandpa-brain:latest" in printed
    # Rich wraps the line, so match the parts rather than the whole phrase.
    assert "50 tool" in printed and "definitions" in printed
    assert "minute" in printed, "it does not say how long"


def test_a_loaded_model_says_nothing(capsys: pytest.CaptureFixture) -> None:
    from grandpa.cli._tool_loop import warn_if_cold

    warned = warn_if_cold(
        Console(force_terminal=False),
        _Engine(["grandpa-brain:latest"]),
        "grandpa-brain:latest",
        _tools(50),
    )

    assert warned is False
    assert capsys.readouterr().out == ""


def test_a_backend_that_cannot_be_probed_says_nothing() -> None:
    """The notice is a courtesy, never a failure."""
    from grandpa.cli._tool_loop import warn_if_cold

    assert warn_if_cold(Console(), object(), "m", _tools(5)) is False


def test_the_estimate_grows_with_the_catalogue(
    capsys: pytest.CaptureFixture,
) -> None:
    """The point being made: the wait is the tool definitions, not the model."""
    from grandpa.cli._tool_loop import warn_if_cold

    warn_if_cold(Console(force_terminal=False), _Engine([]), "m", _tools(10))
    small = capsys.readouterr().out
    warn_if_cold(Console(force_terminal=False), _Engine([]), "m", _tools(200))
    large = capsys.readouterr().out

    def minutes(text: str) -> int:
        import re

        return int(re.search(r"about (\d+) minute", text).group(1))

    assert minutes(large) > minutes(small)
