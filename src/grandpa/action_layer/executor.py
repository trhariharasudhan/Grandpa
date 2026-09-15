"""The one place actions execute in the new layer.

There is no second path, no bypass and no "internal" variant that skips a
check. Everything -- the CLI flag, the tool loop, whatever comes after --
arrives at :func:`execute`, which always does the same five things in the same
order: look the action up, validate its parameters, obtain confirmation if the
catalogue says it is needed, call the implementation, and write an audit
record. A caller cannot opt out of any of them, because there is nothing else
to call.

Failures are returned, never raised. A tool loop feeding a model has to be
able to hand a failure back as a result so the model can recover or explain,
and an exception escaping into that loop would end the conversation instead.

Nothing here imports a legacy stack at module scope. Implementations are
dotted-path strings resolved at the moment one is actually called, so
importing this module stays as cheap as importing the contract.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from grandpa.action_layer.catalogue import ActionSpec, Binding, get
from grandpa.action_layer.model import ActionRequest, ActionResult, RiskLevel

__all__ = ["ConfirmCallback", "audit_log_path", "execute"]

logger = logging.getLogger(__name__)

ConfirmCallback = Callable[[str, Mapping[str, Any], RiskLevel], bool]
"""Asked before a confirmable action runs: ``(action, parameters, risk)``.

It receives the *resolved* parameters -- what will actually be done, defaults
filled in -- so whatever it shows the user is what happens. Returning anything
falsy refuses.
"""

# Error codes on a failed ActionResult. They are part of the contract: a caller
# (or a model reading the result) can branch on them without parsing prose.
UNKNOWN_ACTION = "unknown_action"
INVALID_PARAMETERS = "invalid_parameters"
CONFIRMATION_REQUIRED = "confirmation_required"
CONFIRMATION_DECLINED = "confirmation_declined"
BLOCKED = "blocked"
IMPLEMENTATION_UNAVAILABLE = "implementation_unavailable"
EXECUTION_FAILED = "execution_failed"

_SUCCESS_STATUSES = frozenset({"completed", "handled", "partial_success", "dry_run"})


# --- the request shape the existing services expect ---------------------------


@dataclass(frozen=True)
class _ServiceRequest:
    """What ``pc_control.LocalActionRequest`` looks like from the outside.

    The desktop services only ever read ``.target`` and ``.args``; none of them
    type-check what they were handed. Duck-typing the shape here is what lets
    the layer call them without importing ``pc_control`` -- and the field names
    match, so if a service is ever tightened to require the real class this
    stops working loudly rather than subtly.
    """

    action_type: str
    target: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    require_approval: bool = False
    dry_run: bool = False


# --- resolving an implementation ---------------------------------------------


def _resolve(dotted: str) -> tuple[Any, Any]:
    """Return ``(target, owner)`` for a dotted path.

    ``owner`` is the class a method was found on, or ``None`` for a plain
    function. Imports happen here and nowhere else, which is why importing this
    module pulls in no legacy stack.
    """
    parts = dotted.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        try:
            module = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        target: Any = module
        owner: Any = None
        for attribute in parts[cut:]:
            owner = target
            target = getattr(target, attribute)
        return target, owner if isinstance(owner, type) else None
    raise ModuleNotFoundError(f"no importable module prefix in {dotted!r}")


# --- parameter validation ----------------------------------------------------


_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


def _type_matches(declared: str, value: Any) -> bool:
    expected = _TYPE_CHECKS.get(declared)
    if expected is None:
        return True
    if declared in {"integer", "number"} and isinstance(value, bool):
        return False  # bools are ints in Python; they are not numbers in JSON
    return isinstance(value, expected)


def _validate(spec: ActionSpec, parameters: Mapping[str, Any]) -> list[str]:
    """Return every problem with ``parameters``, or an empty list."""
    schema = spec.parameters
    properties: Mapping[str, Any] = schema.get("properties", {})
    problems: list[str] = []

    for name in schema.get("required", []):
        if name not in parameters:
            problems.append(f"missing required parameter {name!r}")

    for name, value in parameters.items():
        if name not in properties:
            allowed = ", ".join(sorted(properties)) or "none"
            problems.append(f"unknown parameter {name!r} (accepted: {allowed})")
            continue
        rules = properties[name]
        declared = rules.get("type", "")
        if not _type_matches(declared, value):
            problems.append(f"{name!r} must be {declared}, got {type(value).__name__}")
            continue
        if "enum" in rules and value not in rules["enum"]:
            problems.append(f"{name!r} must be one of {rules['enum']}, got {value!r}")
        if "minimum" in rules and value < rules["minimum"]:
            problems.append(f"{name!r} must be at least {rules['minimum']}")
        if "maximum" in rules and value > rules["maximum"]:
            problems.append(f"{name!r} must be at most {rules['maximum']}")
        if declared == "array":
            if len(value) < rules.get("minItems", 0):
                problems.append(f"{name!r} needs at least {rules['minItems']} item(s)")
            item_type = rules.get("items", {}).get("type", "")
            for index, item in enumerate(value):
                if not _type_matches(item_type, item):
                    problems.append(f"{name}[{index}] must be {item_type}")
    return problems


def _resolved_parameters(
    spec: ActionSpec, parameters: Mapping[str, Any]
) -> dict[str, Any]:
    """What will actually be done: what was asked for, plus schema defaults."""
    resolved = {
        name: rules["default"]
        for name, rules in spec.parameters.get("properties", {}).items()
        if "default" in rules
    }
    resolved.update(parameters)
    return resolved


# --- calling an implementation -----------------------------------------------


def _call(spec: ActionSpec, parameters: Mapping[str, Any]) -> Any:
    """Adapt the layer's parameters to whatever shape the implementation wants."""
    implementation, owner = _resolve(spec.implementation)
    action = spec.action_alias or spec.name
    target = ""
    args = dict(parameters)
    if spec.target_parameter is not None:
        target = str(args.pop(spec.target_parameter, "") or "")

    if spec.binding is Binding.ACTION_TARGET:
        return implementation(action, target)

    service_request = _ServiceRequest(action_type=spec.name, target=target, args=args)
    if spec.binding is Binding.REQUEST_ONLY:
        return implementation(service_request)

    # The remaining bindings name a method, so the class needs an instance.
    # Every desktop control service is stateless and no-arg constructible;
    # test_executor.py asserts that so it cannot quietly stop being true.
    instance = owner() if owner is not None else None
    if spec.binding is Binding.REQUEST_ACTION:
        return implementation(instance, service_request, action)
    if spec.binding is Binding.SERVICE_REQUEST:
        return implementation(instance, service_request)
    if spec.binding is Binding.SERVICE_ONLY:
        return implementation(instance)
    if spec.binding is Binding.REQUEST_ACTION_PLATFORM:
        return implementation(instance, service_request, action, platform=sys.platform)
    if spec.binding is Binding.ACTION_PLATFORM:
        return implementation(instance, action, platform=sys.platform)
    if spec.binding is Binding.PLATFORM_ONLY:
        return implementation(instance, platform=sys.platform)
    raise NotImplementedError(f"no adapter for binding {spec.binding}")


