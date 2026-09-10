"""How risky is this action? Answered without touching anything.

Extracted from ``pc_control._classify_risk_impl`` unchanged. The ordering, the
normalisation, the sensitive-application lookup and the default-deny fallback
are all reproduced exactly, because a migration that improves behaviour while
moving it cannot be shown to have preserved it.

**The tables are injected, not imported.** Classification needs four action-type
sets, the sensitive-application table, and the launcher's alias table -- and
that last one lives in ``desktop.control.applications``, which reaches back into
``pc_control``. Importing it here would point the dependency the wrong way and
put a module the kernel baseline guard counts on the wrong side of the boundary.
So the caller supplies them. ``policy`` states the rule; ``pc_control`` still
owns the data, and this slice moves no table.

That injection also removes a failure mode rather than adding one. The original
wrapped its alias import in ``try/except Exception`` and fell back to the raw
name if the import failed; with the mapping passed in there is no import to
fail, and an absent mapping gives the same answer the fallback did.

Nothing here reads a file, opens a database, resolves an inventory, or consults
an emergency stop. Those all stay where they are.
"""

from __future__ import annotations

from collections.abc import Mapping, Set
from dataclasses import dataclass, field

from grandpa.policy.models import PolicyDecision, PolicyRequest, RiskLevel


@dataclass(frozen=True)
class RiskTables:
    """The data classification reads, supplied by the caller.

    Not a policy of its own: these are exactly ``pc_control``'s existing
    constants, passed rather than imported.
    """

    blocked: Set[str] = field(default_factory=frozenset)
    high: Set[str] = field(default_factory=frozenset)
    medium: Set[str] = field(default_factory=frozenset)
    low: Set[str] = field(default_factory=frozenset)
    sensitive_apps: Mapping[str, RiskLevel] = field(default_factory=dict)
    #: Keyed on executable filename -- "git-bash.exe", never "bash" or "Git
    #: Bash". A display name is what a shortcut chose to be called; an
    #: executable filename is what actually runs. Classifying by the former is
    #: how a Tesseract helper called "Console" gets mistaken for a shell.
    #:
    #: Separate from the launch denylist on purpose: this decides the tier and
    #: therefore whether to ask, while ``BLOCKED_EXECUTABLE_NAMES`` decides
    #: whether a launch may proceed at all. An executable can be worth asking
    #: about without being refused.
    sensitive_executables: Mapping[str, RiskLevel] = field(default_factory=dict)
    aliases: Mapping[str, str] = field(default_factory=dict)
    #: Action types that must be confirmed whatever tier they land in. An axis
    #: orthogonal to the four sets above, not a fifth tier: synthetic input is
    #: recoverable, so MEDIUM is the right blast radius, but it reaches
    #: arbitrary code execution, so it is asked about regardless. Empty by
    #: default, on the same terms as every other field here -- absent data
    #: gates nothing, and the caller owns the table.
    approval_required: Set[str] = field(default_factory=frozenset)


def normalise_action_type(value: str) -> str:
    """Fold case, surrounding space, hyphens and inner spaces.

    Deliberately not more than that: ``open__app`` and ``openapp`` do not
    become ``open_app`` today, and making them would widen what the tier
    tables match.
    """
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def sensitive_app_risk(target: str, tables: RiskTables) -> RiskLevel | None:
    """The raised tier for launching *target*, or None for an ordinary app.

    Three lookups, in this order: the alias-resolved name, the name as typed,
    then the executable table. The second stops a sensitive name being lost
    when the launcher gains an alias pointing somewhere the name table does not
    list. The third recognises a program by what runs rather than by what it is
    called, and comes last so it can only add a verdict, never override one.

    Matching is exact equality on the whole string, never a substring search --
    the phrase denylist this replaced was both leaky and prone to catching
    innocent names.

    No inventory lookup, unchanged from the original: a program reachable only
    under an inventory display name outside this table is still an ordinary
    launch. That is the known gap, and closing it is not this slice.
    """
    name = str(target or "").strip().lower()
    if not name:
        return None
    resolved = tables.aliases.get(name, name)
    by_name = tables.sensitive_apps.get(resolved) or tables.sensitive_apps.get(name)
    if by_name is not None:
        return by_name
    # Checked after the name table, so an application already covered there
    # keeps the tier it already had; this can only add a verdict, never
    # replace one. Exact match on the executable filename, with no stem form
    # and no alias generation -- "git-bash" is not an executable.
    return tables.sensitive_executables.get(name)


