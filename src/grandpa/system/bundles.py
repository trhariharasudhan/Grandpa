"""Bundle dataclasses that group cohesive subsystems of GrandpaSystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from grandpa.agents._stubs import BaseAgent
    from grandpa.agents.executor import AgentExecutor
    from grandpa.agents.manager import AgentManager
    from grandpa.agents.scheduler import AgentScheduler
    from grandpa.scheduler.scheduler import TaskScheduler
    from grandpa.scheduler.store import SchedulerStore
    from grandpa.security.audit import AuditLogger
    from grandpa.security.boundary import BoundaryGuard
    from grandpa.security.capabilities import CapabilityPolicy
    from grandpa.telemetry.store import TelemetryStore
    from grandpa.traces.collector import TraceCollector
    from grandpa.traces.store import TraceStore


@dataclass
class SecurityContext:
    """Security policy, audit, and boundary enforcement."""

    capability_policy: Optional[CapabilityPolicy] = None
    audit_logger: Optional[AuditLogger] = None
    boundary_guard: Optional[BoundaryGuard] = None


@dataclass
class Observability:
    """Local telemetry and traces."""

    telemetry_store: Optional[TelemetryStore] = None
    trace_store: Optional[TraceStore] = None
    trace_collector: Optional[TraceCollector] = None


@dataclass
class AgentRuntime:
    """Active agent and agent lifecycle managers."""

    agent: Optional[BaseAgent] = None
    agent_name: str = ""
    manager: Optional[AgentManager] = None
    scheduler: Optional[AgentScheduler] = None
    executor: Optional[AgentExecutor] = None


@dataclass
class Scheduling:
    """Task scheduler and its persistent store."""

    store: Optional[SchedulerStore] = None
    runner: Optional[TaskScheduler] = None
