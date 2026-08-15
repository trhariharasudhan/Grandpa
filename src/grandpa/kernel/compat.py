"""Compatibility builders for canonical AssistantKernel migrations."""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from grandpa.core.events import EventBus, EventType, get_event_bus
from grandpa.kernel.assistant import AssistantKernel
from grandpa.kernel.errors import (
    IntentClassificationError,
    RequestNormalizationError,
)
from grandpa.kernel.files import (
    COPY_PATH_TOOL,
    CREATE_FOLDER_TOOL,
    LIST_DIRECTORY_TOOL,
    SEARCH_FILES_TOOL,
    STAT_PATH_TOOL,
    FileCompatibilityExecutor,
    FileCompatibilityPolicy,
    FileCompatibilityToolRegistry,
    FileCompatibilityVerifier,
    FileReadOnlyExecutor,
    FileReadOnlyPolicy,
    FileReadOnlyToolRegistry,
    FileReadOnlyVerifier,
    ListDirectoryExecutor,
    ListDirectoryPolicy,
    ListDirectoryVerifier,
    SingleToolRegistry,
)
from grandpa.kernel.models import (
    AssistantContext,
    AssistantRequest,
    AssistantResponse,
    AuditEvent,
    ConfirmationRequest,
    ExecutionPlan,
    Intent,
    PlannedAction,
    PolicyDecision,
    ToolResult,
    VerificationResult,
    VerificationSpec,
    model_to_dict,
    utc_now,
)


class BasicRequestNormalizer:
    def normalize(self, request: AssistantRequest) -> AssistantRequest:
        text = " ".join(request.text.strip().split())
        if not text:
            raise RequestNormalizationError(
                "Request text is empty.",
                safe_message="Enter a request first.",
            )
        return replace(request, text=text)


class ListDirectoryIntentClassifier:
    _PATTERN = re.compile(r"^list\s+files(?:\s+(?:in|from))?\s+(.+)$", re.IGNORECASE)

    def classify(self, request: AssistantRequest) -> Intent:
        match = self._PATTERN.match(request.text)
        if not match:
            raise IntentClassificationError(
                "Phase 1 only supports files.list_directory.",
                safe_message="This kernel harness currently supports listing a directory.",
            )
        return Intent(
            domain="files",
            name="list_directory",
            confidence=1.0,
            entities={"path": match.group(1).strip()},
        )


class LightweightContextProvider:
    def build(self, request: AssistantRequest, intent: Intent) -> AssistantContext:
        del request, intent
        return AssistantContext(
            capabilities=frozenset({"files:read"}),
            environment={"cwd": str(Path.cwd())},
        )


class ListDirectoryPlanner:
    def plan(
        self,
        request: AssistantRequest,
        intent: Intent,
        context: AssistantContext,
    ) -> ExecutionPlan:
        del context
        identity = (
            f"{request.request_id}:{LIST_DIRECTORY_TOOL}:{intent.entities['path']}"
        )
        action_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
        return ExecutionPlan(
            plan_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"plan:{identity}")),
            request_id=request.request_id,
            actions=(
                PlannedAction(
                    action_id=action_id,
                    tool_name=LIST_DIRECTORY_TOOL,
                    arguments={"path": intent.entities["path"]},
                    verification=VerificationSpec(kind="directory_listing"),
                    idempotency_key=f"{request.request_id}:{action_id}",
                ),
            ),
        )


