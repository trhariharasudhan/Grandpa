"""Launching a shell or the registry editor is not an ordinary app launch.

``open_app`` sat in ``LOW_RISK_ACTIONS`` and risk was computed from the action
type alone, so every application launch was LOW and unapproved. ``shell_run``
and ``script_run`` are BLOCKED, but *launching the shell application* was not
gated at all -- and the surface denylist that was doing the work caught
``\\bcmd\\b`` while missing "command prompt", "terminal", "regedit" and "task
manager".

The fix is target-aware classification rather than more phrase matching: risk
for ``open_app`` is derived from the application being launched, resolved
through the same ``SAFE_APP_ALIASES`` table the launcher itself uses.

**A limitation worth stating.** Classification runs before execution and is
called several times per request, so it must stay cheap and side-effect free.
It can therefore consult the in-memory alias table but not the app *inventory*,
which is a SQLite read. A shell reachable only under an inventory display name
outside the table -- "Command Prompt (Admin)", say -- is still classified as an
ordinary launch. Closing that needs resolution to move ahead of classification,
which is a larger architectural change than this.

Nothing here launches anything: every test substitutes the executor.
"""

from __future__ import annotations

from typing import Any

import pytest

from grandpa import pc_control
from grandpa.pc_control import LocalActionRequest

SENSITIVE = (
    ("cmd", "MEDIUM"),
    ("cmd.exe", "MEDIUM"),
    ("command prompt", "MEDIUM"),
    ("terminal", "MEDIUM"),
    ("windows terminal", "MEDIUM"),
    ("windowsterminal", "MEDIUM"),
    ("wt", "MEDIUM"),
    ("wt.exe", "MEDIUM"),
    ("powershell", "MEDIUM"),
    ("powershell.exe", "MEDIUM"),
    ("pwsh", "MEDIUM"),
    ("pwsh.exe", "MEDIUM"),
    ("task manager", "MEDIUM"),
    ("taskmgr", "MEDIUM"),
    ("taskmgr.exe", "MEDIUM"),
    ("regedit", "HIGH"),
    ("regedit.exe", "HIGH"),
    ("registry editor", "HIGH"),
    ("diskpart", "HIGH"),
    ("diskpart.exe", "HIGH"),
)

ORDINARY = ("chrome", "notepad", "calculator", "vscode", "paint", "settings")

#: The name a user says or types, and the executable that is the same program.
#: Both spellings reach classification -- a spoken launch arrives as the stem,
#: an HTTP or agent caller can pass either -- so the two must agree.
STEM_AND_EXECUTABLE = (
    ("cmd", "cmd.exe"),
    ("wt", "wt.exe"),
    ("powershell", "powershell.exe"),
    ("pwsh", "pwsh.exe"),
    ("taskmgr", "taskmgr.exe"),
    ("regedit", "regedit.exe"),
    ("diskpart", "diskpart.exe"),
)

#: Refused outright by ``is_safe_launch_target`` at the inventory launch leaf.
#: Classification is a separate, earlier layer; these prove the two stay
#: separate rather than one standing in for the other.
REFUSED_AT_THE_LEAF = (
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "regedit.exe",
    "diskpart.exe",
)

#: Ordinary names that merely *contain* a sensitive one. Matching is exact
#: equality on the whole target, so none of these is affected -- the check
#: these guard is the one a substring or word-boundary denylist would fail.
NEAR_MISSES = (
    "cmdr",
    "wtf",
    "wt-viewer",
    "regedit viewer",
    "diskpartition",
    "powershelly",
    "taskmgr-lite",
    "terminal emulator",
)


def _request(target: str, action: str = "open_app") -> LocalActionRequest:
    return LocalActionRequest(action_type=action, target=target)


@pytest.fixture
def audit_to_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
    )


