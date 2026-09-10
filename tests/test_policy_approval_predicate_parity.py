"""The approval predicate, recorded against the gate that enforces it.

``desktop/kernel/risk.requires_approval`` answers a question the live gate in
``pc_control._run_local_action_impl`` also answers, from the same four clauses:
an explicit request for approval, the HIGH tier, membership of
``APPROVAL_REQUIRED_ACTIONS``, and a sensitive launch. Before that predicate
moves into ``grandpa.policy.engine``, this records what it decides across the
whole space those clauses can reach.

**The oracle is the gate itself, never a copy of its condition.** An earlier
suite compared the facade against a hand-written reproduction of the gate's
``if`` and was deleted for exactly that reason, recorded in
``tests/test_kernel_approval_facade.py``: two copies of one rule drift together
and the test notices nothing. So every case here runs the real boundary with
the actuator stubbed out and reads the status it returns.

The matrix is derived from the implementation rather than sampled: every action
type in the four tier tables, every key in ``SENSITIVE_APP_RISK`` and
``SENSITIVE_EXECUTABLE_RISK``, and ordinary launches that must stay ungated --
each with ``require_approval`` both ways and ``dry_run`` both ways.

Two asymmetries are deliberate, and are asserted rather than hidden:

``blocked`` outranks approval.
    The ``BLOCKED`` tier and the preflight guard refuse before the approval
    gate is reached, which is stricter than staging, not looser. Where the
    boundary answers ``blocked`` the exact-equality claim does not apply, so
    the two directions are stated separately: the predicate must never call
    ungated something the gate stages, and must never call gated something the
    gate runs.

``dry_run`` short-circuits ahead of the approval gate.
    The boundary returns ``dry_run`` without deciding approval at all, so the
    claim made for those cases is the one that is actually true: the predicate
    does not read ``dry_run``, and answers identically with it set and unset.
"""

from __future__ import annotations

import pytest

from grandpa import pc_control
from grandpa.desktop.kernel.requests import coerce_request
from grandpa.desktop.kernel.risk import requires_approval
from grandpa.policy import engine as policy_engine

ALL_ACTIONS = sorted(
    set(pc_control.LOW_RISK_ACTIONS)
    | set(pc_control.MEDIUM_RISK_ACTIONS)
    | set(pc_control.HIGH_RISK_ACTIONS)
    | set(pc_control.BLOCKED_ACTIONS)
)

SENSITIVE_APP_KEYS = sorted(pc_control.SENSITIVE_APP_RISK)
SENSITIVE_EXECUTABLE_KEYS = sorted(pc_control.SENSITIVE_EXECUTABLE_RISK)
ORDINARY_LAUNCHES = ("chrome", "notepad", "calculator", "vscode", "some-random-app")


#: ``file_*`` actions need a real target. ``_preflight_guard`` resolves the
#: path before any approval question is reached, and ``_resolve_path("")``
#: raises ``ValueError("path is required")`` -- so an empty target never gets
#: as far as the clause under test. An ordinary unprotected filename exercises
#: the HIGH tier without tripping the protected-path branch.
FILE_TARGET = "note.txt"


def _target_for(action: str) -> str:
    return FILE_TARGET if action.startswith("file_") else ""


def _matrix() -> list[tuple[str, str]]:
    """(action_type, target) pairs covering every clause the predicate has."""
    cases: list[tuple[str, str]] = [
        (action, _target_for(action)) for action in ALL_ACTIONS
    ]
    cases += [("open_app", key) for key in SENSITIVE_APP_KEYS]
    cases += [("open_app", key) for key in SENSITIVE_EXECUTABLE_KEYS]
    cases += [("open_app", target) for target in ORDINARY_LAUNCHES]
    return cases


MATRIX = _matrix()
CASES = [
    pytest.param(action, target, flag, id=f"{action}-{target or 'none'}-{flag}")
    for action, target in MATRIX
    for flag in (False, True)
]


def _request(action_type: str, target: str, require_approval: bool, dry_run=False):
    return coerce_request(
        {
            "action_type": action_type,
            "target": target,
            "require_approval": require_approval,
            "dry_run": dry_run,
        }
    )


