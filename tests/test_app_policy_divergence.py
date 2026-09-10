"""Characterization: what the two app-launch policies actually agree on.

``pc_control`` gates an ``open_app`` launch on ``SENSITIVE_APP_RISK``, while
``local_actions`` decides from its own ``_APP_ALLOWLIST`` and
``_DANGEROUS_PATTERNS``.  Neither table is derived from the other --
``local_actions`` contains no reference to ``SENSITIVE_APP_RISK`` at all -- so
whether they agree is an empirical question rather than a structural guarantee.

These tests answer it *only* where shipped code and constants settle it.  The
app inventory is a real-machine, SQLite-backed read, so any claim that depends
on it is out of scope here and is documented as such rather than manufactured
with a fixture.

Two things this file is careful **not** to do.

It does not treat "two textual paths behaved differently" as a policy
divergence.  ``local_actions`` filters on words and ``pc_control`` classifies on
application identity, so those two can differ without the underlying policies
disagreeing about anything.  A divergence is only claimed where both sides
resolve the *same canonical application id* and then assign it different
policy, which is true of exactly one application today.

It does not execute anything.  Nothing here calls ``handle_local_action``,
because that orchestrator writes to SQLite through ``_audit_decision`` (the
approval store) and ``_log_attempt`` (``record_activity``) before it returns --
including on the blocked path.  The pure predicates underneath it are
characterized instead, which is both side-effect free and a sharper
instrument: it separates policy from orchestration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa import local_actions as la
from grandpa import pc_control
from grandpa.local_actions import _APP_ALLOWLIST, _is_dangerous, _normalise
from grandpa.pc_control import SENSITIVE_APP_RISK, LocalActionRequest
from grandpa.windows_app_resolver import APP_DEFINITIONS


def _derived_sensitive_launchable() -> set[str]:
    """The sensitive *launchable* apps, derived rather than restated.

    Deriving this is the point: hard-coding the pair would make the suite agree
    with itself instead of with the shipped tables, and adding a launch
    definition for ``regedit`` would then go unnoticed.
    """
    return set(APP_DEFINITIONS) & set(SENSITIVE_APP_RISK)


DERIVED = sorted(_derived_sensitive_launchable())


class TestDerivedSensitiveLaunchableSet:
    def test_intersection_is_exactly_task_manager_and_terminal(self) -> None:
        """Pins today's set so a new launchable shell has to come past here."""
        assert _derived_sensitive_launchable() == {"task_manager", "terminal"}

    def test_no_app_becomes_sensitive_only_through_aliasing(self) -> None:
        """The alias-resolved sweep must not exceed the raw key intersection.

        ``_sensitive_app_risk`` resolves through ``SAFE_APP_ALIASES``, so an app
        id could in principle be sensitive under an alias without its own key
        appearing in ``SENSITIVE_APP_RISK``.  Today it does not, which is what
        makes the plain key intersection a sound derivation.
        """
        alias_resolved = {
            app_id
            for app_id in APP_DEFINITIONS
            if pc_control._sensitive_app_risk(app_id) is not None
        }
        assert alias_resolved == _derived_sensitive_launchable()

    def test_every_sensitive_app_has_a_concrete_launch_definition(self) -> None:
        """Sensitive *and* launchable means there is something to launch."""
        for app_id in DERIVED:
            definition = APP_DEFINITIONS[app_id]
            assert definition.app_id == app_id
            assert definition.executable_names, app_id
            assert definition.system_command or definition.common_paths, app_id

    def test_sensitive_names_outside_the_intersection_are_not_launchable(self) -> None:
        """Being listed as sensitive must not confer a launch definition.

        ``SENSITIVE_APP_RISK`` carries names like ``regedit`` and ``diskpart``
        that ``APP_DEFINITIONS`` deliberately does not define.  Listing a name
        as risky is not the same as teaching the resolver to launch it.
        """
        outside = set(SENSITIVE_APP_RISK) - _derived_sensitive_launchable()
        assert outside, "expected sensitive names with no launch definition"
        for name in outside:
            assert name not in APP_DEFINITIONS


class TestPcControlPolicy:
    """The ``pc_control`` half: both derived apps are MEDIUM and gated.

    ``_launch_needs_approval`` takes a ``LocalActionRequest``; there is no
    ``(action_type, target)`` two-argument form, so the request is built here
    rather than the shipped signature being worked around.
    """

    @pytest.mark.parametrize("app_id", DERIVED)
    def test_sensitive_app_risk_is_medium(self, app_id: str) -> None:
        assert pc_control._sensitive_app_risk(app_id) == "MEDIUM"

    @pytest.mark.parametrize("app_id", DERIVED)
    def test_launch_needs_approval(self, app_id: str) -> None:
        request = LocalActionRequest(action_type="open_app", target=app_id)
        assert pc_control._launch_needs_approval(request) is True

    @pytest.mark.parametrize("app_id", DERIVED)
    def test_only_open_app_is_gated(self, app_id: str) -> None:
        """The gate keys on the action type, not the target alone."""
        request = LocalActionRequest(action_type="focus_window", target=app_id)
        assert pc_control._launch_needs_approval(request) is False