@pytest.fixture
def no_execution(monkeypatch):
    """Any execution at all is a failure in these tests."""

    def explode(request, risk):
        raise AssertionError(f"{request.action_type} on {request.target!r} executed")

    monkeypatch.setattr(pc_control, "_execute", explode)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestSensitiveTargetsAreClassifiedHigher:
    @pytest.mark.parametrize(("target", "risk"), SENSITIVE)
    def test_a_sensitive_application_gets_its_own_risk(self, target, risk):
        assert pc_control.classify_risk(_request(target)) == risk

    @pytest.mark.parametrize(("target", "risk"), SENSITIVE)
    def test_capitalisation_and_spacing_do_not_evade_it(self, target, risk):
        assert pc_control.classify_risk(_request(f"  {target.upper()}  ")) == risk

    def test_an_alias_resolves_to_the_same_risk_as_its_canonical_name(self):
        """ "windows terminal" and "terminal" are one application."""
        assert pc_control.classify_risk(_request("windows terminal")) == (
            pc_control.classify_risk(_request("terminal"))
        )

    @pytest.mark.parametrize("target", ORDINARY)
    def test_ordinary_applications_are_untouched(self, target):
        assert pc_control.classify_risk(_request(target)) == "LOW"

    def test_an_unknown_application_is_still_an_ordinary_launch(self):
        """This does not become a launcher allowlist."""
        assert pc_control.classify_risk(_request("some-random-app")) == "LOW"

    def test_an_empty_target_is_an_ordinary_launch(self):
        assert pc_control.classify_risk(_request("")) == "LOW"

    def test_open_app_remains_a_low_risk_action_type(self):
        """The tier is per-target; the action's own classification is unchanged."""
        assert "open_app" in pc_control.LOW_RISK_ACTIONS


class TestOnlyLaunchingIsAffected:
    @pytest.mark.parametrize(("target", "_risk"), SENSITIVE)
    def test_detecting_an_application_is_not_gated(self, target, _risk):
        """``detect_app`` reports whether something is installed; it launches
        nothing, so gating it would be over-reach."""
        assert pc_control.classify_risk(_request(target, "detect_app")) == "LOW"

    @pytest.mark.parametrize("action", ["focus_window", "close_window", "volume_up"])
    def test_other_actions_ignore_the_target_entirely(self, action):
        before = pc_control.classify_risk(_request("chrome", action))

        assert pc_control.classify_risk(_request("regedit", action)) == before


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


class TestApproval:
    @pytest.mark.parametrize(("target", "_risk"), SENSITIVE)
    def test_a_sensitive_launch_is_staged_for_approval(
        self, target, _risk, audit_to_tmp, no_execution
    ):
        response = pc_control.run_local_action(
            {"action_type": "open_app", "target": target}
        )

        assert response.status == "approval_required"
        assert response.approval_required is True
        assert response.action_id

    @pytest.mark.parametrize("target", ORDINARY)
    def test_an_ordinary_launch_is_not_staged(self, target, audit_to_tmp, monkeypatch):
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="opened",
                approval_required=False,
                risk_level=risk,
                evidence={},
            ),
        )

        response = pc_control.run_local_action(
            {"action_type": "open_app", "target": target}
        )

        assert response.status == "completed"
        assert response.approval_required is False

    def test_the_medium_tier_is_what_needs_the_extra_gate(
        self, audit_to_tmp, no_execution
    ):
        """HIGH is staged by the existing rule; MEDIUM would not have been."""
        assert pc_control.classify_risk(_request("terminal")) == "MEDIUM"

        response = pc_control.run_local_action(
            {"action_type": "open_app", "target": "terminal"}
        )

        assert response.status == "approval_required"


# ---------------------------------------------------------------------------
# The rest of the policy chain is unchanged
# ---------------------------------------------------------------------------


