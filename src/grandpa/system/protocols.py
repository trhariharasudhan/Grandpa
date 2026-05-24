"""Structural protocols for substituting fakes in place of GrandpaSystem."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Protocol

if TYPE_CHECKING:
    from grandpa.core.config import GrandpaConfig
    from grandpa.core.events import EventBus
    from grandpa.engine._stubs import InferenceEngine
    from grandpa.security.capabilities import CapabilityPolicy
    from grandpa.sessions.session import SessionStore
    from grandpa.tools._stubs import BaseTool
    from grandpa.tools.storage._stubs import MemoryBackend
    from grandpa.traces.collector import TraceCollector
    from grandpa.traces.store import TraceStore


class OrchestratorDeps(Protocol):
    """Minimum surface of GrandpaSystem that QueryOrchestrator depends on.

    Tests can satisfy this with a lightweight class — no need to construct
    the full GrandpaSystem dataclass or materialize every subsystem.
    """

    config: GrandpaConfig
    bus: EventBus
    engine: InferenceEngine
    engine_key: str
    model: str
    agent_name: str
    tools: List[BaseTool]
    memory_backend: Optional[MemoryBackend]
    capability_policy: Optional[CapabilityPolicy]
    session_store: Optional[SessionStore]
    trace_store: Optional[TraceStore]
    trace_collector: Optional[TraceCollector]  # written by _run_agent

    # Optional attribute (getattr with default) — declared for type clarity.
    _skill_few_shot_examples: Any
