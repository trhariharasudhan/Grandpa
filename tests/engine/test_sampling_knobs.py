"""``intelligence.top_p`` and ``intelligence.repetition_penalty`` reach Ollama.

Both keys were declared in config but never sent: the adapter always sent its
own ``repeat_penalty`` of 1.08 and no ``top_p`` at all.
"""

from __future__ import annotations

import importlib
import json

import httpx
import respx
from click.testing import CliRunner

from grandpa.agents.simple import SimpleAgent
from grandpa.cli import cli
from grandpa.core.config import GrandpaConfig, IntelligenceConfig
from grandpa.engine.ollama import OllamaEngine
from grandpa.runtime.ollama_adapter import _generation_options

_ask_mod = importlib.import_module("grandpa.cli.ask")

HOST = "http://testhost:11434"
REPLY = {
    "message": {"role": "assistant", "content": "ok"},
    "model": "qwen3:8b",
    "prompt_eval_count": 3,
    "eval_count": 1,
}


def _config(top_p: float = 0.42, repetition_penalty: float = 1.31) -> GrandpaConfig:
    cfg = GrandpaConfig()
    cfg.intelligence.top_p = top_p
    cfg.intelligence.repetition_penalty = repetition_penalty
    return cfg


def _sent_options(route) -> dict:
    return json.loads(route.calls.last.request.content)["options"]


def test_generation_options_forwards_top_p_and_repeat_penalty() -> None:
    options = _generation_options(0.7, 64, {"top_p": 0.42, "repeat_penalty": 1.31})

    assert options["top_p"] == 0.42
    assert options["repeat_penalty"] == 1.31


def test_generation_options_leaves_top_p_to_ollama_when_unset() -> None:
    assert "top_p" not in _generation_options(0.7, 64, {})


def test_config_repetition_penalty_default_matches_adapter_default() -> None:
    adapter_default = _generation_options(0.7, 64, {})["repeat_penalty"]

    assert IntelligenceConfig().repetition_penalty == adapter_default


def test_agent_path_sends_config_top_p_to_ollama(monkeypatch) -> None:
    monkeypatch.setattr("grandpa.agents._stubs.load_config", lambda: _config())
    # Explicit temperature and max_tokens, as `grandpa ask --agent` passes them:
    # that branch never consulted config before.
    agent = SimpleAgent(
        OllamaEngine(host=HOST), "qwen3:8b", temperature=0.2, max_tokens=64
    )

    with respx.mock:
        route = respx.post(f"{HOST}/api/chat").mock(
            return_value=httpx.Response(200, json=REPLY)
        )
        agent.run("hello")

    options = _sent_options(route)
    assert options["top_p"] == 0.42
    assert options["repeat_penalty"] == 1.31
    assert options["temperature"] == 0.2


def test_ask_direct_path_sends_config_top_p_to_ollama(monkeypatch, tmp_path) -> None:
    cfg = _config()
    cfg.telemetry.db_path = str(tmp_path / "telemetry.db")
    engine = OllamaEngine(host=HOST)
    monkeypatch.setattr(_ask_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(_ask_mod, "get_engine", lambda *a, **kw: ("ollama", engine))
    monkeypatch.setattr(_ask_mod, "discover_engines", lambda c: [("ollama", engine)])
    monkeypatch.setattr(_ask_mod, "discover_models", lambda e: {"ollama": ["qwen3:8b"]})

    with respx.mock(assert_all_called=False) as router:
        route = router.post(f"{HOST}/api/chat").mock(
            return_value=httpx.Response(200, json=REPLY)
        )
        router.route(host="testhost").mock(
            return_value=httpx.Response(200, json={"models": []})
        )
        result = CliRunner().invoke(
            cli,
            ["ask", "--agent", "", "--no-context", "-m", "qwen3:8b", "What is 2+2?"],
        )

    assert result.exit_code == 0, result.output
    assert route.called, "ask never sent a chat request to Ollama"
    options = _sent_options(route)
    assert options["top_p"] == 0.42
    assert options["repeat_penalty"] == 1.31


def test_sdk_direct_path_sends_config_top_p_to_ollama() -> None:
    from unittest.mock import patch

    from grandpa.sdk import Grandpa

    engine = OllamaEngine(host=HOST)
    with respx.mock(assert_all_called=False) as router:
        route = router.post(f"{HOST}/api/chat").mock(
            return_value=httpx.Response(200, json=REPLY)
        )
        router.route(host="testhost").mock(
            return_value=httpx.Response(200, json={"models": []})
        )
        with patch("grandpa.sdk.get_engine", return_value=("ollama", engine)):
            Grandpa(config=_config()).ask("hello", model="qwen3:8b", context=False)

    assert route.called, "the SDK never sent a chat request to Ollama"
    options = _sent_options(route)
    assert options["top_p"] == 0.42
    assert options["repeat_penalty"] == 1.31
