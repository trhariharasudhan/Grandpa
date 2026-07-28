"""GrandpaSystem — the fully wired system dataclass."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from grandpa.core.config import GrandpaConfig
from grandpa.core.events import EventBus
from grandpa.core.types import Message
from grandpa.engine._stubs import InferenceEngine
from grandpa.system.bundles import (
    AgentRuntime,
    Observability,
    Scheduling,
    SecurityContext,
)
from grandpa.tools._stubs import BaseTool, ToolExecutor

if TYPE_CHECKING:
    from grandpa.agents._stubs import BaseAgent
    from grandpa.agents.executor import AgentExecutor
    from grandpa.agents.manager import AgentManager
    from grandpa.agents.scheduler import AgentScheduler
    from grandpa.learning._stubs import RouterPolicy
    from grandpa.mcp.client import MCPClient
    from grandpa.mcp.server import MCPServer
    from grandpa.operators.manager import OperatorManager
    from grandpa.scheduler.scheduler import TaskScheduler
    from grandpa.scheduler.store import SchedulerStore
    from grandpa.security.audit import AuditLogger
    from grandpa.security.boundary import BoundaryGuard
    from grandpa.security.capabilities import CapabilityPolicy
    from grandpa.sessions.session import SessionStore
    from grandpa.skills.manager import SkillManager
    from grandpa.speech._stubs import SpeechBackend
    from grandpa.system.orchestrator import QueryOrchestrator
    from grandpa.telemetry.store import TelemetryStore
    from grandpa.tools.storage._stubs import MemoryBackend
    from grandpa.traces.collector import TraceCollector
    from grandpa.traces.store import TraceStore
    from grandpa.workflow.engine import WorkflowEngine

logger = logging.getLogger(__name__)


@dataclass
class GrandpaSystem:
    """Fully wired system -- the single source of truth for primitive composition."""

    config: GrandpaConfig
    bus: EventBus
    engine: InferenceEngine
    engine_key: str
    model: str
    agent: Optional[BaseAgent] = None
    agent_name: str = ""
    tools: List[BaseTool] = field(default_factory=list)
    tool_executor: Optional[ToolExecutor] = None
    memory_backend: Optional[MemoryBackend] = None
    router: Optional[RouterPolicy] = None
    mcp_server: Optional[MCPServer] = None
    telemetry_store: Optional[TelemetryStore] = None
    trace_store: Optional[TraceStore] = None
    trace_collector: Optional[TraceCollector] = None
    scheduler_store: Optional[SchedulerStore] = None
    scheduler: Optional[TaskScheduler] = None
    workflow_engine: Optional[WorkflowEngine] = None
    session_store: Optional[SessionStore] = None
    capability_policy: Optional[CapabilityPolicy] = None
    audit_logger: Optional[AuditLogger] = None
    boundary_guard: Optional[BoundaryGuard] = None
    operator_manager: Optional[OperatorManager] = None
    agent_manager: Optional[AgentManager] = None
    agent_scheduler: Optional[AgentScheduler] = None
    agent_executor: Optional[AgentExecutor] = None
    speech_backend: Optional[SpeechBackend] = None
    skill_manager: Optional[SkillManager] = None
    _mcp_clients: List[MCPClient] = field(default_factory=list)

    @property
    def security(self) -> SecurityContext:
        return SecurityContext(
            capability_policy=self.capability_policy,
            audit_logger=self.audit_logger,
            boundary_guard=self.boundary_guard,
        )

    @property
    def observability(self) -> Observability:
        return Observability(
            telemetry_store=self.telemetry_store,
            trace_store=self.trace_store,
            trace_collector=self.trace_collector,
        )

    @property
    def agents(self) -> AgentRuntime:
        return AgentRuntime(
            agent=self.agent,
            agent_name=self.agent_name,
            manager=self.agent_manager,
            scheduler=self.agent_scheduler,
            executor=self.agent_executor,
        )

    @property
    def scheduling(self) -> Scheduling:
        return Scheduling(
            store=self.scheduler_store,
            runner=self.scheduler,
        )

    def _get_orchestrator(self) -> QueryOrchestrator:
        orch = self.__dict__.get("_orchestrator")
        if orch is None:
            from grandpa.system.orchestrator import QueryOrchestrator

            orch = QueryOrchestrator(self)
            self.__dict__["_orchestrator"] = orch
        return orch

    def ask(
        self,
        query: str,
        *,
        context: bool = True,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        agent: Optional[str] = None,
        tools: Optional[List[str]] = None,
        system_prompt: Optional[str] = None,
        operator_id: Optional[str] = None,
        prior_messages: Optional[List[Message]] = None,
    ) -> Dict[str, Any]:
        return self._get_orchestrator().ask(
            query,
            context=context,
            temperature=temperature,
            max_tokens=max_tokens,
            agent=agent,
            tools=tools,
            system_prompt=system_prompt,
            operator_id=operator_id,
            prior_messages=prior_messages,
        )

    def _detect_agent_intent(self, query: str) -> Optional[str]:
        return self._get_orchestrator()._detect_agent_intent(query)

    def _build_tools(self, tool_names: List[str]) -> List[BaseTool]:
        return self._get_orchestrator()._build_tools(tool_names)

    def _run_agent(
        self,
        query,
        messages,
        agent_name,
        tool_names,
        temperature,
        max_tokens,
        *,
        system_prompt=None,
        operator_id=None,
        prior_messages=None,
    ) -> Dict[str, Any]:
        return self._get_orchestrator()._run_agent(
            query,
            messages,
            agent_name,
            tool_names,
            temperature,
            max_tokens,
            system_prompt=system_prompt,
            operator_id=operator_id,
            prior_messages=prior_messages,
        )

    def _close_mcp_clients(self) -> None:
        """Close all persistent MCP client connections."""
        for client in self._mcp_clients:
            try:
                client.close()
            except Exception:
                logger.debug("Error closing MCP client", exc_info=True)

    def close(self) -> None:
        """Release resources."""
        if self.scheduler and hasattr(self.scheduler, "stop"):
            self.scheduler.stop()
        for resource in (
            self.scheduler_store,
            self.engine,
            self.telemetry_store,
            self.trace_store,
            self.memory_backend,
            self.session_store,
            self.workflow_engine,
        ):
            if resource and hasattr(resource, "close"):
                resource.close()
        if self.agent_manager is not None:
            self.agent_manager.close()
        if self.agent_scheduler is not None:
            self.agent_scheduler.stop()
        self._close_mcp_clients()

    def __enter__(self) -> GrandpaSystem:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


__all__ = ["GrandpaSystem"]
