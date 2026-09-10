"""Post-execution verification: did the action actually take effect?

Before this existed, ``run_local_action`` reported success when the actuator
call returned without raising. For a voice user with no screen in front of them
that is the difference between an assistant and a slot machine -- "Volume set
to 50%" was said whether or not anything moved.

Verification runs immediately after ``_execute`` and before ``_audit``, inside
``run_local_action``. It reads real state back through the same APIs the
actuators use, records the outcome in ``LocalActionResponse.evidence``, and is
deliberately conservative: an action it cannot check reads ``unknown`` rather
than being reported as verified.

All state readers are patched here, so no test reads a real volume level,
clipboard, window, or display.
"""

from __future__ import annotations

from typing import Any

import pytest

from grandpa import pc_control
from grandpa.desktop.control import verification as verify_mod
from grandpa.desktop.control.verification import VerificationOutcome, verify_action
from grandpa.pc_control import LocalActionRequest, LocalActionResponse


def _ok(action_type: str, target: str = "", evidence: dict[str, Any] | None = None):
    return LocalActionResponse(
        ok=True,
        action_id=None,
        status="completed",
        message="done",
        approval_required=False,
        risk_level="LOW",
        evidence=dict(evidence or {}),
    )


def _req(action_type: str, target: str = "", **args: Any) -> LocalActionRequest:
    return LocalActionRequest(action_type=action_type, target=target, args=dict(args))


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


class TestVerificationContract:
    def test_outcome_serialises_for_evidence(self):
        outcome = VerificationOutcome("verified", "matched", expected=50, observed=50)
        data = outcome.to_dict()

        assert data["status"] == "verified"
        assert data["expected"] == 50
        assert data["observed"] == 50

    def test_unverifiable_action_reports_unknown_not_verified(self):
        """The whole point: never claim verification that did not happen."""
        outcome = verify_action(_req("mouse_move", "100,200"), _ok("mouse_move"))

        assert outcome.status == "unknown"

    def test_relative_volume_is_unknown_without_a_pre_reading(self, monkeypatch):
        """volume_up/down are relative; post-state alone cannot confirm them."""
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: 42)

        assert verify_action(_req("volume_up"), _ok("volume_up")).status == "unknown"
        assert (
            verify_action(_req("volume_down"), _ok("volume_down")).status == "unknown"
        )

    def test_window_state_actions_are_verifiable(self):
        """Window show-state gained read-back via IsZoomed / IsIconic."""
        from grandpa.desktop.control.verification import verifiable_actions

        assert {
            "maximize_window",
            "minimize_window",
            "restore_window",
        } <= set(verifiable_actions())


def _window_state(*, maximized, minimized, title="Notepad"):
    return {
        "handle": 1234,
        "title": title,
        "maximized": maximized,
        "minimized": minimized,
    }


