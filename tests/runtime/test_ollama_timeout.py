"""The Ollama request timeout: configurable, and informative when it fires.

It used to be a fixed 180s, which is less than a large model's *first* request
costs once the action catalogue's tool definitions are in the prompt. And every
transport failure said the same thing -- "Ollama not reachable" -- whether the
server was down or a model was still thinking, which makes a slow load look
like a broken install.
"""

from __future__ import annotations

import time

import httpx
import pytest

from grandpa.core.config import GrandpaConfig
from grandpa.runtime.exceptions import RuntimeConnectionError
from grandpa.runtime.ollama_adapter import (
    DEFAULT_OLLAMA_TIMEOUT,
    OllamaBackendAdapter,
    resolve_ollama_timeout,
)


@pytest.fixture(autouse=True)
def no_env_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRANDPA_OLLAMA_TIMEOUT", raising=False)


# --- where the number comes from ----------------------------------------------


def test_the_default_covers_a_cold_large_model() -> None:
    """Measured: grandpa-brain's first request with 60 tool definitions took
    439s on the development machine. A default below that is a guaranteed
    failure on the project's own recommended model."""
    assert DEFAULT_OLLAMA_TIMEOUT >= 439


def test_precedence_is_env_then_caller_then_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert resolve_ollama_timeout() == DEFAULT_OLLAMA_TIMEOUT
    assert resolve_ollama_timeout(42) == 42

    monkeypatch.setenv("GRANDPA_OLLAMA_TIMEOUT", "99")
    assert resolve_ollama_timeout(42) == 99, "the env var is the per-run override"


@pytest.mark.parametrize("value", ["nonsense", "0", "-5", ""])
def test_an_unusable_env_value_is_ignored_not_obeyed(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("GRANDPA_OLLAMA_TIMEOUT", value)

    assert resolve_ollama_timeout(42) == 42


def test_the_config_field_reaches_the_adapter() -> None:
    from grandpa.engine._discovery import _make_engine

    config = GrandpaConfig()
    config.engine.ollama.timeout = 123.0

    engine = _make_engine("ollama", config)

    assert engine._timeout == 123.0


def test_a_zero_in_config_means_use_the_default() -> None:
    from grandpa.engine._discovery import _make_engine

    config = GrandpaConfig()
    assert config.engine.ollama.timeout == 0.0

    assert _make_engine("ollama", config)._timeout == DEFAULT_OLLAMA_TIMEOUT


def test_a_dead_server_is_still_detected_quickly() -> None:
    """A long read timeout must not make an unreachable host slow to report."""
    adapter = OllamaBackendAdapter(timeout=600)

    connect = adapter._client.timeout.connect

    assert connect is not None and connect <= 30, connect
    assert adapter._client.timeout.read == 600


# --- what the failure says ----------------------------------------------------


def test_a_timeout_names_the_model_the_limit_and_the_wait() -> None:
    adapter = OllamaBackendAdapter(timeout=30)
    started = time.monotonic() - 12

    error = adapter._transport_error(
        httpx.ReadTimeout("timed out"), model="grandpa-brain:latest", started=started
    )

    assert isinstance(error, RuntimeConnectionError)
    message = str(error)
    assert "grandpa-brain:latest" in message
    assert "30s" in message, message
    assert "after 12s" in message, message
    assert "GRANDPA_OLLAMA_TIMEOUT" in message, "it does not say how to raise it"


def test_a_refused_connection_still_says_unreachable() -> None:
    """A down server and a slow model are different problems."""
    adapter = OllamaBackendAdapter(timeout=30)

    error = adapter._transport_error(
        httpx.ConnectError("refused"), model="grandpa-mini:latest"
    )

    assert "not reachable" in str(error)
    assert "timeout" not in str(error).lower()


def test_generate_reports_a_timeout_against_the_model_it_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OllamaBackendAdapter(timeout=5)

    def always_times_out(*_args, **_kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(adapter._client, "post", always_times_out)

    with pytest.raises(RuntimeConnectionError) as raised:
        adapter.generate([], model="grandpa-heavy:latest")

    assert "grandpa-heavy:latest" in str(raised.value)