class TestPolicyChainPreserved:
    def test_shell_run_and_script_run_stay_blocked(self):
        assert "shell_run" in pc_control.BLOCKED_ACTIONS
        assert "script_run" in pc_control.BLOCKED_ACTIONS
        assert pc_control.classify_risk(_request("x", "shell_run")) == "BLOCKED"
        assert pc_control.classify_risk(_request("x", "script_run")) == "BLOCKED"

    def test_blocked_wins_over_every_other_tier(self, monkeypatch):
        """Precedence, asserted rather than inferred from disjoint tables.

        No action currently appears in two tiers, so the ordering inside the
        classifier is invisible to ordinary inputs. It still has to hold: an
        action that is blocked must classify as blocked whatever else claims
        it.
        """
        monkeypatch.setattr(
            pc_control, "LOW_RISK_ACTIONS", pc_control.LOW_RISK_ACTIONS | {"shell_run"}
        )

        assert pc_control.classify_risk(_request("cmd", "shell_run")) == "BLOCKED"

    def test_a_blocked_launch_is_not_rescued_by_the_sensitive_table(self, monkeypatch):
        """And the new tier must not be able to un-block anything."""
        monkeypatch.setattr(
            pc_control,
            "BLOCKED_ACTIONS",
            pc_control.BLOCKED_ACTIONS | {"open_app"},
        )

        assert pc_control.classify_risk(_request("regedit")) == "BLOCKED"
        assert pc_control.classify_risk(_request("chrome")) == "BLOCKED"

    def test_a_blocked_action_is_still_refused_before_approval(
        self, audit_to_tmp, no_execution
    ):
        response = pc_control.run_local_action(
            {"action_type": "shell_run", "target": "cmd"}
        )

        assert response.status == "blocked"

    def test_dry_run_still_wins_over_the_approval_gate(
        self, audit_to_tmp, no_execution
    ):
        """Dry run is checked first, so a sensitive launch can still be previewed."""
        response = pc_control.run_local_action(
            {"action_type": "open_app", "target": "regedit", "dry_run": True}
        )

        assert response.status == "dry_run"

    def test_the_risk_is_reported_in_the_dry_run_message(
        self, audit_to_tmp, no_execution
    ):
        response = pc_control.run_local_action(
            {"action_type": "open_app", "target": "regedit", "dry_run": True}
        )

        assert "HIGH" in response.message

    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_the_gate_does_not_depend_on_who_asked(
        self, origin, audit_to_tmp, no_execution
    ):
        """Risk is action- and target-derived; provenance never widens it."""
        response = pc_control.run_local_action(
            {"action_type": "open_app", "target": "regedit", "origin": origin}
        )

        assert response.status == "approval_required"

    def test_the_audit_record_carries_the_raised_risk(self, monkeypatch, tmp_path):
        import json

        log = tmp_path / "audit.log"
        monkeypatch.setattr(pc_control, "get_audit_log_path", lambda: log)

        pc_control.run_local_action(
            {"action_type": "open_app", "target": "regedit", "origin": "voice"}
        )

        record = json.loads(
            [line for line in log.read_text(encoding="utf-8").splitlines() if line][-1]
        )
        assert record["risk_level"] == "HIGH"
        assert record["approval_status"] == "pending"
        assert record["origin"] == "voice"


# ---------------------------------------------------------------------------
# The voice surface
# ---------------------------------------------------------------------------


class RecordingAutomation:
    target_window = None

    def has_pending_confirmation(self) -> bool:
        return False

    def has_pending_window_choice(self) -> bool:
        return False

    def has_pending_dialog(self) -> bool:
        return False

    def handle(self, command: str, dry_run: bool = False):
        from types import SimpleNamespace

        return SimpleNamespace(
            status="handled", message="", data={}, confirmation_token=None
        )


def _turn(text: str, runner, monkeypatch):
    from grandpa.voice.operator import process_voice_operator_turn

    monkeypatch.setattr(
        "grandpa.planner.routing.handle_executive_goal", lambda *a, **k: None
    )
    return process_voice_operator_turn(
        text, action_runner=runner, automation_service=RecordingAutomation()
    )


class TestVoiceSurface:
    @pytest.mark.parametrize(
        "phrase", ["open command prompt", "open terminal", "open task manager"]
    )
    def test_a_spoken_sensitive_launch_asks_first(
        self, phrase, monkeypatch, audit_to_tmp, no_execution
    ):
        """The denylist missed these entirely; the risk table now catches them."""
        response = _turn(phrase, pc_control.run_local_action, monkeypatch)

        assert response.requires_confirmation is True

    def test_a_spoken_ordinary_launch_still_just_runs(self, monkeypatch):
        seen: list[dict[str, Any]] = []

        def runner(payload):
            seen.append(dict(payload))
            return pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="Chrome is open.",
                approval_required=False,
                risk_level="LOW",
                evidence={},
            )

        response = _turn("open chrome", runner, monkeypatch)

        assert [p["action_type"] for p in seen] == ["open_app"]
        assert response.requires_confirmation is False

    @pytest.mark.parametrize("phrase", ["open cmd", "run powershell", "shutdown"])
    def test_the_existing_denylist_still_blocks_what_it_blocked(
        self, phrase, monkeypatch
    ):
        """Target-aware risk is additive; it does not replace the safety check."""
        seen: list[dict[str, Any]] = []

        response = _turn(phrase, lambda p: seen.append(p), monkeypatch)

        assert response.status == "blocked"
        assert seen == []


# ---------------------------------------------------------------------------
# Completing the table
# ---------------------------------------------------------------------------


