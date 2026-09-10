"""The seven ``grandpa.actions`` domain handlers, in the dispatcher's shape.

``actions/router.py`` is already an ordered registry: ``_HANDLERS`` is a tuple of
``(domain, try_handle, count)`` and ``route_action`` asks each in turn, taking
the first non-``None``. That is the dispatcher's own selection rule, written out
by hand, which is what makes these seven the safest possible first adapters --
the shape being adapted to is the shape they already have.

**On the retained ``claims``/``handle`` pair.** The dispatcher now asks
``try_handle`` once, so nothing in production calls the underlying function
twice any more. The split methods are kept because they are still a faithful
description of these seven -- each is an exact dict lookup that either returns
``None`` or constructs a fresh ``LocalActionResult``, with no I/O, no mutation
and no module-level state, so asking twice was harmless here even when it
happened. All seven were read before this was written.

**Do not generalise that.** Most of the Funnel-A branches are not pure in this
way, and several -- the confirmation gate, the permission wrapper, the intent
router's skill execution -- act as they decide. An adapter for those needs a
different strategy, and the purity has to be re-established per handler rather
than assumed from this file.

Results are passed through untouched. ``handle`` returns exactly the object
``try_handle`` produced, never a copy and never a wrapper, because twelve call
sites read ``.status``, ``.kind``, ``.message`` and ``.should_fallback`` off it
and any reconstruction is a chance to change one of them.

Nothing here is registered into production routing.
"""

from __future__ import annotations

from collections.abc import Callable

from grandpa.actions import (
    browser_actions,
    desktop_actions,
    fallback_actions,
    memory_actions,
    planner_actions,
    vision_actions,
    workflow_actions,
)
from grandpa.dispatch.context import RequestContext
from grandpa.dispatch.protocol import NOT_HANDLED, HandlerResult
from grandpa.dispatch.registry import IntentDispatcher

#: A ``grandpa.actions`` domain function: text in, result or ``None`` out.
TryHandle = Callable[[str], HandlerResult | None]


class ActionModuleHandler:
    """Presents one ``grandpa.actions`` domain as an ``IntentHandler``.

    Holds the function rather than the module, matching how ``_HANDLERS`` stores
    it -- and letting a test supply its own callable without patching a module.
    """

    def __init__(self, name: str, try_handle: TryHandle) -> None:
        self.name = name
        self._try_handle = try_handle

    def try_handle(self, ctx: RequestContext) -> HandlerResult:
        """Serve *ctx*, or return ``NOT_HANDLED``.

        The wrapped ``grandpa.actions`` functions signal "not mine" with
        ``None``; translating that to ``NOT_HANDLED`` is this adapter's job,
        because it is the thing that knows the wrapped convention. The
        dispatcher deliberately does not make that assumption for everyone --
        ``None`` is a legitimate result from other handlers.

        ``ctx.text`` is the only input read, as with ``claims`` below.
        """
        result = self._try_handle(ctx.text)
        return NOT_HANDLED if result is None else result

    def claims(self, ctx: RequestContext) -> bool:
        """Whether the wrapped domain recognises ``ctx.text``.

        ``ctx.text`` is the only input read. Origin and dry_run are
        deliberately ignored: these seven parse text and nothing else, and
        letting provenance change what a parser matches would put a policy
        decision inside a parser.
        """
        return self._try_handle(ctx.text) is not None

    def handle(self, ctx: RequestContext) -> HandlerResult:
        """Return exactly what the wrapped domain returned."""
        return self._try_handle(ctx.text)


#: The seven domains in ``actions.router._HANDLERS`` order. Order is spelled out
#: rather than derived from the private ``_HANDLERS`` so this file does not bind
#: to another module's private name; a test asserts the two agree, which catches
#: drift in either direction.
ACTION_MODULE_ORDER: tuple[tuple[str, TryHandle], ...] = (
    ("desktop", desktop_actions.try_handle),
    ("browser", browser_actions.try_handle),
    ("vision", vision_actions.try_handle),
    ("workflow", workflow_actions.try_handle),
    ("planner", planner_actions.try_handle),
    ("memory", memory_actions.try_handle),
    ("fallback", fallback_actions.try_handle),
)


def build_action_module_handlers() -> tuple[ActionModuleHandler, ...]:
    """One adapter per domain, in ``route_action``'s asking order."""
    return tuple(
        ActionModuleHandler(name, try_handle)
        for name, try_handle in ACTION_MODULE_ORDER
    )


def build_action_module_dispatcher() -> IntentDispatcher:
    """A dispatcher holding the seven adapters, ordered as today.

    Orders are spaced by ten so a later slice can interleave a handler without
    renumbering, which would otherwise be a diff that looks like a reordering.
    """
    dispatcher = IntentDispatcher()
    for index, handler in enumerate(build_action_module_handlers()):
        dispatcher.register(handler, order=(index + 1) * 10)
    return dispatcher


__all__ = [
    "ACTION_MODULE_ORDER",
    "ActionModuleHandler",
    "TryHandle",
    "build_action_module_dispatcher",
    "build_action_module_handlers",
]
