"""The one capability policy needs from the outside world: what is this target?

Risk is currently judged from the raw string a caller passed, while the program
that actually runs is chosen later by an inventory lookup that classification
never sees. Closing that means classification has to be able to ask "what does
this name refer to?" before deciding -- and it has to be able to ask without
depending on how the answer is found.

Hence a port, not an implementation. ``policy`` states the question; the
inventory, the alias tables and the Windows resolver already know how to answer
it, and a later slice injects one of them. Nothing here reads a file, opens a
database, or touches Windows.

**One method, deliberately.** Everything else the existing resolvers expose --
scoring, match lists, launch kinds, store paths -- is either an implementation
detail or a different question. A port that mirrored those would tie policy to
the current inventory design and would have to change when that design does.

**What this port does not yet say.** ``apps.resolver.resolve_app`` has three
outcomes: ``found``, ``missing`` and ``ambiguous``. ``CanonicalTarget``
expresses the first two. Ambiguity is a real third answer that today's launcher
already treats as consequential -- ``desktop/control/applications.py`` returns
``approval_required`` at MEDIUM for it -- so collapsing it into "unresolved"
here would quietly discard a signal the live system acts on. That mapping is
deliberately not made in this slice: it belongs to the adapter that wraps a
real resolver, and it needs a decision about ``ResolutionSource`` rather than
an assumption. See the module docstring of ``grandpa.policy.models``.
"""

from __future__ import annotations

from typing import Protocol

from grandpa.policy.models import CanonicalTarget


class AppTargetResolver(Protocol):
    """Turns the words a caller used into the application they refer to.

    Implementations may read an inventory, consult an alias table, or do both;
    that is their business. What they owe the caller is determinism -- the same
    raw target must give the same identity within a request, because a tier
    decided against one identity and an action taken against another is the bug
    this whole port exists to prevent.

    An implementation must not raise for an unknown name. A missing or
    unreadable inventory is an ordinary condition, and the answer to it is an
    unresolved ``CanonicalTarget``, which leaves the request classifiable by
    the rules that apply today.
    """

    def resolve(self, raw_target: str) -> CanonicalTarget:
        """Return the identity *raw_target* refers to, resolved or not."""
        ...


__all__ = ["AppTargetResolver"]