class TestTheTableIsComplete:
    """The table began with the names the first slice needed and no more.

    A launch is classified from the exact string the caller passes, so every
    spelling of the same program has to be present. ``wt`` is the launcher's
    own alias for Windows Terminal, ``taskmgr`` the executable behind Task
    Manager, ``pwsh`` the shell this project records as the preferred one --
    each was an ordinary LOW launch until now.
    """

    @pytest.mark.parametrize(("stem", "executable"), STEM_AND_EXECUTABLE)
    def test_the_executable_matches_the_name(self, stem, executable):
        assert pc_control.classify_risk(_request(executable)) == (
            pc_control.classify_risk(_request(stem))
        )

    @pytest.mark.parametrize(("stem", "executable"), STEM_AND_EXECUTABLE)
    def test_neither_spelling_is_an_ordinary_launch(self, stem, executable):
        assert pc_control.classify_risk(_request(stem)) != "LOW"
        assert pc_control.classify_risk(_request(executable)) != "LOW"

    @pytest.mark.parametrize("target", ["wt", "wt.exe", "windowsterminal"])
    def test_windows_terminal_under_every_name_it_answers_to(self, target):
        """The resolver lists ``wt`` beside "terminal"; the process manager
        spells it ``windowsterminal``. One application, one tier."""
        assert pc_control.classify_risk(_request(target)) == (
            pc_control.classify_risk(_request("terminal"))
        )

    @pytest.mark.parametrize("target", ["taskmgr", "taskmgr.exe"])
    def test_task_manager_under_its_executable_name(self, target):
        assert pc_control.classify_risk(_request(target)) == (
            pc_control.classify_risk(_request("task manager"))
        )

    @pytest.mark.parametrize("target", ["pwsh", "pwsh.exe"])
    def test_the_cross_platform_shell_is_a_shell(self, target):
        """``pwsh`` is the shell this project stores as ``preferred_shell``."""
        assert pc_control.classify_risk(_request(target)) == "MEDIUM"


class TestDiskpart:
    """A partitioning tool was missing from the table entirely.

    It is the one genuinely new application here rather than a new spelling of
    an existing one: it can repartition or wipe a disk, which is why it sits
    beside the registry editor rather than beside a shell.
    """

    @pytest.mark.parametrize("target", ["diskpart", "diskpart.exe"])
    def test_diskpart_is_high_risk(self, target):
        assert pc_control.classify_risk(_request(target)) == "HIGH"

    @pytest.mark.parametrize("target", ["diskpart", "diskpart.exe"])
    def test_diskpart_is_staged_for_approval(self, target, audit_to_tmp, no_execution):
        response = pc_control.run_local_action(
            {"action_type": "open_app", "target": target}
        )

        assert response.status == "approval_required"
        assert response.risk_level == "HIGH"

    def test_diskpart_ranks_with_the_registry_editor(self):
        assert pc_control.classify_risk(_request("diskpart")) == (
            pc_control.classify_risk(_request("regedit"))
        )


class TestExactMatching:
    """Matching is equality on the whole target, not a substring search.

    This is the property that made target-aware risk worth having in the first
    place: the denylist it replaced matched ``cmd`` on a word boundary and so
    was both leaky and prone to catching innocent names. Adding a dozen keys
    must not quietly turn the table back into a phrase matcher.
    """

    @pytest.mark.parametrize("target", NEAR_MISSES)
    def test_a_name_that_merely_contains_a_sensitive_one_is_ordinary(self, target):
        assert pc_control.classify_risk(_request(target)) == "LOW"

    @pytest.mark.parametrize("target", NEAR_MISSES)
    def test_a_near_miss_is_not_staged_for_approval(self, target):
        assert pc_control._launch_needs_approval(_request(target)) is False

    def test_the_extension_is_part_of_the_name_not_a_suffix_rule(self):
        """``cmd.exe`` is listed; ``cmd.com`` and ``cmd.bat`` are not, and no
        rule invents them."""
        assert pc_control.classify_risk(_request("cmd.com")) == "LOW"
        assert pc_control.classify_risk(_request("cmd.bat")) == "LOW"


