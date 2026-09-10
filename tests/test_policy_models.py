"""The policy vocabulary, before anything speaks it.

``grandpa.policy.models`` is types only: no rules, no resolution, no I/O, and
no caller. These tests hold the two properties that make the later steps
possible at all.

The first is dependency direction. The kernel baseline guard counts every
module importing ``pc_control`` or ``local_actions``: **45 files against a
ceiling of 53**, so there are eight of headroom. That headroom grants nothing.
The guard's binding assertion is a per-category set difference -- any module
not already on the recorded list fails it regardless of the total -- so a
policy package importing either would trip the guard at 45 exactly as it would
at 53, and would also invert the dependency the migration exists to create:
policy is what the executor calls, not the reverse. Checking it here as well as
in the guard means the failure names the cause.

(An earlier version of this paragraph said the count was saturated at 51 of 51.
It was true when written and stopped being true as later slices removed
importers; the ceiling itself has since been raised to 53 by the one approved
addition, which ``test_the_baseline_guard_total_is_53`` below pins.)

The second is that this step changed nothing. A module nothing imports cannot
alter behaviour, and the assertions below say so in the form a later reader
will want: the existing risk vocabulary is untouched and still lives where it
did.
"""

from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from grandpa.policy.models import (
    DEFAULT_ACTION_ORIGIN,
    CanonicalTarget,
    PolicyDecision,
    PolicyRequest,
)

MODELS_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "grandpa" / "policy" / "models.py"
)


# ---------------------------------------------------------------------------
# They exist and can be built
# ---------------------------------------------------------------------------


class TestTheTypesAreUsable:
    def test_a_request_needs_only_an_action_type(self):
        request = PolicyRequest(action_type="open_app")

        assert request.action_type == "open_app"
        assert request.target == ""
        assert request.origin == DEFAULT_ACTION_ORIGIN
        assert request.canonical_target is None

    def test_a_request_carries_what_the_caller_asked_for(self):
        request = PolicyRequest(
            action_type="file_delete",
            target="report.pdf",
            args={"recursive": False},
            require_approval=True,
            dry_run=True,
            origin="voice",
        )

        assert request.args == {"recursive": False}
        assert request.require_approval is True
        assert request.dry_run is True
        assert request.origin == "voice"

    def test_a_decision_needs_only_a_tier(self):
        decision = PolicyDecision(risk_level="LOW")

        assert decision.risk_level == "LOW"
        assert decision.approval_required is False
        assert decision.blocked is False

    def test_a_blocked_decision_says_why(self):
        decision = PolicyDecision(risk_level="BLOCKED", blocked_reason="shell_run")

        assert decision.blocked is True
        assert decision.blocked_reason == "shell_run"

    def test_blocking_and_asking_are_different_answers(self):
        """Refused outright is not the same as allowed once confirmed;
        collapsing them is how a block becomes a prompt."""
        asked = PolicyDecision(risk_level="HIGH", approval_required=True)
        refused = PolicyDecision(risk_level="BLOCKED", blocked_reason="shell_run")

        assert asked.blocked is False
        assert refused.approval_required is False

    def test_an_unresolved_target_is_a_normal_state(self):
        """Most actions name no application, and a missing inventory must leave
        a request classifiable rather than raise."""
        target = CanonicalTarget(raw="wsl")

        assert target.resolved is False
        assert target.source == "unresolved"
        assert target.app_id is None

    def test_a_resolved_target_keeps_both_names(self):
        """The decision needs the resolved identity; the audit record needs the
        words the user actually used."""
        target = CanonicalTarget(
            raw="wsl",
            app_id="wsl",
            display_name="WSL",
            executable="wsl.exe",
            launch_path="C:/x/WSL.lnk",
            source="inventory",
        )

        assert target.raw == "wsl"
        assert target.display_name == "WSL"
        assert target.resolved is True

    def test_a_request_can_carry_a_resolved_target(self):
        request = PolicyRequest(
            action_type="open_app",
            target="wsl",
            canonical_target=CanonicalTarget(raw="wsl", source="inventory"),
        )

        assert request.canonical_target is not None
        assert request.canonical_target.resolved is True