class TestWindowShowStateVerification:
    """maximize -> IsZoomed, minimize -> IsIconic, restore -> neither."""

    @pytest.mark.parametrize(
        ("action", "maximized", "minimized", "expected"),
        [
            ("maximize_window", True, False, "verified"),
            ("maximize_window", False, False, "failed"),
            ("maximize_window", False, True, "failed"),
            ("minimize_window", False, True, "verified"),
            ("minimize_window", False, False, "failed"),
            ("minimize_window", True, False, "failed"),
            ("restore_window", False, False, "verified"),
            ("restore_window", True, False, "failed"),
            ("restore_window", False, True, "failed"),
        ],
    )
    def test_show_state_is_read_back(
        self, monkeypatch, action, maximized, minimized, expected
    ):
        monkeypatch.setattr(
            verify_mod,
            "read_window_show_state",
            lambda target: _window_state(maximized=maximized, minimized=minimized),
        )

        outcome = verify_action(_req(action, "active"), _ok(action))

        assert outcome.status == expected

    def test_disappeared_window_is_unknown_not_failed(self, monkeypatch):
        """A window closed between acting and checking is not a failed action."""
        monkeypatch.setattr(verify_mod, "read_window_show_state", lambda target: None)

        outcome = verify_action(
            _req("maximize_window", "notepad"), _ok("maximize_window")
        )

        assert outcome.status == "unknown"

    def test_unreadable_show_state_is_unknown(self, monkeypatch):
        """IsZoomed/IsIconic returning None means unchecked, not failed."""
        monkeypatch.setattr(
            verify_mod,
            "read_window_show_state",
            lambda target: _window_state(maximized=None, minimized=None),
        )

        outcome = verify_action(
            _req("minimize_window", "active"), _ok("minimize_window")
        )

        assert outcome.status == "unknown"

    def test_reader_exception_is_unknown(self, monkeypatch):
        def boom(target):
            raise OSError("win32 gone")

        monkeypatch.setattr(verify_mod, "read_window_show_state", boom)

        outcome = verify_action(_req("restore_window", "active"), _ok("restore_window"))

        assert outcome.status == "unknown"

    def test_failed_window_verification_downgrades_the_response(self, monkeypatch):
        monkeypatch.setattr(
            verify_mod,
            "read_window_show_state",
            lambda target: _window_state(maximized=False, minimized=False),
        )
        monkeypatch.setattr(
            pc_control, "_execute", lambda request, risk: _ok("maximize_window")
        )

        response = pc_control.run_local_action(
            {"action_type": "maximize_window", "target": "active"}
        )

        assert response.ok is False
        assert response.error == "verification_failed"
        assert response.evidence["verification"]["observed"] == "restored"


class TestWindowStateReaderComposition:
    """``read_window_state`` must report what the Win32 readers actually say.

    The tests above patch ``read_window_show_state``, so they never exercise
    ``_is_window_maximized`` / ``_is_window_minimized``. A mutation that forced
    both to return True passed the whole suite -- these close that hole by
    patching at the Win32 reader level instead.
    """

    @pytest.mark.parametrize(
        ("maximized", "minimized"),
        [(True, False), (False, True), (False, False)],
    )
    def test_state_is_taken_from_the_win32_readers(
        self, monkeypatch, maximized, minimized
    ):
        from grandpa import windows_window_control as wwc

        monkeypatch.setattr(
            wwc, "_resolve_window", lambda target: wwc.WindowInfo(99, "Notepad")
        )
        monkeypatch.setattr(wwc, "_is_window_maximized", lambda hwnd: maximized)
        monkeypatch.setattr(wwc, "_is_window_minimized", lambda hwnd: minimized)

        state = wwc.read_window_state("notepad")

        assert state["maximized"] is maximized
        assert state["minimized"] is minimized
        assert state["handle"] == 99

    def test_unresolvable_window_returns_none(self, monkeypatch):
        from grandpa import windows_window_control as wwc

        monkeypatch.setattr(wwc, "_resolve_window", lambda target: None)

        assert wwc.read_window_state("ghost") is None

    def test_unreadable_win32_state_returns_none(self, monkeypatch):
        from grandpa import windows_window_control as wwc

        monkeypatch.setattr(
            wwc, "_resolve_window", lambda target: wwc.WindowInfo(99, "Notepad")
        )
        monkeypatch.setattr(wwc, "_is_window_maximized", lambda hwnd: None)
        monkeypatch.setattr(wwc, "_is_window_minimized", lambda hwnd: None)

        assert wwc.read_window_state("notepad") is None

    def test_zero_handle_reads_as_unknown(self):
        from grandpa import windows_window_control as wwc

        assert wwc._is_window_maximized(0) is None
        assert wwc._is_window_minimized(0) is None

    def test_end_to_end_verification_uses_the_win32_readers(self, monkeypatch):
        """A maximize that did not take effect must be caught through the
        real reader chain, not just through a patched summary function."""
        from grandpa import windows_window_control as wwc

        monkeypatch.setattr(
            wwc, "_resolve_window", lambda target: wwc.WindowInfo(99, "Notepad")
        )
        monkeypatch.setattr(wwc, "_is_window_maximized", lambda hwnd: False)
        monkeypatch.setattr(wwc, "_is_window_minimized", lambda hwnd: False)

        outcome = verify_action(
            _req("maximize_window", "notepad"), _ok("maximize_window")
        )

        assert outcome.status == "failed"
        assert outcome.observed == "restored"


