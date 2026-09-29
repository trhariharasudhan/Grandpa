"""How long a tool that calls a model is allowed to take.

``ToolSpec.timeout_seconds`` defaults to 30 for every tool, and the tools that
wrap one inference call never overrode it -- so a language model got the same
budget as ``git_status``. ``grandpa skill run translate-doc`` failed with "Tool
'llm' timed out after 30s.", and the translation it was doing was correct: run
with no cap, the configured model returns a proper Tamil translation of a
three-line document in 110 seconds.

Meanwhile the engine layer's own measured default is
``ollama_adapter.DEFAULT_OLLAMA_TIMEOUT``, 900 seconds. So the tool layer was
thirty times stricter than the engine it wraps, and a correct answer was thrown
away for arriving on time by the engine's standard and late by the tool's.

The two are the same budget now, read from the same place: a tool that makes one
model call waits as long as the engine is allowed to take. Resolved when asked,
not at import -- see tests/test_no_import_time_paths.py for why.
"""

from __future__ import annotations

_FALLBACK_SECONDS = 900.0
"""Used only if the engine's own default cannot be read."""


def model_call_timeout() -> float:
    """Seconds a single model call may take, from the engine's own setting."""
    try:
        from grandpa.core.config import load_config

        configured = float(load_config().engine.ollama.timeout or 0)
    except Exception:  # noqa: BLE001 - a broken config must not shorten the budget
        configured = 0.0
    if configured > 0:
        return configured
    try:
        from grandpa.runtime.ollama_adapter import DEFAULT_OLLAMA_TIMEOUT

        return float(DEFAULT_OLLAMA_TIMEOUT)
    except Exception:  # noqa: BLE001 - the adapter may not be importable
        return _FALLBACK_SECONDS


__all__ = ["model_call_timeout"]