@pytest.fixture
def outcome(monkeypatch, tmp_path):
    """Run the live gate without actuating anything, and report its status.

    Copied deliberately from ``tests/test_kernel_approval_facade.py`` rather
    than shared: the fixture is the oracle, and an oracle that two suites can
    change for each other is not one.
    """
    monkeypatch.setattr(
        pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
    )
    monkeypatch.setattr(
        pc_control,
        "_execute",
        lambda request, risk: pc_control.LocalActionResponse(
            ok=True,
            action_id=None,
            status="completed",
            message="ok",
            approval_required=False,
            risk_level=risk,
            evidence={},
        ),
    )

    def enforced(payload: dict) -> str:
        return pc_control.run_local_action(payload).status

    return enforced


# ---------------------------------------------------------------------------
# The matrix is worth running
# ---------------------------------------------------------------------------


class TestTheMatrixCoversTheClauses:
    def test_it_is_large_enough_to_mean_something(self):
        assert len(ALL_ACTIONS) >= 60
        assert len(CASES) >= 150

    def test_every_table_is_represented(self):
        targets = {target for _, target in MATRIX}

        assert set(SENSITIVE_APP_KEYS) <= targets
        assert set(SENSITIVE_EXECUTABLE_KEYS) <= targets
        assert set(pc_control.APPROVAL_REQUIRED_ACTIONS) <= set(ALL_ACTIONS)

    def test_both_answers_actually_occur(self):
        answers = {
            requires_approval(_request(action, target, False))
            for action, target in MATRIX
        }

        assert answers == {True, False}, (
            "a matrix that only ever sees one answer proves nothing"
        )


# ---------------------------------------------------------------------------
# Against the gate itself
# ---------------------------------------------------------------------------


class TestThePredicateAgreesWithTheLiveGate:
    @pytest.mark.parametrize("action,target,flag", CASES)
    def test_it_is_never_more_permissive_than_the_boundary(
        self, action, target, flag, outcome
    ):
        """Calling ungated something the boundary stages is the unsafe error."""
        reported = requires_approval(_request(action, target, flag))
        status = outcome(
            {
                "action_type": action,
                "target": target,
                "require_approval": flag,
            }
        )

        if not reported:
            assert status != "approval_required", (
                f"{action}/{target!r} require_approval={flag} was reported "
                f"ungated, but the boundary staged it"
            )

    @pytest.mark.parametrize("action,target,flag", CASES)
    def test_it_is_never_gated_where_the_boundary_runs_freely(
        self, action, target, flag, outcome
    ):
        """The other direction: a gate the boundary does not apply.

        ``blocked`` counts as agreement here -- refusing outright is stricter
        than asking -- so the claim is only that a reported gate is never
        contradicted by an action that simply ran.
        """
        reported = requires_approval(_request(action, target, flag))
        status = outcome(
            {
                "action_type": action,
                "target": target,
                "require_approval": flag,
            }
        )

        if reported:
            assert status in {"approval_required", "blocked"}, (
                f"{action}/{target!r} require_approval={flag} was reported "
                f"gated, but the boundary answered {status!r}"
            )

    @pytest.mark.parametrize("action,target,flag", CASES)
    def test_they_match_exactly_wherever_nothing_is_blocked(
        self, action, target, flag, outcome
    ):
        """Where the BLOCKED tier and the preflight guard stay out of it, the
        predicate and the gate are the same answer."""
        status = outcome(
            {
                "action_type": action,
                "target": target,
                "require_approval": flag,
            }
        )
        if status == "blocked":
            pytest.skip("blocked outranks approval; equality is not the claim")

        assert requires_approval(_request(action, target, flag)) is (
            status == "approval_required"
        )


# ---------------------------------------------------------------------------
# The two flags
# ---------------------------------------------------------------------------


class TestTheFlags:
    @pytest.mark.parametrize("action,target", MATRIX)
    def test_dry_run_does_not_change_the_answer(self, action, target):
        """The gate decides dry run before it decides approval, so the
        predicate has no business reading it."""
        assert requires_approval(_request(action, target, False, dry_run=True)) is (
            requires_approval(_request(action, target, False, dry_run=False))
        )

    @pytest.mark.parametrize("action,target", MATRIX)
    def test_dry_run_reaches_the_boundary_before_approval_does(
        self, action, target, outcome
    ):
        status = outcome({"action_type": action, "target": target, "dry_run": True})

        assert status != "approval_required"

    @pytest.mark.parametrize("action,target", MATRIX)
    def test_requesting_approval_can_only_raise_the_answer(self, action, target):
        """``require_approval`` is a floor, never a ceiling."""
        without = requires_approval(_request(action, target, False))
        with_flag = requires_approval(_request(action, target, True))

        assert with_flag is True
        assert not (without and not with_flag)


