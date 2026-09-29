"""A tool that calls a model is not held to the budget of a tool that calls git.

``ToolSpec.timeout_seconds`` defaults to 30 for every tool, and the tools that
wrap a single inference call never overrode it. ``grandpa skill run
translate-doc`` therefore failed with "Tool 'llm' timed out after 30s." -- and
the work it was doing was correct: run uncapped, the configured model returned a
proper Tamil translation of a three-line document in 110 seconds.

The engine layer's own measured default is 900 seconds. The tool layer was thirty
times stricter than the engine it wraps, so a correct answer was discarded for
being on time by one measure and late by another. These pin the two together.
"""

from __future__ import annotations

import pytest

from grandpa.tools.model_timeout import model_call_timeout

pytestmark = pytest.mark.core


def test_the_budget_is_the_engines_not_the_generic_thirty() -> None:
    """30 is the number that broke translate-doc; anything near it is wrong."""
    assert model_call_timeout() > 60, (
        "a model call is being held to a budget meant for a git command"
    )


def test_it_matches_the_engine_adapters_own_default() -> None:
    from grandpa.runtime.ollama_adapter import DEFAULT_OLLAMA_TIMEOUT

    assert model_call_timeout() == float(DEFAULT_OLLAMA_TIMEOUT)


def test_a_configured_engine_timeout_wins(monkeypatch) -> None:
    """Raising the engine's timeout raises the tool's, because they are one number."""
    from grandpa.core import config as config_module

    loaded = config_module.GrandpaConfig()
    loaded.engine.ollama.timeout = 123.0
    monkeypatch.setattr(config_module, "load_config", lambda *a, **k: loaded)

    assert model_call_timeout() == 123.0


@pytest.mark.parametrize("tool_name", ["llm", "scan_chunks"])
def test_the_model_calling_tools_declare_it(tool_name: str) -> None:
    """The spec is what the executor reads; a tool that forgets is capped at 30.

    The classes are instantiated directly rather than through the registry:
    conftest's ``_clean_registries`` empties it before every test, and
    ``load_builtin_tools`` cannot refill it because the modules are already
    imported. Going through the registry made this skip for whichever tool lost
    the race, which is a test that reports success for doing nothing.
    """
    from grandpa.tools.llm_tool import LLMTool
    from grandpa.tools.scan_chunks import ScanChunksTool

    tool = {"llm": LLMTool, "scan_chunks": ScanChunksTool}[tool_name]()

    assert tool.spec.timeout_seconds == model_call_timeout()


def test_a_tool_that_does_not_call_a_model_keeps_the_short_budget() -> None:
    """The fix is for model calls, not a licence for everything to take forever."""
    from grandpa.tools._stubs import ToolSpec

    assert ToolSpec(name="x", description="y").timeout_seconds == 30.0