class TestWindowInfoStateFields:
    """The new fields must not disturb existing construction sites."""

    def test_window_info_defaults_are_backward_compatible(self):
        from grandpa.windows_window_control import WindowInfo

        info = WindowInfo(1, "Untitled")

        assert info.maximized is None
        assert info.minimized is None
        assert info.restored is None

    @pytest.mark.parametrize(
        ("maximized", "minimized", "restored"),
        [(True, False, False), (False, True, False), (False, False, True)],
    )
    def test_restored_is_derived(self, maximized, minimized, restored):
        from grandpa.windows_window_control import WindowInfo

        info = WindowInfo(1, "t", maximized=maximized, minimized=minimized)

        assert info.restored is restored


# ---------------------------------------------------------------------------
# Verifiable actions
# ---------------------------------------------------------------------------


class TestVolumeVerification:
    def test_volume_set_verified_when_level_matches(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: 50)

        outcome = verify_action(_req("volume_set", "50", level=50), _ok("volume_set"))

        assert outcome.status == "verified"
        assert outcome.observed == 50

    def test_volume_set_failed_when_level_differs(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: 12)

        outcome = verify_action(_req("volume_set", "50", level=50), _ok("volume_set"))

        assert outcome.status == "failed"
        assert outcome.expected == 50
        assert outcome.observed == 12

    def test_volume_set_unknown_when_backend_absent(self, monkeypatch):
        """pycaw is optional; no reading means unknown, not failure."""
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: None)

        outcome = verify_action(_req("volume_set", "50", level=50), _ok("volume_set"))

        assert outcome.status == "unknown"

    @pytest.mark.parametrize(
        ("action", "muted", "expected"),
        [
            ("volume_mute", True, "verified"),
            ("volume_mute", False, "failed"),
            ("volume_unmute", False, "verified"),
            ("volume_unmute", True, "failed"),
        ],
    )
    def test_mute_state_is_read_back(self, monkeypatch, action, muted, expected):
        monkeypatch.setattr(verify_mod, "read_muted", lambda: muted)

        assert verify_action(_req(action), _ok(action)).status == expected

    def test_mute_unknown_without_backend(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_muted", lambda: None)

        assert (
            verify_action(_req("volume_mute"), _ok("volume_mute")).status == "unknown"
        )


class TestBrightnessVerification:
    def test_brightness_set_verified_within_tolerance(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_brightness_percent", lambda: 50)

        outcome = verify_action(
            _req("brightness_set", "50", level=50), _ok("brightness_set")
        )

        assert outcome.status == "verified"

    def test_brightness_set_failed_when_far_off(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_brightness_percent", lambda: 10)

        outcome = verify_action(
            _req("brightness_set", "50", level=50), _ok("brightness_set")
        )

        assert outcome.status == "failed"

    def test_brightness_unknown_without_backend(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_brightness_percent", lambda: None)

        outcome = verify_action(
            _req("brightness_set", "50", level=50), _ok("brightness_set")
        )

        assert outcome.status == "unknown"


class TestClipboardVerification:
    def test_clipboard_write_verified(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_clipboard_text", lambda: "hello")

        outcome = verify_action(
            _req("clipboard_write", "hello"), _ok("clipboard_write")
        )

        assert outcome.status == "verified"

    def test_clipboard_write_failed(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_clipboard_text", lambda: "something else")

        outcome = verify_action(
            _req("clipboard_write", "hello"), _ok("clipboard_write")
        )

        assert outcome.status == "failed"

    def test_clipboard_clear_verified_when_empty(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_clipboard_text", lambda: "")

        assert (
            verify_action(_req("clipboard_clear"), _ok("clipboard_clear")).status
            == "verified"
        )

    def test_clipboard_clear_failed_when_not_empty(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_clipboard_text", lambda: "still here")

        assert (
            verify_action(_req("clipboard_clear"), _ok("clipboard_clear")).status
            == "failed"
        )


class TestWindowFocusVerification:
    def test_focus_verified_when_foreground_matches(self, monkeypatch):
        monkeypatch.setattr(
            verify_mod, "read_foreground_title", lambda: "Notepad - Untitled"
        )

        outcome = verify_action(_req("focus_window", "notepad"), _ok("focus_window"))

        assert outcome.status == "verified"

    def test_focus_failed_when_a_different_window_is_foreground(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_foreground_title", lambda: "Calculator")

        outcome = verify_action(_req("focus_window", "notepad"), _ok("focus_window"))

        assert outcome.status == "failed"

    def test_focus_unknown_when_foreground_unreadable(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_foreground_title", lambda: None)

        outcome = verify_action(_req("focus_window", "notepad"), _ok("focus_window"))

        assert outcome.status == "unknown"


class TestAppOpenVerification:
    """A launch is confirmed or unchecked -- it is never called a failure.

    Corrected from the original slice, which returned ``failed`` when neither
    a launched pid nor a matching window was found. That reads "not running"
    as "did not start", but a real application needs a moment to draw its first
    window, so the check can simply be too early. The consequence was concrete:
    ``test_pc_control.py``'s vscode tests fake ``launch_app``, so no pid is
    recorded and the window search falls through to the real desktop -- a
    successful action was downgraded to ``ok=False`` depending on what happened
    to be running on the machine.

    Telling a user a launch failed when it did not is worse than telling them
    it was not checked, which is the rule the rest of this module follows.
    """

    def test_open_app_verified_when_running(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_app_is_running", lambda app: True)

        outcome = verify_action(_req("open_app", "notepad"), _ok("open_app"))

        assert outcome.status == "verified"

    def test_open_app_unknown_when_undetectable(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_app_is_running", lambda app: None)

        outcome = verify_action(_req("open_app", "notepad"), _ok("open_app"))

        assert outcome.status == "unknown"

    def test_a_launch_not_yet_visible_is_unknown_not_failed(self, monkeypatch):
        """The regression: no evidence yet must not read as evidence of failure."""
        monkeypatch.setattr(verify_mod, "read_app_is_running", lambda app: False)

        outcome = verify_action(_req("open_app", "notepad"), _ok("open_app"))

        assert outcome.status == "unknown"

    def test_reader_never_reports_false(self, monkeypatch):
        """No pid and no window is None -- the reader has no failure verdict."""
        import grandpa.windows_window_control as wwc

        monkeypatch.setattr(wwc, "get_launched_pids", lambda app: [])
        monkeypatch.setattr(wwc, "_matching_windows", lambda target: [])

        assert verify_mod.read_app_is_running("notepad") is None

    def test_a_recorded_pid_alone_confirms_the_launch(self, monkeypatch):
        import grandpa.windows_window_control as wwc

        monkeypatch.setattr(wwc, "get_launched_pids", lambda app: [4242])
        monkeypatch.setattr(wwc, "_matching_windows", lambda target: [])

        assert verify_mod.read_app_is_running("notepad") is True

    def test_a_matching_window_alone_confirms_the_launch(self, monkeypatch):
        import grandpa.windows_window_control as wwc

        monkeypatch.setattr(wwc, "get_launched_pids", lambda app: [])
        monkeypatch.setattr(wwc, "_matching_windows", lambda target: [object()])

        assert verify_mod.read_app_is_running("notepad") is True

    def test_a_successful_launch_is_not_downgraded_by_an_early_check(self, monkeypatch):
        """End to end: the shape that broke the vscode tests."""
        import grandpa.windows_window_control as wwc

        monkeypatch.setattr(wwc, "get_launched_pids", lambda app: [])
        monkeypatch.setattr(wwc, "_matching_windows", lambda target: [])
        monkeypatch.setattr(
            pc_control, "_execute", lambda request, risk: _ok("open_app")
        )

        response = pc_control.run_local_action(
            {"action_type": "open_app", "target": "vscode"}
        )

        assert response.ok is True
        assert response.error is None
        assert response.evidence["verification"]["status"] == "unknown"


# ---------------------------------------------------------------------------
# Integration with run_local_action
# ---------------------------------------------------------------------------


class TestVerificationInsideRunLocalAction:
    def test_evidence_carries_verification(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: 50)
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: _ok("volume_set"),
        )

        response = pc_control.run_local_action(
            {"action_type": "volume_set", "target": "50", "args": {"level": 50}}
        )

        assert response.evidence["verification"]["status"] == "verified"

    def test_verification_failure_is_not_reported_as_success(self, monkeypatch):
        """The behaviour this whole slice exists for."""
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: 3)
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: _ok("volume_set"),
        )

        response = pc_control.run_local_action(
            {"action_type": "volume_set", "target": "50", "args": {"level": 50}}
        )

        assert response.ok is False
        assert response.status == "failed"
        assert response.error == "verification_failed"
        assert response.evidence["verification"]["status"] == "failed"

    def test_unknown_verification_leaves_success_intact(self, monkeypatch):
        """An unverifiable action must not be downgraded to a failure."""
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: _ok("mouse_move"),
        )

        response = pc_control.run_local_action(
            {"action_type": "mouse_move", "target": "10,10"}
        )

        assert response.ok is True
        assert response.evidence["verification"]["status"] == "unknown"

    def test_dry_run_does_not_verify(self, monkeypatch):
        """A dry run performs no actuation, so there is nothing to read back."""
        called: list[str] = []
        monkeypatch.setattr(
            verify_mod,
            "read_volume_percent",
            lambda: called.append("read") or 50,
        )

        response = pc_control.run_local_action(
            {"action_type": "volume_set", "target": "50", "dry_run": True}
        )

        assert response.status == "dry_run"
        assert called == [], "dry run read real device state"
        assert "verification" not in response.evidence

    def test_blocked_action_is_not_verified(self):
        response = pc_control.run_local_action(
            {"action_type": "shell_run", "target": "whoami"}
        )

        assert response.status == "blocked"
        assert "verification" not in (response.evidence or {})

    def test_verification_cannot_change_risk_or_approval(self, monkeypatch):
        """Verification is observational; it must not touch policy."""
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: 3)
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: _ok("volume_set"),
        )

        response = pc_control.run_local_action(
            {"action_type": "volume_set", "target": "50", "args": {"level": 50}}
        )

        assert response.risk_level == "LOW"
        assert response.approval_required is False

    def test_a_failing_actuator_is_not_overwritten_by_verification(self, monkeypatch):
        """Verification only runs on a successful execute."""
        failed = LocalActionResponse(
            ok=False,
            action_id=None,
            status="failed",
            message="actuator said no",
            approval_required=False,
            risk_level="LOW",
        )
        monkeypatch.setattr(pc_control, "_execute", lambda request, risk: failed)

        response = pc_control.run_local_action(
            {"action_type": "volume_set", "target": "50"}
        )

        assert response.ok is False
        assert response.message == "actuator said no"

    def test_verification_reaches_the_audit_record(self, monkeypatch, tmp_path):
        import json

        log = tmp_path / "audit.log"
        monkeypatch.setattr(pc_control, "get_audit_log_path", lambda: log)
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: 50)
        monkeypatch.setattr(
            pc_control, "_execute", lambda request, risk: _ok("volume_set")
        )

        pc_control.run_local_action(
            {
                "action_type": "volume_set",
                "target": "50",
                "args": {"level": 50},
                "origin": "voice",
            }
        )

        record = json.loads(
            [line for line in log.read_text(encoding="utf-8").splitlines() if line][-1]
        )
        assert record["verification"] == "verified"
        assert record["origin"] == "voice"

    def test_a_reader_that_raises_yields_unknown_not_a_crash(self, monkeypatch):
        def boom():
            raise OSError("device gone")

        monkeypatch.setattr(verify_mod, "read_volume_percent", boom)
        monkeypatch.setattr(
            pc_control, "_execute", lambda request, risk: _ok("volume_set")
        )

        response = pc_control.run_local_action(
            {"action_type": "volume_set", "target": "50", "args": {"level": 50}}
        )

        assert response.ok is True
        assert response.evidence["verification"]["status"] == "unknown"
