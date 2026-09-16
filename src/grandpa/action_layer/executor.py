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

from grandpa.action_layer.catalogue import ActionSpec, Binding, Confirmation, get
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


def _call_notes(
    spec: ActionSpec,
    implementation: Any,
    owner: Any,
    action: str,
    parameters: Mapping[str, Any],
    confirmed: bool,
) -> Any:
    """Call ``NotesAutomation.execute`` with a real NotesAction.

    ``confirmed`` is the consent the executor already obtained. It is not a
    bypass: the only notes action that needs asking is ``notes_delete``, the
    catalogue rates it HIGH, so it cannot reach here without a yes. Passing it
    stops notes prompting a second time for consent the layer already holds --
    the double prompt that made chat's old notes branch print a question and
    then send the answer to the model.
    """
    from grandpa.notes.models import NotesAction

    fields: dict[str, Any] = dict(parameters)
    if "tags" in fields:
        fields["tags"] = tuple(fields["tags"])
    # Notes finds an existing note by ``query or title``, so whichever parameter
    # identifies one has to arrive as both.
    if spec.target_parameter and fields.get(spec.target_parameter):
        fields["query"] = fields[spec.target_parameter]

    notes_action = NotesAction(action=action, **fields)
    instance = owner() if owner is not None else None
    return implementation(instance, notes_action, confirmed=confirmed)


def _call_downloads(
    spec: ActionSpec,
    implementation: Any,
    owner: Any,
    action: str,
    parameters: Mapping[str, Any],
    confirmed: bool,
    confirm_callback: ConfirmCallback | None,
) -> Any:
    """Call ``DownloadsAutomation.execute`` with a real DownloadAction.

    Downloads asks for itself (:data:`Confirmation.DOMAIN`), so the layer's
    callback is handed over rather than used up front. Downloads calls it with
    the action and the files it found, which is the only point at which
    "Archive 1 download (6 B)?" can be written -- and the only point at which
    "one file, do not bother asking" can be decided.
    """
    from grandpa.downloads.models import DownloadAction

    fields = dict(parameters)
    if spec.target_parameter and fields.get(spec.target_parameter):
        fields.setdefault("selector", fields[spec.target_parameter])
        fields.pop(spec.target_parameter, None)

    download_action = DownloadAction(action=action, **fields)
    instance = owner() if owner is not None else None

    forwarded = None
    if confirm_callback is not None and not confirmed:

        def forwarded(asked_action: Any, items: Any) -> bool:
            from grandpa.downloads.formatter import format_operation_plan

            plan = format_operation_plan(asked_action.action, items).removesuffix(
                " [y/N]"
            )
            # The domain's own sentence, asked with the layer's callback, so
            # the wording a user sees does not change with the migration.
            return bool(
                confirm_callback(
                    spec.name, {**dict(parameters), "_plan": plan}, spec.risk
                )
            )

    return implementation(
        instance, download_action, confirmed=confirmed, confirm=forwarded
    )


def _call_google(
    spec: ActionSpec,
    implementation: Any,
    owner: Any,
    action: str,
    parameters: Mapping[str, Any],
    confirmed: bool,
    confirm_callback: ConfirmCallback | None,
) -> Any:
    """Call calendar or gmail with their own parsed-action dataclass.

    Same arrangement as downloads: the domain decides whether to ask and writes
    the sentence, because only it knows which event or message was matched.
    """
    if spec.binding is Binding.CALENDAR_ACTION:
        from grandpa.calendar.automation import confirmation_message as plan_for
        from grandpa.calendar.models import CalendarAction as DomainAction
    else:
        from grandpa.gmail.automation import confirmation_message as plan_for
        from grandpa.gmail.models import GmailAction as DomainAction

    domain_action = DomainAction(action=action, **dict(parameters))
    instance = owner() if owner is not None else None

    forwarded = None
    if confirm_callback is not None and not confirmed:

        def forwarded(asked_action: Any) -> bool:
            plan = str(plan_for(asked_action)).removesuffix(" [y/N]")
            return bool(
                confirm_callback(
                    spec.name, {**dict(parameters), "_plan": plan}, spec.risk
                )
            )

    return implementation(
        instance, domain_action, confirmed=confirmed, confirm=forwarded
    )