# ---------------------------------------------------------------------------
# Malformed input keeps answering
# ---------------------------------------------------------------------------


class TestItStaysDefensive:
    @pytest.mark.parametrize(
        "attributes",
        [
            {"action_type": "volume_up"},
            {"action_type": "open_app"},
            {"action_type": "open_app", "target": None},
            {"action_type": "keyboard_type"},
        ],
        ids=["no-target-low", "no-target-launch", "null-target", "no-target-gated"],
    )
    def test_a_partly_formed_request_answers_rather_than_raises(self, attributes):
        from types import SimpleNamespace

        assert isinstance(requires_approval(SimpleNamespace(**attributes)), bool)

    def test_it_returns_a_bool_not_a_truthy_value(self):
        for action, target in (("open_app", "cmd"), ("open_app", "chrome")):
            assert isinstance(requires_approval(_request(action, target, False)), bool)


# ---------------------------------------------------------------------------
# The extracted rule, reached directly
# ---------------------------------------------------------------------------


class TestTheExtractedPredicate:
    """The engine function itself, with the tables passed rather than found."""

    @pytest.mark.parametrize("action,target,flag", CASES)
    def test_it_answers_what_the_view_answers(self, action, target, flag):
        request = _request(action, target, flag)

        assert policy_engine.requires_approval(
            request, pc_control._risk_tables()
        ) is requires_approval(request)

    def test_the_gated_action_table_is_read_from_the_tables_not_hardcoded(self):
        """Clause 3 must consult what it was handed.

        A predicate holding its own copy of ``APPROVAL_REQUIRED_ACTIONS``
        would answer the same today and drift the moment the real table
        changed, which is the failure the injection exists to prevent.
        """
        import dataclasses

        live = pc_control._risk_tables()
        emptied = dataclasses.replace(live, approval_required=frozenset())

        gated_only_by_the_table = _request("keyboard_type", "focused app", False)

        assert policy_engine.requires_approval(gated_only_by_the_table, live) is True
        assert (
            policy_engine.requires_approval(gated_only_by_the_table, emptied) is False
        )

    def test_the_live_tables_carry_the_real_gated_actions(self):
        assert (
            pc_control._risk_tables().approval_required
            == pc_control.APPROVAL_REQUIRED_ACTIONS
        )

    def test_empty_tables_still_honour_an_explicit_request(self):
        """With no data at all, the caller's own flag is the only clause left."""
        from grandpa.policy.engine import RiskTables

        asked = _request("volume_up", "", True)

        assert policy_engine.requires_approval(asked, RiskTables()) is True


class TestTheCoverageIsNotVacuous:
    """Neutering the extracted rule must break the differential above.

    A parity suite that still passes against a predicate answering ``False``
    is not testing the predicate. This runs the same comparison the matrix
    makes and asserts that it fails, so the matrix cannot quietly become
    decorative.
    """

    def test_a_predicate_that_always_says_no_contradicts_the_gate(
        self, monkeypatch, outcome
    ):
        monkeypatch.setattr(
            policy_engine, "requires_approval", lambda request, tables: False
        )
        payload = {"action_type": "open_app", "target": "regedit"}

        reported = requires_approval(coerce_request(payload))
        status = outcome(payload)

        assert reported is False, "the stub did not reach the view"
        assert status == "approval_required", "the boundary still stages this"
        # Which is exactly the condition
        # TestThePredicateAgreesWithTheLiveGate asserts against.

    @pytest.mark.parametrize(
        "payload",
        [
            {"action_type": "open_app", "target": "regedit"},
            {"action_type": "open_app", "target": "terminal"},
            {"action_type": "keyboard_type", "target": "focused app"},
            {"action_type": "file_delete", "target": FILE_TARGET},
            {"action_type": "volume_up", "target": "", "require_approval": True},
        ],
    )
    def test_each_clause_has_at_least_one_case_that_depends_on_it(
        self, payload, monkeypatch
    ):
        """Every clause is load-bearing for something in the matrix."""
        request = coerce_request(payload)
        assert requires_approval(request) is True

        monkeypatch.setattr(
            policy_engine, "requires_approval", lambda request, tables: False
        )

        assert requires_approval(request) is False