def _as_result(spec: ActionSpec, returned: Any) -> ActionResult:
    """Wrap whatever an implementation returned in an ActionResult.

    The two existing result types -- ``LocalActionResponse`` and
    ``BrowserActionResult`` -- are read by attribute rather than by import, for
    the same reason as everything else here.
    """
    if isinstance(returned, ActionResult):
        return returned

    status = str(getattr(returned, "status", "") or "")
    ok = getattr(returned, "ok", None)
    if ok is None:
        ok = status in _SUCCESS_STATUSES
    message = str(getattr(returned, "message", "") or "")
    error = getattr(returned, "error", None)
    if not ok and not error:
        error = status or EXECUTION_FAILED

    data: dict[str, Any] = {"status": status} if status else {}
    # pc_control's responses carry "evidence"; the vision engine's carry "data".
    for attribute in ("evidence", "data"):
        extra = getattr(returned, attribute, None)
        if isinstance(extra, Mapping):
            data.update(extra)
    if not isinstance(returned, (str, bytes)) and not hasattr(returned, "status"):
        data["returned"] = repr(returned)

    return ActionResult(
        success=bool(ok),
        message=message or f"{spec.name} finished.",
        data=data,
        error=None if ok else str(error),
    )


# --- the audit trail ----------------------------------------------------------