def _call_application(
    spec: ActionSpec,
    implementation: Any,
    owner: Any,
    action: str,
    parameters: Mapping[str, Any],
    confirmed: bool,
    confirm_callback: ConfirmCallback | None,
) -> Any:
    """Call the application service, which asks before starting a browser.

    The rule used to live in ``desktop/automation.py``, so it applied to chat
    and to nothing else: open_app was catalogued LOW with no confirmation, and a
    model could start a browser without a word while chat asked every time. It
    now lives in the service every route calls, and this is how the layer's
    callback reaches it.
    """
    args = dict(parameters)
    target = str(args.pop(spec.target_parameter or "", "") or "")
    request = _ServiceRequest(action_type=spec.name, target=target, args=args)

    forwarded = None
    if confirm_callback is not None and not confirmed:

        def forwarded(plan: str) -> bool:
            return bool(
                confirm_callback(
                    spec.name, {**dict(parameters), "_plan": plan}, spec.risk
                )
            )

    instance = owner() if owner is not None else None
    return implementation(
        instance, request, action, confirm=forwarded, confirmed=confirmed
    )


def _call_browser(
    spec: ActionSpec,
    implementation: Any,
    owner: Any,
    action: str,
    parameters: Mapping[str, Any],
    confirmed: bool,
    confirm_callback: ConfirmCallback | None,
) -> Any:
    """Call the browser domain, and let it decide whether to ask.

    Wave 2 gave the browser its own approval path, which left two mechanisms:
    chat asked before navigating, and the action layer -- pointed at
    ``browser_control.execute_browser_action`` -- called ``webbrowser.open``
    with no question at all. The rule that matters lives in the domain, because
    only it can decide: the answer depends on the *resolved* URL, which does
    not exist until "example.com" has been normalised and a search phrase has
    been turned into a query string, and it is skipped entirely for a host in
    ``tools.browser.trusted_domains``. That is the definition of
    :data:`Confirmation.DOMAIN`, so the layer hands its callback over rather
    than asking up front.
    """
    from grandpa.browser.executor import BrowserExecutor
    from grandpa.browser.models import BrowserAction
    from grandpa.browser.safety import configured_trusted_domains

    fields = dict(parameters)
    target = str(fields.pop(spec.target_parameter or "", "") or "")

    if action == "open_url":
        browser_action = BrowserAction(action, target=target, url=target)
    elif action == "search":
        # An unknown provider is refused rather than guessed, and the
        # parser always names one, so the default belongs here too.
        browser_action = BrowserAction(
            action, provider=str(fields.get("provider") or "google"), query=target
        )
    elif action == "open_page":
        browser_action = BrowserAction(action, target=target)
    else:
        browser_action = BrowserAction(action)

    forwarded = None
    if confirm_callback is not None and not confirmed:

        def forwarded(prompt: str, permission: str) -> bool:
            # The domain writes the sentence -- "open https://example.com in
            # your browser" -- because it is the one that resolved the address.
            return bool(
                confirm_callback(
                    spec.name, {**dict(parameters), "_plan": str(prompt)}, spec.risk
                )
            )

    executor = BrowserExecutor(
        confirm=forwarded,
        confirmed=confirmed,
        trusted_domains=configured_trusted_domains(),
    )
    return executor.execute(browser_action)


def _call_files(
    spec: ActionSpec,
    implementation: Any,
    owner: Any,
    action: str,
    parameters: Mapping[str, Any],
    confirmed: bool,
    confirm_callback: ConfirmCallback | None,
) -> Any:
    """Call the files domain with a real FileAction.

    Files owns every file operation, and its safety policy runs inside the
    executor rather than in a caller -- which is why this binding exists. The
    previous route went to a service whose only guard lived in
    ``pc_control._preflight_guard``; the action layer does not go through
    pc_control, so file_delete reached the filesystem with no protected-path
    check at all. Calling the domain puts the check back on every path.

    Deleting asks (:data:`Confirmation.DOMAIN`), because the domain resolves
    "notes.txt" to a path -- and sometimes to several -- before there is
    anything to describe.
    """
    from grandpa.files.executor import FileExecutor
    from grandpa.files.models import FileAction

    fields = dict(parameters)
    target = str(fields.pop(spec.target_parameter or "path", "") or "")

    if action == "create_file" and str(fields.pop("kind", "file")) == "folder":
        action = "create_folder"
    destination = str(fields.pop("destination", "") or "")
    if action == "rename":
        destination = str(fields.pop("new_name", "") or "")

    file_action = FileAction(
        action=action,
        # search names what to look for, not where to look.
        source="" if action == "search" else target,
        query=target if action == "search" else "",
        destination=destination,
        args=fields,
    )

    forwarded = None
    if confirm_callback is not None and not confirmed:

        def forwarded(asked: Any, path: Any, _destination: Any = None) -> bool:
            # The domain's own sentence, asked with the layer's callback, so a
            # migration does not change the words a user reads.
            plan = f"{asked.action} {path}" if path is not None else asked.action
            return bool(
                confirm_callback(
                    spec.name, {**dict(parameters), "_plan": plan}, spec.risk
                )
            )

    executor = FileExecutor()
    if confirmed:
        return executor.execute(file_action, confirm=lambda *_: True)
    return executor.execute(file_action, confirm=forwarded)