def classify_risk(request: PolicyRequest, tables: RiskTables) -> PolicyDecision:
    """Decide the consequence tier for *request*.

    Order matters and is preserved from the original:

    1. ``BLOCKED`` first, so nothing can be rescued into a runnable tier.
    2. ``open_app`` consults the sensitive table, which may raise the tier.
       Only launching -- ``detect_app`` reports installation and starts
       nothing.
    3. HIGH, then MEDIUM, then LOW by action type.
    4. Anything unrecognised is ``BLOCKED``. Default deny.

    ``action_type`` is read directly and ``target`` defensively, matching the
    original exactly: a request too malformed to name an action raises, while
    one merely missing a target classifies.

    Origin, dry run, approval flags, args and the emergency stop are all
    ignored here, as they are today. They are enforced elsewhere in the request
    path and are not consequence.
    """
    action = normalise_action_type(request.action_type)

    if action in tables.blocked:
        return PolicyDecision(risk_level="BLOCKED", evidence={"action_type": action})

    if action == "open_app":
        sensitive = sensitive_app_risk(
            str(getattr(request, "target", "") or ""), tables
        )
        if sensitive is not None:
            return PolicyDecision(
                risk_level=sensitive,
                evidence={"action_type": action, "sensitive_app": True},
            )

    for tier, actions in (
        ("HIGH", tables.high),
        ("MEDIUM", tables.medium),
        ("LOW", tables.low),
    ):
        if action in actions:
            return PolicyDecision(
                risk_level=tier,  # type: ignore[arg-type]
                evidence={"action_type": action},
            )

    return PolicyDecision(
        risk_level="BLOCKED", evidence={"action_type": action, "unknown_action": True}
    )


def requires_approval(request: PolicyRequest, tables: RiskTables) -> bool:
    """Whether this request must be confirmed before it runs.

    Extracted from the four clauses the live gate in
    ``pc_control._run_local_action_impl`` evaluates, in the same order and with
    the same short-circuiting:

    1. the caller asked for approval explicitly,
    2. the tier is ``HIGH``,
    3. the action type is one that is always confirmed, whatever its tier,
    4. the request launches a sensitive application.

    Clause 3 is why ``approval_required`` is a table rather than a tier. Clause
    4 is what makes the MEDIUM half of the sensitive-application table ask
    before it runs -- ``open_app`` as a whole must not become approval-gated,
    or opening a browser would prompt.

    **This states the rule; it does not enforce it.** Enforcement stays inline
    in ``pc_control``, which is the single mandatory boundary and computes this
    condition itself. Nothing here is consulted by that gate, and a caller that
    treated this as the gate would be building a second enforcement point --
    exactly what ``tests/test_kernel_approval_facade.py`` exists to prevent.

    Reads defensively, matching the facade this replaces: it is reached by
    callers holding partly-formed requests, and a request too malformed to name
    a launch is not one. ``action_type`` is still read directly by
    ``classify_risk`` first, so a request with no action type raises exactly as
    it did before.

    Ignores ``dry_run`` and ``origin``, as the gate does. Dry run is decided
    earlier and actuates nothing; origin selects nothing while Q-10 is open.
    """
    risk = classify_risk(request, tables).risk_level
    action = normalise_action_type(str(getattr(request, "action_type", "") or ""))
    return bool(
        getattr(request, "require_approval", False)
        or risk == "HIGH"
        or action in tables.approval_required
        or (
            action == "open_app"
            and sensitive_app_risk(str(getattr(request, "target", "") or ""), tables)
            is not None
        )
    )


__all__ = [
    "RiskTables",
    "classify_risk",
    "normalise_action_type",
    "requires_approval",
    "sensitive_app_risk",
]
