"""The vocabulary a single policy decision is made in.

Types only. No rules, no resolution, no I/O -- and, deliberately, no import of
``pc_control`` or ``local_actions``. That last part is not stylistic: the
kernel baseline guard counts every module importing either of those two, and a
policy package that reached back into ``pc_control`` would both trip the guard
and invert the dependency the migration exists to establish. Policy is the
thing the executor calls, not the other way round.

The guard measures **45 files against a ceiling of 53** -- eight of headroom,
opened up as the migration removed importers rather than added them. The
headroom is not permission: the guard's binding rule is a per-category *set*
difference, so any module not already on the recorded list fails it whatever
the total says. A new ``pc_control`` importer is refused at 45 exactly as it
would have been at 53.

Most of this module is still unused. It is here so the later steps have a
shared vocabulary to be written against, and so that vocabulary can be reviewed
on its own before any behaviour moves. The exception is ``ActionOrigin``, which
D-5 made canonical here: ``pc_control`` re-exports it and ``dispatch.context``
imports it, so provenance is the one piece of this vocabulary already in use.

The names mirror ``pc_control``'s existing ones on purpose. ``PolicyRequest``
carries the same fields as ``LocalActionRequest`` because the first migration
step has to be a faithful translation; a redesign at the same time as a move
would make equivalence impossible to prove.

``CanonicalTarget`` is the one genuinely new idea. Today an application's risk
is judged from the raw string the caller passed, while the program that
actually runs is chosen later, by an inventory lookup that classification never
sees -- so "open wsl" is classified as an ordinary launch and then starts a
shell. Naming the resolved identity is what lets a later step put resolution
*before* classification. It is defined here and used nowhere, which is the
intended state until that step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

#: Kept identical to ``pc_control.RiskLevel``. Duplicated rather than imported
#: for the dependency reason in the module docstring; a later step makes
#: ``pc_control`` import these instead, at which point the duplication ends.
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "BLOCKED"]

#: Kept identical to ``pc_control.ActionStatus``, on the same terms as
#: ``RiskLevel`` above: duplicated rather than imported, because
#: ``LocalActionResponse`` is defined here and cannot annotate itself with a
#: name that lives in the module this package must not import.
ActionStatus = Literal[
    "completed",
    "partial_success",
    "dry_run",
    "approval_required",
    "rejected",
    "blocked",
    "unsupported",
    "failed",
    "expired",
]

#: Who asked for an action (AD-022, D-5). Who asked, never what they claim to
#: be: an HTTP caller cannot assert "voice", which is why the server stamps this
#: rather than reading it from a request body.
#:
#: **This is the canonical definition.** ``pc_control`` re-exports it for the
#: callers that already import from there; there is deliberately no second copy.
#: ``policy`` is the home because it depends on nothing in the package, so every
#: layer can name a provenance without acquiring a dependency on the execution
#: module.
#:
#: Six values, expanded additively by D-5 from the original three. The first
#: three are unchanged and keep their meanings exactly:
#:
#: ``voice``
#:     Spoken by the user.
#: ``agent``
#:     An autonomous agent acting on its own context, with parameters it wrote
#:     itself rather than ones a model chose.
#: ``direct``
#:     A person interacting locally -- the CLI. Also the least-privileged label,
#:     and therefore what an unrecognised origin coerces to.
#: ``api``
#:     A remote HTTP caller. Split from ``direct`` because "someone typing at
#:     this machine" and "something on the network" are the pair an audit trail
#:     most needs to tell apart.
#: ``scheduler``
#:     A timer, with no human present at the moment of execution.
#: ``skill``
#:     A skill invoked through ``SkillTool``, carrying model-chosen parameters.
#:     Distinct from ``agent`` because AD-022 is precisely about that
#:     difference: an agent reading its own context passes hardcoded literals,
#:     while a skill can be handed arguments a model produced.
#:
#: Recording origin still changes no decision. Risk is computed from the action,
#: never from who asked, and the approval digest deliberately excludes origin --
#: which is what made this expansion safe to make without touching a single
#: stored approval.
ActionOrigin = Literal["voice", "agent", "direct", "api", "scheduler", "skill"]

#: The runtime membership check behind ``_coerce_origin``. Kept in step with the
#: ``Literal`` above by test, since the type is erased at runtime.
ACTION_ORIGINS: tuple[str, ...] = (
    "voice",
    "agent",
    "direct",
    "api",
    "scheduler",
    "skill",
)

DEFAULT_ACTION_ORIGIN: ActionOrigin = "direct"

#: Where a resolved identity came from, so a decision can be explained and so a
#: later step can treat a fuzzy match differently from an exact one.
ResolutionSource = Literal["alias", "inventory", "unresolved"]


@dataclass(frozen=True)
class CanonicalTarget:
    """What a request's target turned out to refer to.

    ``raw`` is what the caller said; every other field is what it resolved to.
    Both are kept because a decision needs the resolved identity while an audit
    record needs the words the user actually used.

    An unresolved target is normal, not an error: most actions do not name an
    application at all, and an inventory that is missing or unreadable must
    leave the request classifiable rather than raise. ``source`` says which
    case this is.
    """

    raw: str
    app_id: str | None = None
    display_name: str = ""
    executable: str = ""
    launch_path: str = ""
    source: ResolutionSource = "unresolved"

    @property
    def resolved(self) -> bool:
        return self.source != "unresolved"


@dataclass(frozen=True)
class PolicyRequest:
    """One action, as presented for a decision.

    Frozen, like ``LocalActionRequest``: a request that could be edited between
    the tier being chosen and the action running is a request whose tier means
    nothing.
    """

    action_type: str
    target: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    require_approval: bool = False
    dry_run: bool = False
    origin: ActionOrigin = DEFAULT_ACTION_ORIGIN
    canonical_target: CanonicalTarget | None = None


@dataclass(frozen=True)
class PolicyDecision:
    """What policy concluded, and why.

    ``blocked_reason`` and ``approval_required`` are separate because they are
    different answers: refused outright, versus allowed once a person confirms.
    Collapsing them is how a block quietly becomes a prompt.

    ``evidence`` carries what the decision was based on -- the matched table
    entry, the resolved identity -- so an audit record can show the reasoning
    rather than just the verdict.
    """

    risk_level: RiskLevel
    approval_required: bool = False
    blocked_reason: str | None = None
    canonical_target: CanonicalTarget | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.blocked_reason is not None


#: The request and response the executor speaks in.
#:
#: **Canonical here, re-exported by ``pc_control`` (AD-028).** They moved
#: because ``desktop/`` needed them and importing them from ``pc_control`` was
#: 15 of the 18 symbols in the ``pc_control`` <-> ``desktop`` back-edge -- a
#: type-location problem, not the policy-ownership one the migration plan
#: assumed. Moving them is a dependency-direction change and nothing else:
#: fields, defaults, mutability and ``to_dict`` are unchanged from the
#: definitions that lived in ``pc_control``.
#:
#: AD-028 does not close GAP-10. ``run_local_action`` (2) and
#: ``_is_protected_path`` (1) remain, and they are behavioural edges needing
#: their own design.


@dataclass(frozen=True)
class LocalActionRequest:
    action_type: str
    target: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    require_approval: bool = False
    dry_run: bool = False
    origin: ActionOrigin = DEFAULT_ACTION_ORIGIN


@dataclass
class LocalActionResponse:
    ok: bool
    action_id: str | None
    status: ActionStatus
    message: str
    approval_required: bool
    risk_level: RiskLevel
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action_id": self.action_id,
            "status": self.status,
            "message": self.message,
            "approval_required": self.approval_required,
            "risk_level": self.risk_level,
            "evidence": self.evidence,
            "error": self.error,
        }


__all__ = [
    "ACTION_ORIGINS",
    "ActionOrigin",
    "ActionStatus",
    "CanonicalTarget",
    "DEFAULT_ACTION_ORIGIN",
    "LocalActionRequest",
    "LocalActionResponse",
    "PolicyDecision",
    "PolicyRequest",
    "ResolutionSource",
    "RiskLevel",
]
