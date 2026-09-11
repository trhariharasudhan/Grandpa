"""Web search works out of the box via keyless DuckDuckGo (``ddgs``).

The network is mocked. A real-network check lives at the bottom and only runs
with ``GRANDPA_RUN_NETWORK_TESTS=1`` (this repo has no network marker).
"""

from __future__ import annotations

import functools
import importlib.machinery
import os
import sys
import types

import pytest
from click.testing import CliRunner

import grandpa.web_search.automation as automation
from grandpa.cli import cli
from grandpa.web_search.cache import WebSearchCache
from grandpa.web_search.client import WebSearchClient
from grandpa.web_search.models import WebSearchQuery
from grandpa.web_search.providers import default_provider_config

_SEARCH_ENVS = (
    "BRAVE_SEARCH_API_KEY",
    "BING_SEARCH_API_KEY",
    "SERPER_API_KEY",
    "GRANDPA_WEB_SEARCH_PROVIDER",
    "GRANDPA_WEB_SEARCH_API_KEY_ENV",
)


@pytest.fixture
def no_search_keys(monkeypatch) -> None:
    for name in _SEARCH_ENVS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fake_ddgs(monkeypatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    class _FakeDDGS:
        def text(self, query: str, **kwargs):
            calls.append((query, kwargs))
            return [
                {
                    "title": "FastAPI",
                    "href": "https://fastapi.tiangolo.com/",
                    "body": "FastAPI framework, high performance, easy to learn.",
                },
                {
                    "title": "fastapi/fastapi on GitHub",
                    "href": "https://github.com/fastapi/fastapi",
                    "body": "FastAPI framework source code.",
                },
            ]

    module = types.ModuleType("ddgs")
    module.DDGS = _FakeDDGS
    module.__spec__ = importlib.machinery.ModuleSpec("ddgs", None)
    monkeypatch.setitem(sys.modules, "ddgs", module)
    return calls


def test_default_provider_is_duckduckgo_without_api_keys(no_search_keys) -> None:
    config = default_provider_config()

    assert config.provider == "duckduckgo"
    assert WebSearchClient(config).status()[0] == "ready"


def test_keyed_provider_is_still_used_when_its_key_is_present(
    no_search_keys, monkeypatch
) -> None:
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

    config = default_provider_config()

    assert config.provider == "brave"
    assert WebSearchClient(config).status()[0] == "ready"


def test_explicit_provider_overrides_keyless_default(
    no_search_keys, monkeypatch
) -> None:
    monkeypatch.setenv("GRANDPA_WEB_SEARCH_PROVIDER", "serper")

    config = default_provider_config()

    assert config.provider == "serper"
    assert WebSearchClient(config).status()[0] == "not_configured"


def test_cli_search_web_returns_results_without_api_key(
    no_search_keys, fake_ddgs, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        automation, "WebSearchCache", functools.partial(WebSearchCache, tmp_path)
    )

    result = CliRunner().invoke(cli, ["search", "web", "fastapi"])

    assert result.exit_code == 0, result.output
    assert "not configured" not in result.output.lower()
    assert "https://fastapi.tiangolo.com/" in result.output
    assert fake_ddgs and fake_ddgs[0][0] == "fastapi"


def test_recency_window_maps_to_ddgs_timelimit(no_search_keys, fake_ddgs) -> None:
    client = WebSearchClient(default_provider_config())

    client.search(WebSearchQuery(text="fastapi release", recency_days=7))

    assert fake_ddgs[-1][1].get("timelimit") == "w"


@pytest.mark.environment
@pytest.mark.skipif(
    os.environ.get("GRANDPA_RUN_NETWORK_TESTS") != "1",
    reason="live DuckDuckGo check; set GRANDPA_RUN_NETWORK_TESTS=1 to run",
)
def test_live_duckduckgo_search_returns_results(no_search_keys) -> None:
    results = WebSearchClient(default_provider_config()).search(
        WebSearchQuery(text="fastapi", max_results=3)
    )

    assert results
    assert any(r.url.startswith("https://") for r in results)
