"""A model-driven loop over the action catalogue.

The keyword waterfall can only do what someone wrote a pattern for, and only
one thing at a time. This loop hands the model the catalogue as tools and lets
it decide: send the goal, run whatever it calls, feed the results back, repeat
until it answers in words or runs out of steps.

Every action goes through :func:`grandpa.action_layer.executor.execute` --
including confirmation. There is no path from here to an implementation that
skips it.

A failed action is *not* a loop failure. The result goes back to the model as
a tool result so it can correct a bad argument or explain what it could not
do, which is the difference between an assistant and a batch script.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from grandpa.action_layer.catalogue import CATALOGUE, ActionSpec, get
from grandpa.action_layer.executor import ConfirmCallback, execute
from grandpa.action_layer.model import ActionRequest, ActionResult, Origin, RiskLevel
from grandpa.action_layer.tool_schema import as_tool_definitions

__all__ = [
    "DEFAULT_STEP_LIMIT",
    "ActionTrace",
    "LoopResult",
    "ToolsUnsupportedError",
    "run",
    "supports_tools",
]

logger = logging.getLogger(__name__)

DEFAULT_STEP_LIMIT = 8
"""Model turns, not actions -- one turn may call several tools.

Eight is enough for the multi-step goals this layer exists to make possible
(create, append, read back is three) with room to recover from a mistake,
and low enough that a model looping on itself stops in seconds rather than
grinding through a local GPU for minutes.
"""

SYSTEM_PROMPT = """\
You are Grandpa, controlling a Windows desktop through a fixed set of tools.

Use the tools to actually do what the user asked -- do not describe what you
would do, and never claim something is done unless a tool result says so. If a
tool fails, read the error and either correct the call or tell the user plainly
what did not work. When the goal needs several steps, take them one at a time
and check each result before the next. When you are finished, reply in plain
words with what you did and what you found.

If no tool can do what was asked, say so instead of pretending."""


@dataclass(frozen=True, slots=True)
class ActionTrace:
    """One action the loop took, and how it went."""

    action: str
    parameters: Mapping[str, Any]
    success: bool
    message: str
    error: str | None = None
    step: int = 0

    def summary(self) -> str:
        outcome = "ok" if self.success else f"failed ({self.error})"
        return f"{self.action} -> {outcome}"


@dataclass(frozen=True, slots=True)
class LoopResult:
    """What the loop produced: the model's answer, and what it actually did."""

    text: str
    """The model's final reply, or an explanation of why there is none."""

    trace: tuple[ActionTrace, ...] = ()
    """Every action attempted, in order."""

    steps: int = 0
    """Model turns used."""

    stopped_at_limit: bool = False
    """True when the step limit ended the loop rather than the model."""

    model: str = ""

    @property
    def actions_taken(self) -> tuple[str, ...]:
        return tuple(entry.action for entry in self.trace)


class ToolsUnsupportedError(RuntimeError):
    """The configured model cannot call tools, so the loop cannot run.

    Raised rather than worked around. Ollama's adapter quietly retries without
    the tools when the server rejects them
    (``runtime/ollama_adapter.py``), which would leave the model chatting about
    the desktop instead of touching it -- exactly the failure this layer exists
    to remove. Better to stop and name the model.
    """


# --- can this model call tools at all? ---------------------------------------


def supports_tools(engine: Any, model: str) -> bool | None:
    """Return True, False, or None when it cannot be determined.

    Asks the backend rather than guessing from the model name: Ollama's
    ``/api/show`` reports a ``capabilities`` list, and ``tools`` is in it only
    for models that really support tool calling. An engine may also answer for
    itself by defining ``supports_tools(model)``.
    """
    asker = getattr(engine, "supports_tools", None)
    if callable(asker):
        try:
            return bool(asker(model))
        except Exception as exc:  # pragma: no cover - backend specific
            logger.debug("engine.supports_tools(%s) failed: %s", model, exc)
            return None

    capabilities = _ollama_capabilities(engine, model)
    if capabilities is None:
        return None
    return "tools" in capabilities


def _ollama_capabilities(engine: Any, model: str) -> list[str] | None:
    client = getattr(engine, "_client", None)
    post = getattr(client, "post", None)
    if not callable(post):
        return None
    try:
        response = post("/api/show", json={"model": model})
        response.raise_for_status()
        capabilities = response.json().get("capabilities")
    except Exception as exc:
        logger.debug("could not read capabilities for %s: %s", model, exc)
        return None
    if not isinstance(capabilities, list):
        return None
    return [str(capability) for capability in capabilities]


def _require_tool_support(engine: Any, model: str) -> None:
    supported = supports_tools(engine, model)
    if supported is False:
        capabilities = _ollama_capabilities(engine, model) or []
        detail = ", ".join(capabilities) if capabilities else "none reported"
        raise ToolsUnsupportedError(
            f"The model {model!r} cannot call tools (capabilities: {detail}), so "
            "the action loop has nothing to drive it with. Choose a model whose "
            "capabilities include 'tools'."
        )
    if supported is None:
        # A backend that will not say. Proceeding is the only option, but it is
        # worth a line in the log when the loop then does nothing.
        logger.debug("tool support for %r could not be determined", model)