class TestTheyAreFrozen:
    """A request editable between the tier being chosen and the action running
    is a request whose tier means nothing."""

    def test_a_request_cannot_be_edited(self):
        request = PolicyRequest(action_type="open_app")

        with pytest.raises(FrozenInstanceError):
            request.action_type = "shell_run"  # type: ignore[misc]

    def test_a_decision_cannot_be_edited(self):
        decision = PolicyDecision(risk_level="LOW")

        with pytest.raises(FrozenInstanceError):
            decision.risk_level = "BLOCKED"  # type: ignore[misc]

    def test_a_canonical_target_cannot_be_edited(self):
        target = CanonicalTarget(raw="wsl")

        with pytest.raises(FrozenInstanceError):
            target.raw = "chrome"  # type: ignore[misc]

    def test_mutable_defaults_are_not_shared(self):
        first = PolicyRequest(action_type="open_app")
        second = PolicyRequest(action_type="open_app")
        first.args["poisoned"] = True

        assert second.args == {}


# ---------------------------------------------------------------------------
# Dependency direction
# ---------------------------------------------------------------------------


class TestItDependsOnNothingItShouldNot:
    @staticmethod
    def _imported_modules() -> set[str]:
        tree = ast.parse(MODELS_PATH.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        return modules

    def test_it_does_not_import_pc_control(self):
        assert not any("pc_control" in module for module in self._imported_modules())

    def test_it_does_not_import_local_actions(self):
        assert not any("local_actions" in module for module in self._imported_modules())

    def test_it_imports_nothing_from_grandpa_at_all(self):
        """Not merely the two counted modules: a types module with no internal
        dependencies is one no future step can be blocked by."""
        assert not any(
            module.startswith("grandpa") for module in self._imported_modules()
        )

    def test_it_uses_only_the_standard_library(self):
        assert self._imported_modules() <= {"__future__", "dataclasses", "typing"}


# ---------------------------------------------------------------------------
# Nothing moved
# ---------------------------------------------------------------------------


class TestNothingElseChanged:
    def test_the_baseline_guard_total_is_53(self):
        """The ceiling this migration must not raise except deliberately. It
        was 51 while every file entry surface still bypassed the boundary; the
        composition layer that ended that is the one approved addition, and
        ``tests/test_file_composition.py`` pins which module it is. Anything
        else importing either funnel still shows up here first."""
        baseline = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "tests"
                / "architecture"
                / "direct_executor_baseline.json"
            ).read_text(encoding="utf-8")
        )

        # 53 since 4.5H-3: ``composition/ask_handlers.py`` is the approved
        # application-level composition consumer of ``local_actions``,
        # added for the ask.py dispatcher migration. Still an exact count,
        # so any further importer has to come past this line.
        assert sum(len(paths) for paths in baseline.values()) == 53
        assert "src/grandpa/composition/files.py" in baseline["pc_control"]

    def test_only_the_intended_modules_import_the_new_package(self):
        """The list is pinned rather than removed, so each new dependant is a
        decision rather than a discovery.

        Four so far, and they arrived for different reasons. ``pc_control``
        delegates classification here. ``files/executor.py`` names the mutation
        seam here -- which is the whole point of the boundary protocol: a
        capability package may depend on ``policy``, and must not depend on the
        execution module. ``composition/files.py`` names the same seam to type
        the runner it injects; it is the layer that wires the two together, and
        the only one permitted to know the concrete actuator.

        ``dispatch/context.py`` takes only ``ActionOrigin``, the provenance
        vocabulary. ``RequestContext`` requires an origin and defaults it to
        nothing, so the dispatcher has to name the type it demands -- and the
        alternative was a third copy of ``Literal["voice", "agent", "direct"]``
        beside the two that already exist in ``policy.models`` and
        ``pc_control``. Reconciling those two is 4.12's work; adding a third
        here would have made it worse. It imports no policy *behaviour*: no
        engine, no resolver, no decision type.

        The direction is what matters and is held by the sibling tests: policy
        imports nothing back.

        **Eight more since AD-028.1**, all of ``desktop/control/``. They are the
        canonical typed Windows capability services, and the layering
        ``entry surfaces -> dispatch -> policy -> capability packages -> core``
        puts ``policy`` above them: a capability package may depend on it. Each
        was importing ``LocalActionResponse`` (or, in ``windows.py``,
        ``LocalActionRequest``) from ``pc_control`` -- the execution module,
        which is the side of the line the boundary protocol says they must not
        reach. Repointing them at ``policy.models`` moves them onto the
        permitted direction; it is the same reasoning that admitted
        ``files/executor.py``.

        They take models and nothing else -- no engine, no resolver, no
        decision type -- and the class objects are identical either way, since
        ``pc_control`` re-exports rather than redefines. ``applications.py``
        still imports ``_is_protected_path`` from ``pc_control`` at one site;
        AD-028.1 deliberately left that outside its scope, so that edge is
        still counted against the execution module here.

        **One more with the §4.11 approval-predicate extraction**:
        ``desktop/kernel/risk.py``. It is the thirteenth and the first from
        ``desktop/kernel/``, which is a different kind of dependant from the
        eight above -- not a capability package but the facade over the
        execution module -- so it is worth being explicit about why it is
        admitted. It already imported ``pc_control`` and still does, for the
        risk tables; what changed is that the approval *rule* it evaluates now
        lives in ``policy.engine`` instead of being a second copy of the live
        gate's condition. That points one of its dependencies at ``policy``
        rather than adding a dependency on the execution module, which is the
        direction the migration wants.

        It takes ``requires_approval`` -- policy *behaviour*, unlike every
        entry above it except ``pc_control`` itself. That is the point of the
        extraction, and it is bounded: the function decides nothing, because
        enforcement stays inline in ``pc_control._run_local_action_impl``.
        ``tests/test_kernel_approval_facade.py`` holds that line, and
        ``tests/test_policy_approval_predicate_parity.py`` holds the answer.

        Authorised by **AD-028.2**, which also settles how AD-028.1 e should be
        read: that decision's "no ``desktop/kernel/`` dependency change is
        authorised" concerned the existing ``desktop/kernel -> pc_control``
        set within its own slice -- the 24 statements it names, still exactly
        as they were -- and not the addition of this policy dependency.
        AD-028.2 authorises ``risk.py`` and ``requires_approval`` alone; the
        other five ``desktop/kernel/`` modules are not admitted by it, and a
        further policy dependency from this package needs its own record.
        """
        root = Path(__file__).resolve().parents[1] / "src" / "grandpa"
        importers = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if "grandpa.policy" in path.read_text(encoding="utf-8")
            and path.parent.name != "policy"
        )

        assert importers == [
            "composition/files.py",
            "desktop/control/applications.py",
            "desktop/control/automation.py",
            "desktop/control/clipboard.py",
            "desktop/control/diagnostics.py",
            "desktop/control/files.py",
            "desktop/control/monitors.py",
            "desktop/control/power.py",
            "desktop/control/windows.py",
            "desktop/kernel/risk.py",
            "dispatch/context.py",
            "files/executor.py",
            "pc_control.py",
        ]

    def test_the_live_risk_vocabulary_is_untouched(self):
        from grandpa import pc_control

        assert pc_control.ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )
        assert pc_control.DEFAULT_ACTION_ORIGIN == "direct"
        assert len(pc_control.SENSITIVE_APP_RISK) == 21

    def test_the_new_request_mirrors_the_live_one(self):
        """A faithful translation, not a redesign: proving equivalence later
        depends on these matching now."""
        from grandpa.pc_control import LocalActionRequest

        live = {field.name for field in fields(LocalActionRequest)}
        proposed = {field.name for field in fields(PolicyRequest)}

        assert live <= proposed
        assert proposed - live == {"canonical_target"}
