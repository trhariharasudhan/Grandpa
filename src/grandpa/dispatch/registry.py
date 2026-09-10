"""Ordering and selection. Nothing else.

The dispatcher decides *which* handler serves a request. It does not classify
risk, stage approval, check the emergency stop, audit, or execute -- every one
of those already has an owner, and the audit for this step found that the
funnels enforce them in a specific order that this package must not perturb.
A dispatcher that also classified would become a second policy boundary, which
is the problem ``policy/`` exists to end rather than to acquire a sibling of.

That is also why ``DispatchResult`` carries no risk level, permission status or
approval flag. Three policy-shaped result models already exist
(``PolicyDecision``, ``PermissionStatus``, ``IntentRoute``); a fourth grown here
would have to be reconciled at 4.11 along with the other three.

Deliberately not built: plugin discovery, dynamic import, persistence, caching,
and any concurrency control. Registration is explicit and ordering is given by
the caller, because a registry that discovers its own handlers cannot be
reasoned about from the call site -- and the whole reason six chains diverged is
that no one could see the whole set from any one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from grandpa.dispatch.context import RequestContext
from grandpa.dispatch.protocol import NOT_HANDLED, HandlerResult, IntentHandler


@dataclass(frozen=True)
class DispatchResult:
    """Which handler served the request, and what it returned.

    ``handler_name`` is None exactly when no handler served it. That case is
    ordinary, not an error: the surfaces fall through to conversation when
    nothing recognises the text, and a dispatcher that raised instead would
    turn every unrecognised sentence into an exception.

    ``result`` is :data:`NOT_HANDLED` in that case rather than ``None``, since
    ``None`` is a value a handler may legitimately return -- ``claimed`` is the
    field to read, never the truthiness of ``result``.
    """

    handler_name: str | None = None
    result: HandlerResult = NOT_HANDLED

    @property
    def claimed(self) -> bool:
        return self.handler_name is not None


class IntentDispatcher:
    """An ordered set of handlers, asked in order until one claims.

    Not thread-safe, and deliberately so: registration happens once at
    composition time, and adding a lock would imply a mutation pattern this
    does not have.
    """

    def __init__(self) -> None:
        # (order, sequence, handler). ``sequence`` breaks ties by registration
        # order so two handlers sharing an order are still asked in a defined
        # sequence -- otherwise the chain would depend on sort stability, which
        # is exactly the kind of accident the golden-order tests exist to catch.
        self._entries: list[tuple[int, int, IntentHandler]] = []
        self._sequence = 0

    def register(self, handler: IntentHandler, *, order: int) -> None:
        """Add *handler* at *order*. Lower orders are asked first."""
        self._entries.append((order, self._sequence, handler))
        self._sequence += 1
        self._entries.sort(key=lambda entry: (entry[0], entry[1]))

    @property
    def handlers(self) -> tuple[IntentHandler, ...]:
        """The registered handlers, in the order they will be asked."""
        return tuple(handler for _order, _seq, handler in self._entries)

    def dispatch(self, ctx: RequestContext) -> DispatchResult:
        """Ask each handler in order; the first that serves *ctx* wins.

        Each handler is invoked **exactly once**. That is the point of the
        single-method contract: handlers that act while deciding would
        otherwise act twice, and for the file handler the deciding call is the
        one that reaches the mutation boundary.

        The verdict is read by identity against ``NOT_HANDLED`` and nothing
        else. The result is never inspected -- not its truthiness, not
        ``status``, not ``should_fallback`` -- because the results this must
        carry share no base type, and a dispatcher that read one field of one
        of them would have become the place their shapes are reconciled.

        Exceptions from ``try_handle`` propagate. Wrapping them in an error
        envelope is a real responsibility, but it belongs to the slice that
        migrates a surface and can say what an envelope should contain --
        swallowing them here would hide handler faults behind "nobody served
        it".
        """
        for handler in self.handlers:
            result = handler.try_handle(ctx)
            if result is not NOT_HANDLED:
                return DispatchResult(handler_name=handler.name, result=result)
        return DispatchResult()


__all__ = ["DispatchResult", "IntentDispatcher"]