# --- turning a tool call into an action ---------------------------------------


def _parse_arguments(raw: Any) -> tuple[dict[str, Any] | None, str]:
    if raw is None or raw == "":
        return {}, ""
    if isinstance(raw, Mapping):
        return dict(raw), ""
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        return None, f"arguments were not valid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, f"arguments must be a JSON object, got {type(parsed).__name__}"
    return parsed, ""


def _request_for(action: str, parameters: Mapping[str, Any], origin: Origin):
    """Build the request, taking risk and confirmation from the catalogue."""
    try:
        spec: ActionSpec | None = get(action)
    except KeyError:
        spec = None
    if spec is None:
        # Unknown to the catalogue: let the executor say so, and default to the
        # safe end of the contract on the way there.
        return ActionRequest(action, parameters, origin, RiskLevel.BLOCKED, True)
    return ActionRequest(
        action, parameters, origin, spec.risk, spec.requires_confirmation
    )


def _tool_result_payload(result: ActionResult) -> str:
    payload: dict[str, Any] = {"success": result.success, "message": result.message}
    if result.error:
        payload["error"] = result.error
    if result.data:
        payload["data"] = _jsonable(dict(result.data))
    return json.dumps(payload, ensure_ascii=False, default=str)[:4000]


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)
    return value


# --- the loop -----------------------------------------------------------------


@dataclass
class _Turn:
    """One exchange with the model, kept out of run() so it stays readable."""

    content: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)


def _ask_model(
    engine: Any,
    model: str,
    messages: Sequence[Any],
    tools: list[dict[str, Any]],
    temperature: float,
) -> _Turn:
    response = engine.generate(
        messages, model=model, tools=tools, temperature=temperature
    )
    if not isinstance(response, Mapping):  # pragma: no cover - defensive
        return _Turn(content=str(response))
    calls = [dict(call) for call in (response.get("tool_calls") or [])]
    return _Turn(content=str(response.get("content") or ""), calls=calls)


def run(
    goal: str,
    *,
    engine: Any,
    model: str,
    confirm_callback: ConfirmCallback | None = None,
    origin: Origin = Origin.MODEL,
    step_limit: int = DEFAULT_STEP_LIMIT,
    system_prompt: str = SYSTEM_PROMPT,
    actions: Iterable[ActionSpec] | None = None,
    temperature: float = 0.0,
    on_action: Callable[[ActionTrace], None] | None = None,
) -> LoopResult:
    """Let the model pursue ``goal`` with the catalogue as its tools."""
    from grandpa.core.types import Message, Role, ToolCall

    _require_tool_support(engine, model)

    specs = tuple(CATALOGUE if actions is None else actions)
    tools = as_tool_definitions(specs)
    messages: list[Message] = [
        Message(role=Role.SYSTEM, content=system_prompt),
        Message(role=Role.USER, content=goal),
    ]
    trace: list[ActionTrace] = []
    limit = max(1, int(step_limit))

    for step in range(1, limit + 1):
        turn = _ask_model(engine, model, messages, tools, temperature)

        if not turn.calls:
            text = turn.content.strip()
            if not text:
                text = (
                    "The model ended the turn without an answer and without "
                    "calling a tool, so nothing was done."
                )
            return LoopResult(text, tuple(trace), step, False, model)

        messages.append(
            Message(
                role=Role.ASSISTANT,
                content=turn.content,
                tool_calls=[
                    ToolCall(
                        id=str(call.get("id") or f"call_{index}"),
                        name=str(call.get("name") or ""),
                        arguments=_as_argument_string(call.get("arguments")),
                    )
                    for index, call in enumerate(turn.calls)
                ],
            )
        )

        for index, call in enumerate(turn.calls):
            action = str(call.get("name") or "")
            call_id = str(call.get("id") or f"call_{index}")
            parameters, problem = _parse_arguments(call.get("arguments"))
            if parameters is None:
                result = ActionResult.failed(
                    "invalid_arguments", message=f"{action}: {problem}"
                )
                parameters = {}
            else:
                result = execute(
                    _request_for(action, parameters, origin), confirm_callback
                )

            entry = ActionTrace(
                action=action,
                parameters=dict(parameters),
                success=result.success,
                message=result.message,
                error=result.error,
                step=step,
            )
            trace.append(entry)
            if on_action is not None:
                on_action(entry)

            # A failure goes back as a result, not as an exception: the model
            # is the thing best placed to recover from it or explain it.
            messages.append(
                Message(
                    role=Role.TOOL,
                    content=_tool_result_payload(result),
                    name=action,
                    tool_call_id=call_id,
                )
            )

    done = ", ".join(entry.summary() for entry in trace) or "nothing"
    return LoopResult(
        text=(
            f"I stopped after {limit} steps without finishing, so the goal may "
            f"be incomplete. What I did: {done}."
        ),
        trace=tuple(trace),
        steps=limit,
        stopped_at_limit=True,
        model=model,
    )


def _as_argument_string(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw or {})
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return "{}"
