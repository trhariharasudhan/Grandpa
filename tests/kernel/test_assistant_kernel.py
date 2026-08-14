from __future__ import annotations

from dataclasses import replace

from grandpa.core.events import EventBus
from grandpa.kernel.assistant import AssistantKernel
from grandpa.kernel.compat import (
    BasicRequestNormalizer,
    EventBusAuditSink,
    IdentityResponseRenderer,
    InMemoryConfirmationService,
    LightweightContextProvider,
    ListDirectoryIntentClassifier,
    ListDirectoryPlanner,
    MetadataOnlyMemoryUpdater,
)
from grandpa.kernel.files import (
    ListDirectoryExecutor,
    ListDirectoryPolicy,
    ListDirectoryVerifier,
    SingleToolRegistry,
)
from grandpa.kernel.models import (
    AssistantRequest,
    AssistantSource,
    AuditStage,
    PolicyDecision,
    PolicyOutcome,
    ResponseStatus,
    RiskLevel,
    ToolStatus,
    VerificationResult,
    VerificationStatus,
)


class RecordingPolicy(ListDirectoryPolicy):
    def __init__(self, events, outcome=PolicyOutcome.ALLOW):
        self.events = events
        self.outcome = outcome

    def evaluate(self, request, context, action, action_digest):
        self.events.append("policy")
        return PolicyDecision(
            outcome=self.outcome,
            risk=RiskLevel.LOW,
            reason="Confirm this action."
            if self.outcome is PolicyOutcome.CONFIRM
            else "ok",
            action_digest=action_digest,
        )


class RecordingExecutor(ListDirectoryExecutor):
    def __init__(self, events, *, raises=False):
        self.events = events
        self.raises = raises
        self.calls = 0

    def execute(self, *args, **kwargs):
        self.calls += 1
        self.events.append("executor")
        if self.raises:
            raise OSError("simulated execution failure")
        return super().execute(*args, **kwargs)


class RecordingAudit:
    def __init__(self, events, fail_stage=None):
        self.events = events
        self.fail_stage = fail_stage
        self.records = []

    def record(self, event):
        self.events.append(f"audit:{event.stage.value}")
        if event.stage is self.fail_stage:
            raise OSError("simulated audit failure")
        self.records.append(event)


class RaisingPolicy:
    def evaluate(self, *args, **kwargs):
        raise RuntimeError("simulated policy failure")


class WrongDigestPolicy:
    def evaluate(self, request, context, action, action_digest):
        return PolicyDecision(
            outcome=PolicyOutcome.ALLOW,
            risk=RiskLevel.LOW,
            reason="wrong binding",
            action_digest=f"wrong-{action_digest}",
        )


class FailingVerifier(ListDirectoryVerifier):
    def verify(self, *args, **kwargs):
        return VerificationResult(
            VerificationStatus.FAILED, "Independent verification failed."
        )


def _kernel(
    *,
    policy=None,
    executor=None,
    audit=None,
    verifier=None,
    confirmations=None,
):
    events = []
    actual_policy = policy or RecordingPolicy(events)
    actual_executor = executor or RecordingExecutor(events)
    actual_audit = audit or RecordingAudit(events)
    return (
        AssistantKernel(
            normalizer=BasicRequestNormalizer(),
            classifier=ListDirectoryIntentClassifier(),
            context_provider=LightweightContextProvider(),
            planner=ListDirectoryPlanner(),
            policy=actual_policy,
            confirmations=confirmations or InMemoryConfirmationService(),
            tools=SingleToolRegistry(),
            executor=actual_executor,
            verifier=verifier or ListDirectoryVerifier(),
            audit=actual_audit,
            memory=MetadataOnlyMemoryUpdater(),
            renderer=IdentityResponseRenderer(),
        ),
        events,
        actual_executor,
        actual_audit,
    )


def _request(tmp_path):
    return AssistantRequest(
        request_id="request-1",
        session_id="session-1",
        source=AssistantSource.CLI,
        text=f"List files in {tmp_path}",
    )


def test_lifecycle_orders_policy_and_audit_before_execution(tmp_path):
    kernel, events, _, audit = _kernel()

    response = kernel.handle(_request(tmp_path))

    assert response.status is ResponseStatus.COMPLETED
    assert events.index("policy") < events.index("audit:execution_started")
    assert events.index("audit:execution_started") < events.index("executor")
    stages = [event.stage for event in audit.records]
    assert stages == [
        AuditStage.REQUEST_RECEIVED,
        AuditStage.PLAN_CREATED,
        AuditStage.ACTION_ATTEMPTED,
        AuditStage.POLICY_EVALUATED,
        AuditStage.EXECUTION_STARTED,
        AuditStage.EXECUTION_FINISHED,
        AuditStage.VERIFICATION_FINISHED,
        AuditStage.MEMORY_UPDATED,
        AuditStage.REQUEST_COMPLETED,
    ]


def test_blocked_policy_never_calls_executor(tmp_path):
    events = []
    policy = RecordingPolicy(events, PolicyOutcome.BLOCK)
    executor = RecordingExecutor(events)
    kernel, _, _, _ = _kernel(policy=policy, executor=executor)

    response = kernel.handle(_request(tmp_path))

    assert response.status is ResponseStatus.BLOCKED
    assert executor.calls == 0