class ExistingReadOnlyFileIntentClassifier:
    def __init__(
        self,
        *,
        include_create_folder: bool = False,
        include_copy_path: bool = False,
    ) -> None:
        from grandpa.files.parser import FileParser

        self._parser = FileParser()
        self._allowed_actions = {"search", "properties"}
        if include_create_folder:
            self._allowed_actions.add("create_folder")
        if include_copy_path:
            self._allowed_actions.add("copy")

    def classify(self, request: AssistantRequest) -> Intent:
        action = self._parser.parse(request.text)
        if action is None or action.action not in self._allowed_actions:
            raise IntentClassificationError(
                "The compatibility kernel only accepts migrated read-only actions.",
                safe_message="That file action has not migrated to the kernel yet.",
            )
        if action.action == "create_folder":
            return Intent(
                domain="files",
                name="create_folder",
                confidence=1.0,
                entities={"path": action.source},
            )
        if action.action == "copy":
            return Intent(
                domain="files",
                name="copy_path",
                confidence=1.0,
                entities={
                    "source": action.source,
                    "destination": action.destination,
                },
            )
        if action.action == "properties":
            return Intent(
                domain="files",
                name="stat_path",
                confidence=1.0,
                entities={"path": action.source},
            )
        return Intent(
            domain="files",
            name="search",
            confidence=1.0,
            entities={
                "query": action.query,
                "suffixes": list(action.args.get("suffixes", ())),
                "latest": bool(action.args.get("latest", False)),
                "recent": bool(action.args.get("recent", False)),
                "contains": bool(action.args.get("contains", False)),
            },
        )


class ExistingReadOnlyFileContextProvider:
    def __init__(self, roots: tuple[Path, ...], *, include_write: bool = False) -> None:
        self._roots = roots
        self._include_write = include_write

    def build(self, request: AssistantRequest, intent: Intent) -> AssistantContext:
        del request, intent
        capabilities = {"files:read"}
        if self._include_write:
            capabilities.add("files:write")
        return AssistantContext(
            capabilities=frozenset(capabilities),
            environment={"roots": [str(root) for root in self._roots]},
        )


class ExistingReadOnlyFilePlanner:
    def plan(
        self,
        request: AssistantRequest,
        intent: Intent,
        context: AssistantContext,
    ) -> ExecutionPlan:
        if intent.name == "copy_path":
            tool_name = COPY_PATH_TOOL
            verification = "file_copied"
            arguments = {
                "source": intent.entities["source"],
                "destination": intent.entities["destination"],
                "roots": list(context.environment["roots"]),
            }
        elif intent.name == "create_folder":
            tool_name = CREATE_FOLDER_TOOL
            verification = "directory_created"
            arguments = {
                "path": intent.entities["path"],
                "roots": list(context.environment["roots"]),
            }
        elif intent.name == "stat_path":
            tool_name = STAT_PATH_TOOL
            verification = "path_metadata"
            arguments = {
                "path": intent.entities["path"],
                "roots": list(context.environment["roots"]),
            }
        else:
            tool_name = SEARCH_FILES_TOOL
            verification = "file_search"
            arguments = {
                "query": intent.entities["query"],
                "roots": list(context.environment["roots"]),
                "suffixes": list(intent.entities["suffixes"]),
                "latest": intent.entities["latest"],
                "recent": intent.entities["recent"],
                "contains": intent.entities["contains"],
            }
        identity = f"{request.request_id}:{tool_name}:{arguments}"
        action_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
        return ExecutionPlan(
            plan_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"plan:{identity}")),
            request_id=request.request_id,
            actions=(
                PlannedAction(
                    action_id=action_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    verification=VerificationSpec(kind=verification),
                    idempotency_key=f"{request.request_id}:{action_id}",
                ),
            ),
        )


class InMemoryConfirmationService:
    """Single-process exact-action confirmation for compatibility tests only."""

    def __init__(self, *, ttl_seconds: int = 120) -> None:
        self._ttl_seconds = ttl_seconds
        self._pending: dict[str, ConfirmationRequest] = {}

    def issue(
        self,
        request: AssistantRequest,
        action: PlannedAction,
        decision: PolicyDecision,
    ) -> ConfirmationRequest:
        confirmation = ConfirmationRequest(
            token=secrets.token_urlsafe(24),
            request_id=request.request_id,
            session_id=request.session_id,
            action_id=action.action_id,
            action_digest=decision.action_digest,
            expires_at=utc_now() + timedelta(seconds=self._ttl_seconds),
        )
        self._pending[confirmation.token] = confirmation
        return confirmation

    def validate(
        self,
        token: str,
        request: AssistantRequest,
        action: PlannedAction,
        decision: PolicyDecision,
    ) -> bool:
        confirmation = self._pending.get(token)
        valid = bool(
            confirmation
            and confirmation.expires_at > utc_now()
            and confirmation.request_id == request.request_id
            and confirmation.session_id == request.session_id
            and confirmation.action_id == action.action_id
            and confirmation.action_digest == decision.action_digest
        )
        if valid:
            self._pending.pop(token, None)
        return valid


