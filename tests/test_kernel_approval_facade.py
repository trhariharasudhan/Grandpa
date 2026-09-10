"""The kernel's approval facade must agree with the gate that actually runs.

``desktop/kernel/risk.py::requires_approval`` is part of the desktop-kernel
facade -- ``tests/test_pc_control_kernel.py`` pins it alongside
``coerce_request``, ``validate_request`` and ``classify``, under a name that
states the contract: the facades *preserve behavior*. It is also used by
``tests/test_action_origin_invariant.py`` to assert that the skill path cannot
skip an approval gate.

It computed approval from the action type and the HIGH tier alone, so it did
not know about the MEDIUM half of ``SENSITIVE_APP_RISK`` added when launching a
shell became target-aware. It answered ``False`` for ``open_app terminal``
while the live gate stages the action:

===================  ==========  ====================  ==========
target               classify    facade (before)       live gate
===================  ==========  ====================  ==========
``chrome``           LOW         False                 False
``regedit``          HIGH        True                  True
``terminal``         MEDIUM      **False**             **True**
``cmd``              MEDIUM      **False**             **True**
===================  ==========  ====================  ==========

Nothing consumes the wrong answer today -- the live gate at
``pc_control.py:322`` is what enforces -- so this was latent rather than a
hole. It is still a predicate that answers a safety question wrongly while
looking authoritative, which is how a future caller inherits a bug.

Enforcement stays exactly where it is. This makes the facade *report* what the
gate already does; it does not move, wrap, or replace the gate.
"""

from __future__ import annotations

import inspect

import pytest

from grandpa import pc_control
from grandpa.desktop.kernel.requests import coerce_request
from grandpa.desktop.kernel.risk import classify, requires_approval

SENSITIVE_LAUNCHES = (
    "cmd",
    "command prompt",
    "powershell",
    "windows powershell",
    "terminal",
    "windows terminal",
    "task manager",
    "regedit",
    "registry editor",
)

ORDINARY_LAUNCHES = ("chrome", "notepad", "calculator", "vscode", "some-random-app")


def _request(action_type: str, target: str = "", **extra):
    return coerce_request({"action_type": action_type, "target": target, **extra})