def _call_web_search(
    spec: ActionSpec,
    implementation: Any,
    owner: Any,
    action: str,
    parameters: Mapping[str, Any],
) -> Any:
    """Call WebSearchAutomation.execute with a real WebSearchAction.

    The query is its own object, so a plain parameter mapping will not do.
    """
    from grandpa.web_search.models import WebSearchAction, WebSearchQuery

    query = None
    if parameters.get("query"):
        query = WebSearchQuery(
            text=str(parameters["query"]),
            max_results=int(parameters.get("max_results", 5)),
        )
    search_action = WebSearchAction(action=action, query=query)
    instance = owner() if owner is not None else None
    return implementation(instance, search_action)


def _call(
    spec: ActionSpec,
    parameters: Mapping[str, Any],
    *,
    confirmed: bool = False,
    confirm_callback: ConfirmCallback | None = None,
) -> Any:
    """Adapt the layer's parameters to whatever shape the implementation wants."""
    implementation, owner = _resolve(spec.implementation)
    action = spec.action_alias or spec.name

    if spec.binding is Binding.NOTES_ACTION:
        return _call_notes(spec, implementation, owner, action, parameters, confirmed)
    if spec.binding in {Binding.REMINDER_ACTION, Binding.SCHEDULER_ACTION}:
        # Module-level dispatchers, like memory's, with keyword parameters.
        return implementation(action, **dict(parameters))
    if spec.binding in {Binding.CALENDAR_ACTION, Binding.GMAIL_ACTION}:
        return _call_google(
            spec,
            implementation,
            owner,
            action,
            parameters,
            confirmed,
            confirm_callback,
        )
    if spec.binding is Binding.APPLICATION_ACTION:
        return _call_application(
            spec,
            implementation,
            owner,
            action,
            parameters,
            confirmed,
            confirm_callback,
        )
    if spec.binding is Binding.AWARENESS_ACTION:
        # Reading the page, never changing it: no confirmation to hand over.
        # The domain captures and redacts before it answers.
        return implementation(
            action, str(dict(parameters).get(spec.target_parameter or "", "") or "")
        )
    if spec.binding is Binding.BROWSER_ACTION:
        return _call_browser(
            spec,
            implementation,
            owner,
            action,
            parameters,
            confirmed,
            confirm_callback,
        )
    if spec.binding is Binding.FILE_ACTION:
        return _call_files(
            spec,
            implementation,
            owner,
            action,
            parameters,
            confirmed,
            confirm_callback,
        )
    if spec.binding is Binding.FUNCTION_KWARGS:
        return implementation(**dict(parameters))
    if spec.binding is Binding.WEB_SEARCH_ACTION:
        return _call_web_search(spec, implementation, owner, action, parameters)
    if spec.binding is Binding.MEMORY_ACTION:
        # A module-level function: no instance, and the parameters are keywords.
        return implementation(action, **dict(parameters))
    if spec.binding is Binding.DOWNLOADS_ACTION:
        return _call_downloads(
            spec,
            implementation,
            owner,
            action,
            parameters,
            confirmed,
            confirm_callback,
        )

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
    if isinstance(returned, str):
        # Some implementations are a plain formatter -- the clock is one. A
        # string is the answer, and an answer is a success.
        return ActionResult(success=True, message=returned)

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
    # Domain results also carry a couple of plain scalars a caller wants back --
    # what the action was about, and which domain answered.
    contents = getattr(returned, "contents", None)
    if isinstance(contents, str):
        # A read's payload. The files domain returns it as a field rather
        # than inside an evidence mapping.
        data["content"] = contents
        data.setdefault("size", len(contents.encode("utf-8")))
    for attribute in ("target", "kind", "url"):
        value = getattr(returned, attribute, None)
        if isinstance(value, str) and value:
            data.setdefault(attribute, value)
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
    needs = spec.requires_confirmation or request.requires_confirmation
    asks_itself = spec.confirmation is Confirmation.DOMAIN

    if needs and asks_itself:
        # The domain will ask, but only if it has something to ask with. No
        # callback means no one to ask, and that refuses here rather than
        # letting the domain quietly proceed or print a question to nobody.
        if confirm_callback is None:
            result = ActionResult.failed(
                CONFIRMATION_REQUIRED,
                message=(
                    f"{spec.name} may need the user's confirmation and no way to "
                    "ask for it was provided, so nothing was done."
                ),
            )
            _audit(request, risk=spec.risk, confirmed=None, result=result)
            return result
    elif needs:
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
        returned = _call(
            spec,
            parameters,
            confirmed=bool(confirmed),
            confirm_callback=confirm_callback,
        )
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