class EventBusAuditSink:
    """Compatibility adapter; durable audit ownership remains unchanged."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus

    def record(self, event: AuditEvent) -> None:
        self.bus.publish(EventType.TRACE_STEP, {"kernel_audit": model_to_dict(event)})


class MetadataOnlyMemoryUpdater:
    def __init__(self) -> None:
        self.update_count = 0

    def update(
        self,
        request: AssistantRequest,
        context: AssistantContext,
        plan: ExecutionPlan,
        results: tuple[ToolResult, ...],
        verifications: tuple[VerificationResult, ...],
    ) -> None:
        del request, context, plan, results, verifications
        self.update_count += 1


class IdentityResponseRenderer:
    def render(self, response: AssistantResponse) -> AssistantResponse:
        return response


def build_list_directory_kernel(
    *,
    bus: EventBus | None = None,
    confirmations: InMemoryConfirmationService | None = None,
) -> AssistantKernel:
    """Build the isolated Phase 1 harness without changing production routing."""

    event_bus = bus or get_event_bus()
    return AssistantKernel(
        normalizer=BasicRequestNormalizer(),
        classifier=ListDirectoryIntentClassifier(),
        context_provider=LightweightContextProvider(),
        planner=ListDirectoryPlanner(),
        policy=ListDirectoryPolicy(),
        confirmations=confirmations or InMemoryConfirmationService(),
        tools=SingleToolRegistry(),
        executor=ListDirectoryExecutor(),
        verifier=ListDirectoryVerifier(),
        audit=EventBusAuditSink(event_bus),
        memory=MetadataOnlyMemoryUpdater(),
        renderer=IdentityResponseRenderer(),
    )


def build_read_only_file_kernel(
    *,
    roots: tuple[Path, ...],
    bus: EventBus | None = None,
) -> AssistantKernel:
    """Build the internal kernel adapter used by FileAutomation search."""

    event_bus = bus or get_event_bus()
    return AssistantKernel(
        normalizer=BasicRequestNormalizer(),
        classifier=ExistingReadOnlyFileIntentClassifier(),
        context_provider=ExistingReadOnlyFileContextProvider(roots),
        planner=ExistingReadOnlyFilePlanner(),
        policy=FileReadOnlyPolicy(),
        confirmations=InMemoryConfirmationService(),
        tools=FileReadOnlyToolRegistry(),
        executor=FileReadOnlyExecutor(),
        verifier=FileReadOnlyVerifier(),
        audit=EventBusAuditSink(event_bus),
        memory=MetadataOnlyMemoryUpdater(),
        renderer=IdentityResponseRenderer(),
    )


def build_file_compatibility_kernel(
    *,
    roots: tuple[Path, ...],
    bus: EventBus | None = None,
) -> AssistantKernel:
    """Build the kernel adapter for migrated file operations."""

    event_bus = bus or get_event_bus()
    return AssistantKernel(
        normalizer=BasicRequestNormalizer(),
        classifier=ExistingReadOnlyFileIntentClassifier(
            include_create_folder=True,
            include_copy_path=True,
        ),
        context_provider=ExistingReadOnlyFileContextProvider(roots, include_write=True),
        planner=ExistingReadOnlyFilePlanner(),
        policy=FileCompatibilityPolicy(),
        confirmations=InMemoryConfirmationService(),
        tools=FileCompatibilityToolRegistry(),
        executor=FileCompatibilityExecutor(),
        verifier=FileCompatibilityVerifier(),
        audit=EventBusAuditSink(event_bus),
        memory=MetadataOnlyMemoryUpdater(),
        renderer=IdentityResponseRenderer(),
    )
