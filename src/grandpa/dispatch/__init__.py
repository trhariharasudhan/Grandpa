"""One ordered handler chain, shared by every entry surface.

Six entry surfaces each hand-wrote their own probe chain, so a request served
by one is not necessarily served by another: ``ask`` is missing nine of the
handlers ``chat`` has, and the two voice surfaces reach different actuation
funnels for the same spoken sentence. This package exists so the ordering lives
in one place and a surface differs only by which handlers it is given.

**Nothing consumes this yet.** It is the additive first step of the dispatcher
migration: the contract lands, is tested, and only then does a surface move to
it. No existing routing is changed, replaced, or reordered by this package
being present.

Scope is deliberately narrow -- registration, ordering, selection. Risk
classification, approval, the emergency stop, audit and execution all keep
their current owners, and the order the funnels apply them in is not this
package's to alter.
"""

from grandpa.dispatch.context import RequestContext
from grandpa.dispatch.protocol import NOT_HANDLED, HandlerResult, IntentHandler
from grandpa.dispatch.registry import DispatchResult, IntentDispatcher

__all__ = [
    "NOT_HANDLED",
    "DispatchResult",
    "HandlerResult",
    "IntentDispatcher",
    "IntentHandler",
    "RequestContext",
]
