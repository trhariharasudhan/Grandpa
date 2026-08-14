"""Narrow dependency ports consumed by :class:`AssistantKernel`."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from grandpa.kernel.models import (
    AssistantContext,
    AssistantRequest,
    AssistantResponse,
    AuditEvent,
    ConfirmationRequest,
    ExecutionAuthorization,
    ExecutionPlan,
    Intent,
    PlannedAction,
    PolicyDecision,
    ToolResult,
    VerificationResult,
)


class ToolDefinition(Protocol):
    name: str
    argument_schema: Mapping[str, Any]

    def validate_arguments(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]: ...


class RequestNormalizer(Protocol):
    def normalize(self, request: AssistantRequest) -> AssistantRequest: ...


class IntentClassifier(Protocol):
    def classify(self, request: AssistantRequest) -> Intent: ...


class ContextProvider(Protocol):
    def build(self, request: AssistantRequest, intent: Intent) -> AssistantContext: ...


class Planner(Protocol):
    def plan(
        self,
        request: AssistantRequest,
        intent: Intent,
        context: AssistantContext,
    ) -> ExecutionPlan: ...


class PolicyEngine(Protocol):
    def evaluate(
        self,
        request: AssistantRequest,
        context: AssistantContext,
        action: PlannedAction,
        action_digest: str,
    ) -> PolicyDecision: ...


class ConfirmationService(Protocol):
    def issue(
        self,
        request: AssistantRequest,
        action: PlannedAction,
        decision: PolicyDecision,
    ) -> ConfirmationRequest: ...

    def validate(
        self,
        token: str,
        request: AssistantRequest,
        action: PlannedAction,
        decision: PolicyDecision,
    ) -> bool: ...


class ToolRegistry(Protocol):
    def resolve(self, name: str) -> ToolDefinition: ...


class ToolExecutor(Protocol):
    def execute(
        self,
        tool: ToolDefinition,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        context: AssistantContext,
        authorization: ExecutionAuthorization,
    ) -> ToolResult: ...


class Verifier(Protocol):
    def verify(
        self,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        result: ToolResult,
        context: AssistantContext,
    ) -> VerificationResult: ...


class AuditSink(Protocol):
    def record(self, event: AuditEvent) -> None: ...


class MemoryUpdater(Protocol):
    def update(
        self,
        request: AssistantRequest,
        context: AssistantContext,
        plan: ExecutionPlan,
        results: tuple[ToolResult, ...],
        verifications: tuple[VerificationResult, ...],
    ) -> None: ...


class ResponseRenderer(Protocol):
    def render(self, response: AssistantResponse) -> AssistantResponse: ...
