"""What ``classify_risk`` decides today, recorded before it moves.

This is a characterisation suite, not a specification. It says what the current
classifier does -- including anything it does by accident -- so that extracting
the logic into ``grandpa.policy.engine`` can be shown to change nothing. A test
here failing after the extraction means the extraction altered behaviour, which
is the one thing it must not do.

The matrix is derived from the implementation rather than hand-picked: every
action type in the four tier tables, every key in ``SENSITIVE_APP_RISK``, and
the normalisation and fallback paths around them. Sampling would leave exactly
the gaps a migration slips through.
"""

from __future__ import annotations

import pytest

from grandpa import pc_control
from grandpa.pc_control import LocalActionRequest

ALL_ACTIONS = sorted(
    set(pc_control.LOW_RISK_ACTIONS)
    | set(pc_control.MEDIUM_RISK_ACTIONS)
    | set(pc_control.HIGH_RISK_ACTIONS)
    | set(pc_control.BLOCKED_ACTIONS)
)

EXPECTED_TIER = {
    **{action: "BLOCKED" for action in pc_control.BLOCKED_ACTIONS},
    **{action: "HIGH" for action in pc_control.HIGH_RISK_ACTIONS},
    **{action: "MEDIUM" for action in pc_control.MEDIUM_RISK_ACTIONS},
    **{action: "LOW" for action in pc_control.LOW_RISK_ACTIONS},
}

SENSITIVE_KEYS = sorted(pc_control.SENSITIVE_APP_RISK)

ORDINARY_TARGETS = (
    "chrome",
    "notepad",
    "calculator",
    "vscode",
    "paint",
    "settings",
    "some-random-app",
    "",
)


def _request(action_type: str, target: str = "", **extra) -> LocalActionRequest:
    return LocalActionRequest(action_type=action_type, target=target, **extra)


# ---------------------------------------------------------------------------
# Every action type
# ---------------------------------------------------------------------------


class TestEveryActionType:
    def test_the_matrix_covers_every_known_action(self):
        """If a tier table grows, this suite must grow with it."""
        assert len(ALL_ACTIONS) == 70
        assert set(ALL_ACTIONS) == set(EXPECTED_TIER)

    def test_no_action_appears_in_two_tiers(self):
        """Tier lookup is ordered, so an overlap would make the order
        load-bearing in a way nothing documents."""
        tiers = (
            set(pc_control.LOW_RISK_ACTIONS),
            set(pc_control.MEDIUM_RISK_ACTIONS),
            set(pc_control.HIGH_RISK_ACTIONS),
            set(pc_control.BLOCKED_ACTIONS),
        )
        for index, first in enumerate(tiers):
            for second in tiers[index + 1 :]:
                assert not (first & second)

    @pytest.mark.parametrize("action", ALL_ACTIONS)
    def test_each_action_classifies_as_recorded(self, action):
        assert pc_control.classify_risk(_request(action)) == EXPECTED_TIER[action]

    def test_an_unknown_action_is_blocked(self):
        """Default deny: the fallback is BLOCKED, not LOW."""
        assert pc_control.classify_risk(_request("no_such_action")) == "BLOCKED"

    @pytest.mark.parametrize(
        "raw", ["OPEN_APP", "  open_app  ", "open-app", "open app", "Open-App"]
    )
    def test_the_action_type_is_normalised(self, raw):
        """Case, surrounding space, hyphens and spaces all fold."""
        assert pc_control.classify_risk(_request(raw)) == "LOW"

    def test_normalisation_does_not_invent_matches(self):
        assert pc_control.classify_risk(_request("open__app")) == "BLOCKED"
        assert pc_control.classify_risk(_request("openapp")) == "BLOCKED"


# ---------------------------------------------------------------------------
# Sensitive applications
# ---------------------------------------------------------------------------


