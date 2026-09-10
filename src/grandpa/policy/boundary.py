"""The seam a capability package uses to reach the hardened action boundary.

A capability package must not import the execution module. The layering is
``entry surfaces -> dispatch -> policy -> capability packages -> core``, and
``pc_control`` sits on the wrong side of that line for ``files/`` to depend on
it -- which is also why the file layer is absent from the saturated
direct-executor baseline.

``FileExecutor`` already solved this by taking an injected callable instead of
importing anything. What was missing was ownership: the type lived in the
capability package as a bare ``Callable`` alias, so the seam was a private
detail rather than something the policy layer offered. Declaring it here moves
the *name* to the layer capability packages are permitted to depend on. Nothing
else moves.

**Deliberately a callable, not an object with a ``run`` method.** The existing
site invokes ``self.mutation_runner(payload)`` and the thing injected is
``run_local_action`` itself. A method-based protocol would satisfy nothing
already in the tree and would need an adapter at every injection point --
changing the semantics of a compatibility contract in a slice whose whole
purpose is to change none. Structural typing describes what exists.

**What this is not.** It carries no policy, evaluates nothing, stores nothing
and executes nothing. Every gate -- risk tier, approval, token, digest,
single-owner claim, emergency stop, dry run, audit -- stays where it is, behind
the callable. Filesystem behaviour stays in ``FileExecutor``. If this module
ever grows a rule, the seam has become the god-module it exists to avoid.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

#: What crosses the seam: the payload ``run_local_action`` already accepts.
#: Left as a plain mapping rather than a model, because narrowing it here would
#: put the capability's request shape in the policy layer and make the two
#: versions drift.
MutationPayload = Mapping[str, Any]


class MutationBoundary(Protocol):
    """Performs one mutation through the hardened boundary, or refuses it.

    Implementations decide; they do not merely forward. The return value is the
    boundary's own response object -- deliberately untyped here, so that naming
    the seam does not drag the execution module's types into the policy layer
    through a type annotation.

    A caller supplies one of these to opt a mutation into the boundary. Passing
    nothing is the ordinary case and leaves behaviour untouched, which is what
    makes this additive.
    """

    def __call__(self, payload: MutationPayload) -> Any:
        """Run *payload* through the boundary and return its response."""
        ...


__all__ = ["MutationBoundary", "MutationPayload"]
