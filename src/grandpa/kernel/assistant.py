"""Canonical coordinator for Grandpa request execution."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any, Mapping

from grandpa.kernel.errors import (
    AuditWriteError,
    ConfirmationValidationError,
    KernelError,
    MemoryUpdateError,
    PolicyEvaluationError,
    RequestNormalizationError,
    ResponseRenderingError,
    SecurityInvariantError,
    ToolArgumentValidationError,
    ToolExecutionError,
    ToolNotFoundError,
)
from grandpa.kernel.interfaces import (
    AuditSink,
    ConfirmationService,
    ContextProvider,
    IntentClassifier,
    MemoryUpdater,
    Planner,
    PolicyEngine,
    RequestNormalizer,
    ResponseRenderer,
    ToolExecutor,
    ToolRegistry,
    Verifier,
)
from grandpa.kernel.models import (
    AssistantContext,
    AssistantRequest,
    AssistantResponse,
    AuditEvent,
    AuditStage,
    ExecutionAuthorization,
    ExecutionPlan,
    PlannedAction,
    PolicyOutcome,
    ResponseStatus,
    ToolResult,
    ToolStatus,
    VerificationResult,
    VerificationStatus,
    action_digest,
)


class AssistantKernel:
    """Coordinate typed services without implementing domain behavior."""

    def __init__(
        self,
        *,
        normalizer: RequestNormalizer,
        classifier: IntentClassifier,
        context_provider: ContextProvider,
        planner: Planner,
        policy: PolicyEngine,
        confirmations: ConfirmationService,
        tools: ToolRegistry,
        executor: ToolExecutor,
        verifier: Verifier,
        audit: AuditSink,
        memory: MemoryUpdater,
        renderer: ResponseRenderer,
    ) -> None:
        self._normalizer = normalizer
        self._classifier = classifier
        self._context_provider = context_provider
        self._planner = planner
        self._policy = policy
        self._confirmations = confirmations
        self._tools = tools
        self._executor = executor
        self._verifier = verifier
        self._audit = audit
        self._memory = memory
        self._renderer = renderer

    def handle(self, request: AssistantRequest) -> AssistantResponse:
        """Run one request through the canonical fail-closed lifecycle."""

        plan: ExecutionPlan | None = None
        results: list[ToolResult] = []
        verifications: list[VerificationResult] = []
        active_request = request
        context = AssistantContext()
        try:
            self._record(request, None, AuditStage.REQUEST_RECEIVED, "received")
            active_request = self._normalizer.normalize(request)
            self._assert_request_identity(request, active_request)
            intent = self._classifier.classify(active_request)
            context = self._context_provider.build(active_request, intent)
            plan = self._planner.plan(active_request, intent, context)
            if plan.request_id != active_request.request_id:
                raise SecurityInvariantError("Plan request identity does not match.")
            self._record(
                active_request,
                None,
                AuditStage.PLAN_CREATED,
                "planned",
                {"plan_id": plan.plan_id, "action_count": len(plan.actions)},
            )

            succeeded_actions: set[str] = set()
            for action in plan.actions:
                missing_dependencies = set(action.dependencies) - succeeded_actions
                if missing_dependencies:
                    raise SecurityInvariantError(
                        "Action dependencies have not completed successfully."
                    )
                terminal = self._run_action(
                    active_request,
                    context,
                    plan,
                    action,
                    results,
                    verifications,
                )
                if terminal is not None:
                    return terminal
                succeeded_actions.add(action.action_id)

            self._update_memory(
                active_request,
                context,
                plan,
                tuple(results),
                tuple(verifications),
            )
            self._record(
                active_request,
                None,
                AuditStage.REQUEST_COMPLETED,
                "completed",
                {"plan_id": plan.plan_id},
            )
            text = results[-1].safe_message if results else "Request completed."
            return self._render(
                AssistantResponse(
                    status=ResponseStatus.COMPLETED,
                    text=text,
                    plan_id=plan.plan_id,
                    actions=tuple(results),
                )
            )
        except KernelError as exc:
            return self._failure_response(active_request, plan, results, exc)
        except Exception as exc:
            error = KernelError(
                f"Unexpected kernel failure: {type(exc).__name__}: {exc}"
            )
            return self._failure_response(active_request, plan, results, error)

    def _run_action(
        self,
        request: AssistantRequest,
        context: AssistantContext,
        plan: ExecutionPlan,
        action: PlannedAction,
        results: list[ToolResult],
        verifications: list[VerificationResult],
    ) -> AssistantResponse | None:
        self._record(
            request,
            action,
            AuditStage.ACTION_ATTEMPTED,
            "attempted",
            {"tool_name": action.tool_name},
        )
        try:
            tool = self._tools.resolve(action.tool_name)
        except KernelError:
            raise
        except Exception as exc:
            raise ToolNotFoundError(
                f"Tool resolution failed for {action.tool_name}: {exc}",
                safe_message="The requested capability is not available.",
            ) from exc

        try:
            canonical_arguments = tool.validate_arguments(action.arguments)
        except KernelError:
            raise
        except Exception as exc:
            raise ToolArgumentValidationError(
                f"Invalid arguments for {action.tool_name}: {exc}",
                safe_message=f"Invalid arguments for {action.tool_name}.",
            ) from exc

        canonical_action = replace(action, arguments=canonical_arguments)
        digest = action_digest(request, canonical_action, canonical_arguments)
        try:
            decision = self._policy.evaluate(
                request,
                context,
                canonical_action,
                digest,
            )
        except KernelError:
            raise
        except Exception as exc:
            raise PolicyEvaluationError(f"Policy evaluation failed: {exc}") from exc
        if decision.action_digest != digest:
            raise SecurityInvariantError("Policy decision has the wrong action digest.")

        self._record(
            request,
            canonical_action,
            AuditStage.POLICY_EVALUATED,
            decision.outcome.value,
            {
                "risk": decision.risk.value,
                "action_digest": digest,
                "reason": decision.reason,
            },
        )
        if decision.outcome is PolicyOutcome.BLOCK:
            result = ToolResult(
                status=ToolStatus.BLOCKED,
                data={},
                safe_message=decision.reason or "That action is blocked.",
            )
            results.append(result)
            self._record(
                request,
                canonical_action,
                AuditStage.EXECUTION_FINISHED,
                "blocked",
            )
            return self._terminal_response(
                request,
                context,
                plan,
                results,
                verifications,
                ResponseStatus.BLOCKED,
                result.safe_message,
            )

        confirmation_validated = False
        if decision.outcome is PolicyOutcome.CONFIRM:
            if request.confirmation_token:
                try:
                    confirmation_validated = self._confirmations.validate(
                        request.confirmation_token,
                        request,
                        canonical_action,
                        decision,
                    )
                except Exception as exc:
                    raise ConfirmationValidationError(
                        f"Confirmation validation failed: {exc}"
                    ) from exc
            if not confirmation_validated:
                confirmation = self._confirmations.issue(
                    request,
                    canonical_action,
                    decision,
                )
                self._record(
                    request,
                    canonical_action,
                    AuditStage.CONFIRMATION_REQUIRED,
                    "required",
                    {"action_digest": digest},
                )
                return self._render(
                    AssistantResponse(
                        status=ResponseStatus.CONFIRMATION_REQUIRED,
                        text=decision.reason or "This action requires confirmation.",
                        plan_id=plan.plan_id,
                        confirmation=confirmation,
                        actions=tuple(results),
                    )
                )

        authorization = ExecutionAuthorization(
            decision=decision,
            confirmation_validated=confirmation_validated,
        )
        self._record(
            request,
            canonical_action,
            AuditStage.EXECUTION_STARTED,
            "authorized",
            {"action_digest": digest},
        )
        try:
            result = self._executor.execute(
                tool,
                canonical_action,
                canonical_arguments,
                context,
                authorization,
            )
        except Exception as exc:
            result = ToolResult(
                status=ToolStatus.FAILED,
                data={},
                safe_message="The tool could not complete the action.",
            )
            self._record(
                request,
                canonical_action,
                AuditStage.EXECUTION_FINISHED,
                "failed",
                {"error_type": type(exc).__name__},
            )
            results.append(result)
            error = ToolExecutionError(
                f"Tool execution failed: {exc}",
                safe_message=result.safe_message,
            )
            return self._failure_response(request, plan, results, error)

        results.append(result)
        self._record(
            request,
            canonical_action,
            AuditStage.EXECUTION_FINISHED,
            result.status.value,
        )
        if result.status is not ToolStatus.SUCCEEDED:
            return self._terminal_response(
                request,
                context,
                plan,
                results,
                verifications,
                ResponseStatus.FAILED,
                result.safe_message,
            )

        if canonical_action.verification is None:
            verification = VerificationResult(
                status=VerificationStatus.UNVERIFIED,
                reason="No verification was requested.",
            )
        else:
            try:
                verification = self._verifier.verify(
                    canonical_action,
                    canonical_arguments,
                    result,
                    context,
                )
            except Exception as exc:
                verification = VerificationResult(
                    status=VerificationStatus.FAILED,
                    reason="Result verification failed unexpectedly.",
                )
                self._record(
                    request,
                    canonical_action,
                    AuditStage.VERIFICATION_FINISHED,
                    "failed",
                    {"error_type": type(exc).__name__},
                )
                verifications.append(verification)
                return self._terminal_response(
                    request,
                    context,
                    plan,
                    results,
                    verifications,
                    ResponseStatus.FAILED,
                    verification.reason,
                )

        verifications.append(verification)
        self._record(
            request,
            canonical_action,
            AuditStage.VERIFICATION_FINISHED,
            verification.status.value,
            {"reason": verification.reason},
        )
        if verification.status is VerificationStatus.FAILED:
            return self._terminal_response(
                request,
                context,
                plan,
                results,
                verifications,
                ResponseStatus.FAILED,
                verification.reason,
            )
        return None

    def _terminal_response(
        self,
        request: AssistantRequest,
        context: AssistantContext,
        plan: ExecutionPlan,
        results: list[ToolResult],
        verifications: list[VerificationResult],
        status: ResponseStatus,
        text: str,
    ) -> AssistantResponse:
        self._update_memory(
            request,
            context,
            plan,
            tuple(results),
            tuple(verifications),
        )
        self._record(
            request,
            None,
            (
                AuditStage.REQUEST_FAILED
                if status is ResponseStatus.FAILED
                else AuditStage.REQUEST_COMPLETED
            ),
            status.value,
            {"plan_id": plan.plan_id},
        )
        return self._render(
            AssistantResponse(
                status=status,
                text=text,
                plan_id=plan.plan_id,
                actions=tuple(results),
            )
        )

    def _update_memory(
        self,
        request: AssistantRequest,
        context: AssistantContext,
        plan: ExecutionPlan,
        results: tuple[ToolResult, ...],
        verifications: tuple[VerificationResult, ...],
    ) -> None:
        try:
            self._memory.update(request, context, plan, results, verifications)
        except Exception as exc:
            raise MemoryUpdateError(f"Memory update failed: {exc}") from exc
        self._record(
            request,
            None,
            AuditStage.MEMORY_UPDATED,
            "completed",
            {"stored_semantic_memory": False},
        )

    def _record(
        self,
        request: AssistantRequest,
        action: PlannedAction | None,
        stage: AuditStage,
        outcome: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            request_id=request.request_id,
            action_id=action.action_id if action else None,
            stage=stage,
            outcome=outcome,
            redacted_payload=_redact(payload or {}),
        )
        try:
            self._audit.record(event)
        except Exception as exc:
            raise AuditWriteError(
                f"Audit write failed at {stage.value}: {exc}"
            ) from exc

    def _failure_response(
        self,
        request: AssistantRequest,
        plan: ExecutionPlan | None,
        results: list[ToolResult],
        error: KernelError,
    ) -> AssistantResponse:
        if not isinstance(error, AuditWriteError):
            try:
                self._record(
                    request,
                    None,
                    AuditStage.REQUEST_FAILED,
                    "failed",
                    {"error_type": type(error).__name__},
                )
            except AuditWriteError:
                pass
        response = AssistantResponse(
            status=ResponseStatus.FAILED,
            text=error.safe_message,
            plan_id=plan.plan_id if plan else None,
            actions=tuple(results),
        )
        try:
            return self._render(response)
        except ResponseRenderingError:
            return response

    def _render(self, response: AssistantResponse) -> AssistantResponse:
        try:
            return self._renderer.render(response)
        except Exception as exc:
            raise ResponseRenderingError(f"Response rendering failed: {exc}") from exc

    @staticmethod
    def _assert_request_identity(
        original: AssistantRequest,
        normalized: AssistantRequest,
    ) -> None:
        if (
            original.request_id != normalized.request_id
            or original.session_id != normalized.session_id
            or original.source is not normalized.source
        ):
            raise RequestNormalizationError(
                "Request normalization changed security identity."
            )


_SENSITIVE_KEYS = ("password", "secret", "token", "otp", "card", "credential")


def _redact(value: Any, *, key: str = "") -> Any:
    if any(marker in key.casefold() for marker in _SENSITIVE_KEYS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_redact(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