@pytest.fixture
def outcome(monkeypatch, tmp_path):
    """Run the live gate without executing anything, and report its status.

    ``approval_required`` and ``blocked`` are both refusals to run freely;
    ``completed`` is the only outcome that means the action went through.
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
# The divergence this closes
# ---------------------------------------------------------------------------


class TestSensitiveLaunchesAreReported:
    @pytest.mark.parametrize("target", SENSITIVE_LAUNCHES)
    def test_the_facade_reports_a_sensitive_launch_as_gated(self, target):
        assert requires_approval(_request("open_app", target)) is True

    @pytest.mark.parametrize("target", ORDINARY_LAUNCHES)
    def test_an_ordinary_launch_is_still_ungated(self, target):
        assert requires_approval(_request("open_app", target)) is False

    def test_the_medium_tier_is_the_half_that_was_missing(self):
        """HIGH was already reported; MEDIUM was not."""
        request = _request("open_app", "terminal")

        assert classify(request) == "MEDIUM"
        assert requires_approval(request) is True

    @pytest.mark.parametrize("target", SENSITIVE_LAUNCHES)
    def test_detecting_is_not_reported_as_gated(self, target):
        """``detect_app`` starts nothing, and the live gate does not stage it."""
        assert requires_approval(_request("detect_app", target)) is False


# ---------------------------------------------------------------------------
# Agreement with what is actually enforced
# ---------------------------------------------------------------------------


class TestFacadeAgreesWithTheLiveGate:
    """The property that matters, checked against the gate rather than a list."""

    @pytest.mark.parametrize(
        "payload",
        [
            {"action_type": "open_app", "target": "chrome"},
            {"action_type": "open_app", "target": "notepad"},
            {"action_type": "open_app", "target": "terminal"},
            {"action_type": "open_app", "target": "cmd"},
            {"action_type": "open_app", "target": "powershell"},
            {"action_type": "open_app", "target": "task manager"},
            {"action_type": "open_app", "target": "regedit"},
            {"action_type": "detect_app", "target": "regedit"},
            {"action_type": "volume_up", "target": ""},
            {"action_type": "volume_set", "target": "40"},
            {"action_type": "file_delete", "target": "note.txt"},
            {"action_type": "keyboard_hotkey", "target": "win+r"},
            {"action_type": "keyboard_type", "target": "focused app"},
            {"action_type": "mouse_click", "target": "1,1"},
            {"action_type": "system_shutdown", "target": ""},
            {"action_type": "empty_recycle_bin", "target": ""},
            {"action_type": "volume_up", "target": "", "require_approval": True},
        ],
    )
    def test_the_facade_is_never_more_permissive_than_the_boundary(
        self, payload, outcome
    ):
        """The safety-relevant direction.

        Exact equality with "was it staged?" is the wrong test: a dangerous
        hotkey like ``win+r`` is *blocked* by the preflight guard before the
        approval gate is reached, which is stricter than approval, not looser.
        What must hold is that the facade never reports an action as ungated
        when the boundary would refuse to run it.
        """
        reported = requires_approval(coerce_request(payload))
        status = outcome(payload)

        if not reported:
            assert status == "completed", (
                f"the facade reported {payload} as ungated, "
                f"but the boundary answered {status!r}"
            )

    @pytest.mark.parametrize(
        "payload",
        [
            {"action_type": "open_app", "target": "chrome"},
            {"action_type": "open_app", "target": "terminal"},
            {"action_type": "open_app", "target": "regedit"},
            {"action_type": "volume_up", "target": ""},
            {"action_type": "file_delete", "target": "note.txt"},
            {"action_type": "keyboard_type", "target": "focused app"},
        ],
    )
    def test_the_facade_matches_exactly_where_nothing_is_blocked(
        self, payload, outcome
    ):
        """Where the preflight guard does not intervene, the two agree exactly."""
        status = outcome(payload)
        assert status != "blocked", "this case is meant to reach the approval gate"

        assert requires_approval(coerce_request(payload)) is (
            status == "approval_required"
        )

    def test_a_blocked_action_is_refused_before_approval_is_asked(self, outcome):
        """Blocked outranks approval; the facade must not make it look softer."""
        payload = {"action_type": "shell_run", "target": "cmd"}

        assert outcome(payload) == "blocked"

    def test_a_dangerous_hotkey_is_blocked_rather_than_staged(self, outcome):
        """``win+r`` reaches a shell, so preflight refuses it outright."""
        assert outcome({"action_type": "keyboard_hotkey", "target": "win+r"}) == (
            "blocked"
        )
        assert requires_approval(_request("keyboard_hotkey", "win+r")) is True


# ---------------------------------------------------------------------------
# The existing facade contract is untouched
# ---------------------------------------------------------------------------


class TestFrozenFacadeContractIntact:
    def test_the_facade_signature_is_unchanged(self):
        import inspect

        assert list(inspect.signature(requires_approval).parameters) == ["request"]

    def test_the_file_delete_contract_still_holds(self):
        """Mirrors ``test_kernel_request_and_risk_facades_preserve_behavior``."""
        request = coerce_request({"action_type": "file_delete", "target": "note.txt"})

        assert classify(request) == "HIGH"
        assert requires_approval(request) is True

    @pytest.mark.parametrize("action", sorted(pc_control.HIGH_RISK_ACTIONS))
    def test_every_high_risk_action_is_still_reported(self, action):
        assert requires_approval(_request(action, "x")) is True

    @pytest.mark.parametrize("action", sorted(pc_control.APPROVAL_REQUIRED_ACTIONS))
    def test_every_approval_required_action_is_still_reported(self, action):
        assert requires_approval(_request(action, "x")) is True

    def test_require_approval_can_only_raise_never_lower(self):
        request = coerce_request(
            {"action_type": "file_delete", "target": "x", "require_approval": False}
        )

        assert requires_approval(request) is True

    def test_an_explicit_request_for_approval_is_honoured(self):
        request = coerce_request(
            {"action_type": "volume_up", "target": "", "require_approval": True}
        )

        assert requires_approval(request) is True


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_the_live_gate_is_still_the_enforcer(self, outcome):
        """The facade reports; it does not gate.

        Neutering the facade must not change what the boundary does -- that is
        what "enforcement stays in pc_control" means, and it is why this slice
        cannot have loosened anything.
        """
        import grandpa.desktop.kernel.risk as risk_module

        original = risk_module.requires_approval
        risk_module.requires_approval = lambda request: False
        try:
            assert outcome({"action_type": "open_app", "target": "regedit"}) == (
                "approval_required"
            )
            assert outcome({"action_type": "open_app", "target": "terminal"}) == (
                "approval_required"
            )
        finally:
            risk_module.requires_approval = original

    def test_no_risk_table_was_changed(self):
        assert "open_app" in pc_control.LOW_RISK_ACTIONS
        assert "shell_run" in pc_control.BLOCKED_ACTIONS
        assert "script_run" in pc_control.BLOCKED_ACTIONS

    def test_the_origin_vocabulary_is_unchanged(self):
        assert pc_control.ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )

    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_the_facade_does_not_depend_on_provenance(self, origin):
        """Q-10 stays open: origin still selects nothing."""
        request = coerce_request(
            {"action_type": "open_app", "target": "terminal", "origin": origin}
        )

        assert requires_approval(request) is True

    # -----------------------------------------------------------------------
    # Malformed input, and the invariants that keep enforcement where it is.
    #
    # Merged from tests/test_kernel_approval_agreement.py, which covered the
    # same subject with a weaker oracle: it compared the facade against a
    # hand-written copy of the gate's condition rather than against the gate
    # itself, so the two could drift together. That file's duplicate cases were
    # dropped and these -- the ones with no equivalent here -- kept.
    # -----------------------------------------------------------------------

    @pytest.mark.parametrize(
        "attributes",
        [
            {"action_type": "volume_up"},
            {"action_type": "open_app"},
            {"action_type": "open_app", "target": None},
        ],
        ids=["no-target-low", "no-target-launch", "null-target"],
    )
    def test_a_request_without_a_target_does_not_raise(self, attributes):
        """A request carrying no target classifies rather than raising.

        Classification touched only the action type until target-aware launch
        risk arrived, so this held before and must keep holding -- the facade
        is consulted by callers that may hold partly-formed objects.

        A request with no ``action_type`` at all raised before that change too,
        so it is left alone: asserting otherwise would be inventing a
        requirement rather than preserving one.
        """
        from types import SimpleNamespace

        assert requires_approval(SimpleNamespace(**attributes)) is False

    @pytest.mark.parametrize(
        "attributes",
        [{"action_type": "open_app"}, {"action_type": "open_app", "target": None}],
    )
    def test_the_launch_helper_itself_is_defensive(self, attributes):
        from types import SimpleNamespace

        assert pc_control._launch_needs_approval(SimpleNamespace(**attributes)) is False

    def test_it_still_returns_a_bool(self):
        for request in (_request("open_app", "cmd"), _request("open_app", "chrome")):
            assert isinstance(requires_approval(request), bool)

    def test_classification_is_untouched(self):
        """The change was to approval, not risk."""
        assert classify(_request("open_app", "terminal")) == "MEDIUM"
        assert classify(_request("open_app", "regedit")) == "HIGH"
        assert classify(_request("open_app", "chrome")) == "LOW"

    def test_the_live_gate_is_not_relocated(self):
        """Enforcement stays inline in pc_control; the facade is only a view.

        Read from the source rather than from behaviour, because the thing
        being guarded against is a refactor -- Option B, moving the gate into
        the facade -- which would still behave correctly while relocating the
        one place enforcement happens.
        """
        source = inspect.getsource(pc_control._run_local_action_impl)

        assert "APPROVAL_REQUIRED_ACTIONS" in source
        assert "_launch_needs_approval" in source
        assert "requires_approval" not in source

    def test_the_facade_does_not_become_the_enforcement_path(self):
        """pc_control must not start delegating to the kernel facade."""
        source = inspect.getsource(pc_control)

        assert "from grandpa.desktop.kernel.risk import requires_approval" not in source