def test_policy_exception_fails_closed(tmp_path):
    events = []
    executor = RecordingExecutor(events)
    kernel, _, _, _ = _kernel(policy=RaisingPolicy(), executor=executor)

    response = kernel.handle(_request(tmp_path))

    assert response.status is ResponseStatus.FAILED
    assert executor.calls == 0


def test_policy_decision_bound_to_wrong_digest_cannot_execute(tmp_path):
    events = []
    executor = RecordingExecutor(events)
    kernel, _, _, _ = _kernel(policy=WrongDigestPolicy(), executor=executor)

    response = kernel.handle(_request(tmp_path))

    assert response.status is ResponseStatus.FAILED
    assert executor.calls == 0


def test_confirmation_required_and_invalid_token_never_execute(tmp_path):
    events = []
    policy = RecordingPolicy(events, PolicyOutcome.CONFIRM)
    executor = RecordingExecutor(events)
    confirmations = InMemoryConfirmationService()
    kernel, _, _, _ = _kernel(
        policy=policy,
        executor=executor,
        confirmations=confirmations,
    )
    request = _request(tmp_path)

    initial = kernel.handle(request)
    invalid = kernel.handle(replace(request, confirmation_token="wrong"))

    assert initial.status is ResponseStatus.CONFIRMATION_REQUIRED
    assert invalid.status is ResponseStatus.CONFIRMATION_REQUIRED
    assert executor.calls == 0


def test_valid_exact_action_confirmation_executes_once(tmp_path):
    events = []
    policy = RecordingPolicy(events, PolicyOutcome.CONFIRM)
    executor = RecordingExecutor(events)
    confirmations = InMemoryConfirmationService()
    kernel, _, _, _ = _kernel(
        policy=policy,
        executor=executor,
        confirmations=confirmations,
    )
    request = _request(tmp_path)
    pending = kernel.handle(request)

    confirmed = kernel.handle(
        replace(request, confirmation_token=pending.confirmation.token)
    )
    replayed = kernel.handle(
        replace(request, confirmation_token=pending.confirmation.token)
    )

    assert confirmed.status is ResponseStatus.COMPLETED
    assert replayed.status is ResponseStatus.CONFIRMATION_REQUIRED
    assert executor.calls == 1


def test_confirmation_for_changed_action_is_rejected(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    events = []
    policy = RecordingPolicy(events, PolicyOutcome.CONFIRM)
    executor = RecordingExecutor(events)
    confirmations = InMemoryConfirmationService()
    kernel, _, _, _ = _kernel(
        policy=policy,
        executor=executor,
        confirmations=confirmations,
    )
    request = _request(first)
    pending = kernel.handle(request)

    changed = kernel.handle(
        replace(
            request,
            text=f"List files in {second}",
            confirmation_token=pending.confirmation.token,
        )
    )

    assert changed.status is ResponseStatus.CONFIRMATION_REQUIRED
    assert executor.calls == 0


def test_audit_failure_before_execution_fails_closed(tmp_path):
    events = []
    executor = RecordingExecutor(events)
    audit = RecordingAudit(events, AuditStage.EXECUTION_STARTED)
    kernel, _, _, _ = _kernel(executor=executor, audit=audit)

    response = kernel.handle(_request(tmp_path))

    assert response.status is ResponseStatus.FAILED
    assert executor.calls == 0


def test_executor_exception_produces_safe_failure(tmp_path):
    events = []
    executor = RecordingExecutor(events, raises=True)
    kernel, _, _, _ = _kernel(executor=executor)

    response = kernel.handle(_request(tmp_path))

    assert response.status is ResponseStatus.FAILED
    assert response.text == "The tool could not complete the action."
    assert "simulated" not in response.text


def test_verification_failure_is_not_reported_as_success(tmp_path):
    kernel, _, _, _ = _kernel(verifier=FailingVerifier())

    response = kernel.handle(_request(tmp_path))

    assert response.status is ResponseStatus.FAILED
    assert response.text == "Independent verification failed."
    assert response.actions[0].status is ToolStatus.SUCCEEDED


def test_event_bus_compatibility_sink_emits_structured_events(tmp_path):
    bus = EventBus(record_history=True)
    kernel = AssistantKernel(
        normalizer=BasicRequestNormalizer(),
        classifier=ListDirectoryIntentClassifier(),
        context_provider=LightweightContextProvider(),
        planner=ListDirectoryPlanner(),
        policy=ListDirectoryPolicy(),
        confirmations=InMemoryConfirmationService(),
        tools=SingleToolRegistry(),
        executor=ListDirectoryExecutor(),
        verifier=ListDirectoryVerifier(),
        audit=EventBusAuditSink(bus),
        memory=MetadataOnlyMemoryUpdater(),
        renderer=IdentityResponseRenderer(),
    )

    kernel.handle(_request(tmp_path))

    payloads = [event.data["kernel_audit"] for event in bus.history]
    assert payloads[0]["stage"] == "request_received"
    assert payloads[-1]["stage"] == "request_completed"
    assert all("confirmation_token" not in str(payload) for payload in payloads)