class TestSensitiveTargets:
    @pytest.mark.parametrize("key", SENSITIVE_KEYS)
    def test_each_sensitive_key_raises_the_tier(self, key):
        expected = pc_control.SENSITIVE_APP_RISK[key]

        assert pc_control.classify_risk(_request("open_app", key)) == expected

    @pytest.mark.parametrize("key", SENSITIVE_KEYS)
    def test_case_and_padding_do_not_evade_it(self, key):
        expected = pc_control.SENSITIVE_APP_RISK[key]
        padded = f"  {key.upper()}  "

        assert pc_control.classify_risk(_request("open_app", padded)) == expected

    def test_the_alias_table_is_consulted(self):
        """ "windows terminal" resolves through SAFE_APP_ALIASES to "terminal"."""
        assert pc_control.classify_risk(_request("open_app", "windows terminal")) == (
            pc_control.classify_risk(_request("open_app", "terminal"))
        )

    def test_the_raw_name_is_used_when_the_alias_leads_nowhere(self, monkeypatch):
        """The lookup tries the resolved id and then the name as typed."""
        from grandpa.desktop.control import applications

        monkeypatch.setitem(
            applications.SAFE_APP_ALIASES, "powershell", "not_in_the_table"
        )

        assert pc_control.classify_risk(_request("open_app", "powershell")) == "MEDIUM"

    @pytest.mark.parametrize("target", ORDINARY_TARGETS)
    def test_an_ordinary_target_stays_low(self, target):
        assert pc_control.classify_risk(_request("open_app", target)) == "LOW"

    @pytest.mark.parametrize(
        "target", ["cmdr", "wtf", "regedit viewer", "diskpartition", "cmd.com"]
    )
    def test_matching_is_exact_not_substring(self, target):
        assert pc_control.classify_risk(_request("open_app", target)) == "LOW"

    @pytest.mark.parametrize("key", SENSITIVE_KEYS)
    def test_only_open_app_consults_the_table(self, key):
        """detect_app reports installation and launches nothing."""
        assert pc_control.classify_risk(_request("detect_app", key)) == "LOW"

    @pytest.mark.parametrize("action", ["focus_window", "close_window", "volume_up"])
    def test_other_actions_ignore_the_target(self, action):
        plain = pc_control.classify_risk(_request(action, "chrome"))

        assert pc_control.classify_risk(_request(action, "regedit")) == plain


# ---------------------------------------------------------------------------
# What classification does not look at
# ---------------------------------------------------------------------------


class TestClassificationIgnores:
    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_origin_does_not_change_the_tier(self, origin):
        assert pc_control.classify_risk(
            _request("file_delete", "x", origin=origin)
        ) == ("HIGH")
        assert pc_control.classify_risk(_request("open_app", "wsl", origin=origin)) == (
            "LOW"
        )

    def test_dry_run_does_not_change_the_tier(self):
        """Dry run is enforced later, in the request path, not here."""
        assert pc_control.classify_risk(_request("file_delete", "x", dry_run=True)) == (
            "HIGH"
        )

    def test_require_approval_does_not_change_the_tier(self):
        """Approval is a separate question from consequence."""
        assert (
            pc_control.classify_risk(
                _request("open_app", "chrome", require_approval=True)
            )
            == "LOW"
        )

    def test_an_emergency_stop_does_not_change_the_tier(self, monkeypatch):
        monkeypatch.setattr(pc_control, "_EMERGENCY_STOP_ACTIVE", True)

        assert pc_control.classify_risk(_request("open_app", "chrome")) == "LOW"

    def test_args_do_not_change_the_tier(self):
        assert pc_control.classify_risk(
            _request("keyboard_hotkey", "focused", args={"keys": "win+r"})
        ) == pc_control.classify_risk(_request("keyboard_hotkey", "focused"))


# ---------------------------------------------------------------------------
# Safety interactions, recorded where they actually live
# ---------------------------------------------------------------------------


class TestSafetyInteractions:
    @pytest.mark.parametrize("action", ["shell_run", "script_run"])
    def test_shell_and_script_are_blocked_by_tier(self, action):
        assert pc_control.classify_risk(_request(action, "anything")) == "BLOCKED"

    @pytest.mark.parametrize("action", sorted(pc_control.APPROVAL_REQUIRED_ACTIONS))
    def test_approval_required_actions_keep_their_own_tier(self, action):
        """Approval is decided by the gate, not by the tier -- these are not
        forced to HIGH."""
        assert pc_control.classify_risk(_request(action)) == EXPECTED_TIER[action]

    def test_win_r_is_refused_by_preflight_not_by_classification(self):
        """Recorded so the extraction is not expected to reproduce it: the
        tier for keyboard_hotkey is unremarkable, and the refusal happens
        later in the request path."""
        assert pc_control.classify_risk(
            _request("keyboard_hotkey", "focused", args={"keys": "win+r"})
        ) in {"LOW", "MEDIUM", "HIGH"}

    def test_the_launch_approval_predicate_is_separate_from_the_tier(self):
        """``_launch_needs_approval`` is not part of classification and is not
        being moved in this slice."""
        assert pc_control._launch_needs_approval(_request("open_app", "terminal"))
        assert not pc_control._launch_needs_approval(_request("open_app", "chrome"))


# ---------------------------------------------------------------------------
# Exceptions, as they are today
# ---------------------------------------------------------------------------


class TestCurrentExceptionBehaviour:
    def test_a_request_without_an_action_type_raises(self):
        """The classifier reads action_type directly; only the target is read
        defensively. Recorded so the extraction preserves it."""

        class Bare:
            target = "x"

        with pytest.raises(AttributeError):
            pc_control.classify_risk(Bare())

    def test_a_request_without_a_target_still_classifies(self):
        class NoTarget:
            action_type = "open_app"

        assert pc_control.classify_risk(NoTarget()) == "LOW"

    def test_a_none_target_is_treated_as_empty(self):
        assert pc_control.classify_risk(_request("open_app", None)) == "LOW"  # type: ignore[arg-type]
