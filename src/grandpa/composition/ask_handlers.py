"""The five handlers ``cli/ask.py`` calls, in the dispatcher's shape.

Translation only. Each adapter calls one existing handler exactly once, decides
claimed-or-not from the value that handler returned, and hands that value back
untouched. No adapter parses text, consults policy, stages approval, checks the
emergency stop, writes an audit record, or knows what any result means.

**Why this lives in ``composition`` and not ``dispatch.adapters``.** The
dispatch package stays capability-free: its existing adapters wrap
``grandpa.actions``, which imports nothing. These five reach into
``local_actions``, ``file_assistant``, ``task_scheduler``, ``memory_context``
and ``core.runtime_context`` -- naming concrete capabilities is exactly what
``composition`` exists to do, and the layer that already wires the file surface
is the right one to wire this.

**Nothing consumes this yet.** ``ask.py`` is unchanged and does not import it.
The adapters are built and tested here so the wiring slice has something proven
to wire; until then this module is reachable only from tests.

Three details are load-bearing and easy to lose:

*Handlers are resolved at call time*, by importing inside ``try_handle`` --
which is what ``ask.py`` itself does. Binding them at construction would make
the module attribute unpatchable and would freeze whichever object existed at
import time.

*``execute`` is never passed* to ``handle_local_action`` or
``handle_scheduler_command``. Both default to ``True`` and ``ask`` leaves them
there; passing it explicitly would look harmless and would pin behaviour the
4.4c characterization deliberately measured as inherited.

*``datetime`` claims on truthiness*, not on ``is not None``. ``ask.py:681``
tests ``if dt_resp:`` while ``voice/assistant.py:155`` tests ``is not None``.
Today ``handle_datetime_intent`` never returns an empty string, so the two
agree -- but this adapter follows ``ask``, and a surface that wants the other
rule needs its own adapter rather than a change here.
"""

from __future__ import annotations

from collections.abc import Callable

from grandpa.dispatch.context import RequestContext
from grandpa.dispatch.protocol import NOT_HANDLED, HandlerResult
from grandpa.dispatch.registry import IntentDispatcher

#: Calls one handler and returns whatever it returned. Nothing is interpreted.
_Invoke = Callable[[RequestContext], object]

#: Decides whether a returned value means "served". Each handler family states
#: this differently, which is the only reason the adapters are not one function.
_Claimed = Callable[[object], bool]


class AskHandlerAdapter:
    """One existing handler, presented as an ``IntentHandler``."""

    def __init__(self, name: str, invoke: _Invoke, claimed: _Claimed) -> None:
        self.name = name
        self._invoke = invoke
        self._claimed = claimed

    def try_handle(self, ctx: RequestContext) -> HandlerResult:
        """Call the handler once; return its result, or ``NOT_HANDLED``.

        The result is returned by identity. Twelve call sites read ``status``,
        ``kind``, ``message`` and ``should_fallback`` off these objects, and
        rebuilding one here would be a chance for any of them to differ.
        """
        result = self._invoke(ctx)
        return result if self._claimed(result) else NOT_HANDLED


# ---------------------------------------------------------------------------
# The five invocations, each matching what ``ask.py`` does today
# ---------------------------------------------------------------------------


def _invoke_datetime(ctx: RequestContext) -> object:
    from grandpa.core.runtime_context import handle_datetime_intent

    return handle_datetime_intent(ctx.text)


def _invoke_memory(ctx: RequestContext) -> object:
    from grandpa.memory_context import handle_memory_command

    return handle_memory_command(ctx.text)


def _invoke_local_action(ctx: RequestContext) -> object:
    from grandpa.local_actions import handle_local_action

    # No ``execute``: the default is True and ``ask`` inherits it.
    return handle_local_action(ctx.text)


def _invoke_file(ctx: RequestContext) -> object:
    from grandpa.file_assistant import handle_file_command

    # Provenance is the caller's to state; this forwards it and invents nothing.
    return handle_file_command(ctx.text, origin=ctx.origin)


def _invoke_scheduler(ctx: RequestContext) -> object:
    from grandpa.task_scheduler import handle_scheduler_command

    # No ``execute``, for the same reason as ``local_action`` above.
    return handle_scheduler_command(ctx.text)


def _truthy(result: object) -> bool:
    """``handle_datetime_intent`` returns ``Optional[str]``; ``ask`` tests it
    for truth."""
    return bool(result)


def _served(result: object) -> bool:
    """The other four report it on the result object itself."""
    return not result.should_fallback  # type: ignore[attr-defined]


#: The order ``ask.py`` asks in, which since the GAP-22 fix is also its
#: precedence order. ``datetime`` ahead of ``memory`` is the ratified invariant:
#: memory mutates as it matches, so it must not run for a request datetime
#: answers.
ASK_HANDLER_ORDER: tuple[tuple[str, _Invoke, _Claimed], ...] = (
    ("datetime", _invoke_datetime, _truthy),
    ("memory", _invoke_memory, _served),
    ("local_action", _invoke_local_action, _served),
    ("file", _invoke_file, _served),
    ("scheduler", _invoke_scheduler, _served),
)


def build_ask_handlers() -> tuple[AskHandlerAdapter, ...]:
    """The five adapters, in ``ask``'s order."""
    return tuple(
        AskHandlerAdapter(name, invoke, claimed)
        for name, invoke, claimed in ASK_HANDLER_ORDER
    )


def build_ask_dispatcher() -> IntentDispatcher:
    """A dispatcher holding the five adapters, ordered as ``ask`` asks today.

    Orders are spaced by ten so a later slice can interleave a handler without
    renumbering, which would otherwise be a diff that looks like a reordering.

    Not wired into ``ask.py``. Building one has no effect until something
    dispatches through it.
    """
    dispatcher = IntentDispatcher()
    for index, handler in enumerate(build_ask_handlers()):
        dispatcher.register(handler, order=(index + 1) * 10)
    return dispatcher


__all__ = [
    "ASK_HANDLER_ORDER",
    "AskHandlerAdapter",
    "build_ask_dispatcher",
    "build_ask_handlers",
]