class TestLocalActionsDeterministicSurface:
    """The ``local_actions`` half, only where inventory is not involved."""

    def test_task_manager_text_is_not_dangerous(self) -> None:
        """No pattern intercepts it, so the text reaches app parsing."""
        assert _is_dangerous(_normalise("open task manager")) is False

    def test_task_manager_resolves_without_consulting_inventory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exact-allowlist hit short-circuits ahead of every inventory read.

        ``resolve_fuzzy_app`` consults ``grandpa.apps.inventory.find_app`` twice,
        but only after the exact ``_APP_ALLOWLIST`` check has had its chance.
        Recording calls rather than raising, because the two inventory lookups
        sit inside ``except Exception: pass`` and would swallow a raise --
        making an inventory read look like an absence of one.
        """
        import grandpa.apps.inventory as inventory

        seen: list[tuple] = []
        monkeypatch.setattr(
            inventory, "find_app", lambda *a, **k: seen.append(a) or None
        )

        app_id, confidence, label = la.resolve_fuzzy_app("task manager")

        assert (app_id, confidence, label) == ("task_manager", 1.0, "Task Manager")
        assert seen == [], "inventory was consulted for an exact allowlist hit"

    def test_terminal_text_is_intercepted_before_app_resolution(self) -> None:
        """The text filter blocks it well before identity is considered.

        This is why ``terminal`` cannot be compared with ``task_manager``: the
        outcome is decided by ``\\bterminal\\b``, and app policy never runs.
        """
        assert _is_dangerous(_normalise("open terminal")) is True
        assert _is_dangerous(_normalise("open windows terminal")) is True

    def test_terminal_is_absent_from_the_local_actions_allowlist(self) -> None:
        assert "terminal" not in _APP_ALLOWLIST
        assert "windows terminal" not in _APP_ALLOWLIST


class TestTerminalWtAsymmetry:
    """The ``terminal`` / ``wt`` split, to the exact depth shipped code settles.

    ``APP_DEFINITIONS["terminal"]`` lists ``wt`` as an alias, so the resolver
    treats the two as one application.  ``_DANGEROUS_PATTERNS`` carries
    ``\\bterminal\\b`` and no ``wt`` pattern, so the text filter does not: one
    spelling of the same application is intercepted and the other is not.

    That asymmetry is deterministic and is asserted.  What ``wt`` would then
    *resolve to* inside ``local_actions`` is not: ``wt`` is absent from
    ``_APP_ALLOWLIST``, so resolution falls through to the inventory, and that
    is a real-machine read this suite will not stage.
    """

    def test_wt_and_terminal_are_the_same_application_to_the_resolver(self) -> None:
        assert "wt" in APP_DEFINITIONS["terminal"].aliases
        assert "terminal" in APP_DEFINITIONS["terminal"].aliases

    def test_text_filter_catches_terminal_but_not_wt(self) -> None:
        assert _is_dangerous(_normalise("open terminal")) is True
        assert _is_dangerous(_normalise("open wt")) is False

    def test_wt_resolution_is_inventory_dependent_and_not_asserted(self) -> None:
        """Documents the boundary instead of staging inventory to cross it."""
        assert "wt" not in _APP_ALLOWLIST


class TestProvenDivergence:
    """Exactly one application is provably classified differently.

    ``task_manager`` is reached by both sides as the same canonical id, without
    inventory, and they disagree: ``pc_control`` requires approval, while
    ``local_actions`` treats it as an ordinary allowlisted launch.  That is an
    app-identity divergence, not two text paths behaving differently.

    ``terminal`` is deliberately excluded.  ``local_actions`` blocks it, which
    is the more restrictive outcome, but by text filtering rather than app
    policy -- so it evidences no disagreement about the application itself.
    """

    def test_task_manager_is_gated_by_pc_control(self) -> None:
        request = LocalActionRequest(action_type="open_app", target="task_manager")
        assert pc_control._sensitive_app_risk("task_manager") == "MEDIUM"
        assert pc_control._launch_needs_approval(request) is True

    def test_task_manager_is_an_ordinary_launch_to_local_actions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import grandpa.apps.inventory as inventory

        seen: list[tuple] = []
        monkeypatch.setattr(
            inventory, "find_app", lambda *a, **k: seen.append(a) or None
        )

        assert _is_dangerous(_normalise("open task manager")) is False
        assert la.resolve_fuzzy_app("task manager")[0] == "task_manager"
        assert seen == []

    def test_both_sides_agree_on_the_identity_they_disagree_about(self) -> None:
        """The divergence is about policy, not about which app is meant."""
        assert _APP_ALLOWLIST["task manager"][0] == "task_manager"
        assert "task_manager" in APP_DEFINITIONS
        assert "task_manager" in SENSITIVE_APP_RISK


class TestDispatcherStructuralAsymmetry:
    """The two policies are independent sources, not one derived from the other.

    Characterization only: this records that ``local_actions`` reaches its own
    verdict without consulting ``pc_control``'s table, which is the structural
    reason a divergence is possible at all.
    """

    def test_local_actions_does_not_consult_pc_control_app_policy(self) -> None:
        source = Path(la.__file__).read_text(encoding="utf-8")
        for symbol in (
            "SENSITIVE_APP_RISK",
            "_sensitive_app_risk",
            "_launch_needs_approval",
        ):
            assert symbol not in source, symbol

    def test_the_two_policies_are_separate_tables(self) -> None:
        assert set(_APP_ALLOWLIST) != set(SENSITIVE_APP_RISK)
        assert "task manager" in _APP_ALLOWLIST
        assert "terminal" not in _APP_ALLOWLIST