def audit_log_path() -> Path:
    """The same JSONL log ``pc_control`` writes, found the same way.

    ``pc_control._audit`` itself is not reusable from here: it is private, it
    takes two ``pc_control`` dataclasses, and importing it would re-couple the
    layer to the stack it replaces -- the thing
    ``tests/action_layer/test_import_isolation.py`` exists to prevent. So the
    layer reuses the *log*, not the function: same location, same resolution
    order (``GRANDPA_LOCAL_ACTION_LOG``, else ``GRANDPA_RUNTIME_DIR``), same
    one-JSON-object-per-line format, so ``read_recent_audit_entries`` and the
    rotation policy keep working over both stacks' records.
    """
    configured = os.environ.get("GRANDPA_LOCAL_ACTION_LOG")
    if configured:
        return Path(configured)
    return (
        Path(os.environ.get("GRANDPA_RUNTIME_DIR", "runtime"))
        / "logs"
        / ("local_actions.jsonl")
    )


def _audit(
    request: ActionRequest,
    *,
    risk: RiskLevel,
    confirmed: bool | None,
    result: ActionResult,
) -> None:
    """Record one attempt. Never raises: a log that fails must not lose work."""
    record = {
        "timestamp": time.time(),
        "source": "action_layer",
        "action_type": request.action,
        "origin": request.origin.value,
        "risk_level": risk.value,
        "confirmed": confirmed,
        "ok": result.success,
        "status": "completed" if result.success else (result.error or "failed"),
        "error": result.error,
    }
    logger.info("action_layer.execute %s", json.dumps(record, ensure_ascii=True))
    try:
        path = audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    except OSError as exc:  # pragma: no cover - depends on the filesystem
        logger.warning("could not write the action audit log: %s", exc)


# --- the entry point ----------------------------------------------------------


def execute(
    request: ActionRequest,
    confirm_callback: ConfirmCallback | None = None,
) -> ActionResult:
    """Perform one catalogued action, or explain why it was not performed."""
    try:
        spec = get(request.action)
    except KeyError:
        result = ActionResult.failed(
            UNKNOWN_ACTION,
            message=f"I have no action called {request.action!r}.",
            action=request.action,
        )
        _audit(request, risk=request.risk, confirmed=None, result=result)
        return result

    if spec.risk is RiskLevel.BLOCKED:  # pragma: no cover - none are catalogued
        result = ActionResult.failed(
            BLOCKED, message=f"{spec.name} is blocked and is never performed."
        )
        _audit(request, risk=spec.risk, confirmed=None, result=result)
        return result

    problems = _validate(spec, request.parameters)
    if problems:
        result = ActionResult.failed(
            INVALID_PARAMETERS,
            message=f"{spec.name}: " + "; ".join(problems),
            problems=problems,
        )
        _audit(request, risk=spec.risk, confirmed=None, result=result)
        return result

    parameters = _resolved_parameters(spec, request.parameters)

    # The catalogue decides, and a caller may only be stricter, never looser.
    confirmed: bool | None = None
    if spec.requires_confirmation or request.requires_confirmation:
        if confirm_callback is None:
            result = ActionResult.failed(
                CONFIRMATION_REQUIRED,
                message=(
                    f"{spec.name} needs the user's confirmation and no way to ask "
                    "for it was provided, so nothing was done."
                ),
            )
            _audit(request, risk=spec.risk, confirmed=None, result=result)
            return result
        try:
            confirmed = bool(confirm_callback(spec.name, parameters, spec.risk))
        except Exception as exc:
            result = ActionResult.failed(
                CONFIRMATION_DECLINED,
                message=f"{spec.name} was not confirmed: {exc}",
            )
            _audit(request, risk=spec.risk, confirmed=False, result=result)
            return result
        if not confirmed:
            result = ActionResult.failed(
                CONFIRMATION_DECLINED,
                message=f"{spec.name} was declined, so nothing was done.",
            )
            _audit(request, risk=spec.risk, confirmed=False, result=result)
            return result

    try:
        returned = _call(spec, parameters)
    except (ImportError, AttributeError, ModuleNotFoundError) as exc:
        result = ActionResult.failed(
            IMPLEMENTATION_UNAVAILABLE,
            message=f"{spec.name} cannot run here: {exc}",
        )
        _audit(request, risk=spec.risk, confirmed=confirmed, result=result)
        return result
    except Exception as exc:
        result = ActionResult.failed(
            EXECUTION_FAILED,
            message=f"{spec.name} failed: {exc}",
            exception=type(exc).__name__,
        )
        _audit(request, risk=spec.risk, confirmed=confirmed, result=result)
        return result

    result = _as_result(spec, returned)
    _audit(request, risk=spec.risk, confirmed=confirmed, result=result)
    return result
