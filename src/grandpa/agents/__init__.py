"""Agent primitives with on-demand implementation registration."""

from __future__ import annotations

import importlib
import logging

from grandpa.agents._stubs import AgentContext, AgentResult, BaseAgent, ToolUsingAgent
from grandpa.core.registry import AgentRegistry

logger = logging.getLogger(__name__)
_BUILTINS = (
    "simple",
    "orchestrator",
    "native_react",
    "react",
    "rlm",
    "operative",
    "monitor",
    "monitor_operative",
)
_builtins_loaded = False


def load_builtin_agents() -> None:
    """Import agent implementations once to populate their registry."""
    global _builtins_loaded
    if _builtins_loaded:
        return
    for module in _BUILTINS:
        try:
            importlib.import_module(f"grandpa.agents.{module}")
        except ImportError as exc:
            logger.debug("Optional agent %s unavailable: %s", module, exc)
    from grandpa.core.registry import AgentRegistry
    if AgentRegistry.contains("native_react") and not AgentRegistry.contains("react"):
        AgentRegistry.register_value("react", AgentRegistry.get("native_react"))
    _builtins_loaded = True


__all__ = ["AgentContext", "AgentResult", "AgentRegistry", "BaseAgent", "ToolUsingAgent", "load_builtin_agents"]