class TestTheLookupItself:
    """Two properties of ``_sensitive_app_risk`` that the table relies on."""

    def test_the_raw_name_is_still_checked_when_an_alias_leads_elsewhere(
        self, monkeypatch
    ):
        """The lookup tries the resolved id *and* the name as typed.

        Today every alias resolves to something already in the table, so the
        second lookup never decides anything and no test noticed when it was
        removed. It is what stops a sensitive name from being lost the moment
        the launcher gains an alias for it: an alias pointing at an id this
        table does not list would otherwise silently downgrade the launch.
        """
        from grandpa.desktop.control import applications

        monkeypatch.setitem(
            applications.SAFE_APP_ALIASES, "powershell", "some_other_app_id"
        )

        assert pc_control.classify_risk(_request("powershell")) == "MEDIUM"

    def test_every_executable_name_agrees_with_its_stem(self):
        """The table is symmetric, and deliberately so.

        Each ``.exe`` key is listed at the same tier as the bare name, and no
        rule derives one from the other -- both are written out. That is why
        stripping the extension before the lookup would change no answer, and
        why a future entry must add both spellings rather than rely on one.
        """
        table = pc_control.SENSITIVE_APP_RISK
        for key, tier in table.items():
            if key.endswith(".exe"):
                stem = key[: -len(".exe")]
                assert stem in table, f"{key} is listed but {stem} is not"
                assert table[stem] == tier, f"{key} and {stem} disagree"


class TestClassificationIsNotTheLaunchRefusal:
    """Two separate layers, and this slice moves only the first.

    Five of these executables are refused outright at the launch leaf by
    ``is_safe_launch_target``. Classification runs much earlier and decides
    whether to *ask*; the leaf decides whether to *run*. Listing them here
    changes the first answer and must leave the second exactly as it was --
    otherwise the table would be quietly standing in for the denylist.
    """

    @pytest.mark.parametrize("executable", REFUSED_AT_THE_LEAF)
    def test_the_launch_leaf_still_refuses_it(self, executable):
        from grandpa.apps.safety import is_safe_launch_target

        assert is_safe_launch_target(f"C:/Windows/System32/{executable}") is False

    @pytest.mark.parametrize("executable", REFUSED_AT_THE_LEAF)
    def test_classification_now_also_asks_first(self, executable):
        assert pc_control.classify_risk(_request(executable)) != "LOW"
        assert pc_control._launch_needs_approval(_request(executable)) is True

    def test_the_executable_denylist_is_unchanged(self):
        """Named explicitly so a change to it cannot pass unnoticed here."""
        from grandpa.apps.safety import BLOCKED_EXECUTABLE_NAMES

        assert set(BLOCKED_EXECUTABLE_NAMES) == {
            "cmd.exe",
            "powershell.exe",
            "pwsh.exe",
            "regedit.exe",
            "diskpart.exe",
        }

    def test_a_launchable_sensitive_app_is_gated_only_here(self):
        """``wt.exe`` and ``taskmgr.exe`` are absent from that denylist, so the
        table is the only thing that asks before they run."""
        from grandpa.apps.safety import BLOCKED_EXECUTABLE_NAMES

        for executable in ("wt.exe", "taskmgr.exe"):
            assert executable not in BLOCKED_EXECUTABLE_NAMES
            assert pc_control._launch_needs_approval(_request(executable)) is True


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_no_action_type_moved_between_tiers(self):
        assert "open_app" in pc_control.LOW_RISK_ACTIONS
        assert "open_app" not in pc_control.MEDIUM_RISK_ACTIONS
        assert "open_app" not in pc_control.HIGH_RISK_ACTIONS
        assert "open_app" not in pc_control.BLOCKED_ACTIONS

    def test_the_approval_required_action_set_is_unchanged(self):
        assert pc_control.APPROVAL_REQUIRED_ACTIONS == frozenset(
            {
                "browser_download",
                "browser_form_fill",
                "keyboard_hotkey",
                "keyboard_type",
                "mouse_click",
                "mouse_drag",
            }
        ) or set(pc_control.APPROVAL_REQUIRED_ACTIONS) == {
            "browser_download",
            "browser_form_fill",
            "keyboard_hotkey",
            "keyboard_type",
            "mouse_click",
            "mouse_drag",
        }

    def test_the_origin_vocabulary_is_unchanged(self):
        assert pc_control.ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )

    def test_the_sensitive_table_only_raises_never_lowers(self):
        """A sensitive entry must never make something less restricted."""
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "BLOCKED": 3}
        for target, risk in SENSITIVE:
            assert order[risk] > order["LOW"], f"{target} is not a raise"

    def test_the_table_resolves_through_the_launchers_own_aliases(self):
        """Not a separate name list: the same table the launcher resolves with."""
        from grandpa.desktop.control.applications import SAFE_APP_ALIASES

        assert SAFE_APP_ALIASES["windows terminal"] == "terminal"
        assert pc_control.classify_risk(_request("windows terminal")) == "MEDIUM"
