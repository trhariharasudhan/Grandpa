"""What a handler owes the dispatcher.

One method. ``try_handle`` answers "did you serve this, and with what?" in a
single call, because for the handlers this dispatcher exists to unify, asking
and doing are the same act.

**Why not ``claims`` then ``handle``** (the shape this replaced). That split
requires ``claims`` to be side-effect free, and four of the five handlers in
``cli/ask.py`` cannot honour it: ``handle_memory_command`` writes as it
matches, ``handle_local_action`` audits and actuates, ``handle_scheduler_command``
upserts inside the matched branch, and ``handle_file_command`` is stronger
still -- it runs the file automation *before* consulting its own patterns, so
its claim decision reaches the mutation boundary. Wrapping any of them in a
``claims``/``handle`` pair invoked the handler twice, which meant the effect
happened twice. Caching a ``claims`` result does not fix it: caching removes
the second call, and the first is the one that already acted.

Only ``handle_datetime_intent`` is genuinely pure. A contract that only its
one handler can satisfy is not a contract the dispatcher can be built on.

This is also the shape production already uses. Every ``grandpa.actions``
domain exposes ``try_handle(command) -> result | None``; the adapters in
``dispatch.adapters`` were wrapping that and synthesising a ``claims`` from it
by calling it a second time.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from grandpa.dispatch.context import RequestContext


class _NotHandled:
    """The type of :data:`NOT_HANDLED`. Never instantiated elsewhere."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "NOT_HANDLED"

    def __bool__(self) -> bool:
        """Falsy, so a stray truthiness test reads the safe way.

        Identity is still the only supported check -- see the note on
        :data:`NOT_HANDLED`.
        """
        return False


#: Returned by a handler that did not serve the request.
#:
#: A dedicated sentinel rather than ``None``, and compared by identity rather
#: than truthiness, because both of the obvious alternatives are ambiguous
#: here. ``handle_datetime_intent`` returns ``Optional[str]``, so ``None`` is a
#: value a handler can legitimately produce; and a served request can produce
#: an empty or falsy result. Only ``result is NOT_HANDLED`` separates "nobody
#: served this" from "served, and the answer was empty".
NOT_HANDLED: Any = _NotHandled()

#: Whatever a handler returns when it served the request. Deliberately opaque:
#: the dispatcher passes it back untouched and never reads a field off it.
#:
#: The five handlers this must carry have no common base -- one returns a bare
#: ``str`` and four return unrelated dataclasses -- so any concrete type here
#: would mean a normalisation step, and normalising is where ``status`` and
#: ``message`` quietly change.
HandlerResult = object


@runtime_checkable
class IntentHandler(Protocol):
    """Something that can serve a request, or decline it.

    ``runtime_checkable`` so a registry caller can assert shape in a test
    without importing a concrete handler. Note this checks method presence
    only, which is all a structural check can offer and all that is wanted
    here.
    """

    name: str

    def try_handle(self, ctx: RequestContext) -> HandlerResult:
        """Serve *ctx*, or return :data:`NOT_HANDLED`.

        Called at most once per dispatch attempt. A handler that acts while
        deciding is expected and supported; that is the reason this method is
        not split in two.
        """
        ...


__all__ = ["NOT_HANDLED", "HandlerResult", "IntentHandler"]
