"""Verifying relative volume changes without reading the device every time.

``volume_up`` and ``volume_down`` are relative: the post-execute reading alone
says nothing, because 47% is neither right nor wrong without knowing what it
was before. They were therefore the only common voice commands stuck on
``unknown``, and after the previous slice made verification audible, every
"turn up the volume" ended with "I could not confirm it took effect".

Confirming them needs a reading from *before* the action. The cost worth
avoiding is doing that for all ~70 action types, so the pre-read is scoped to
exactly the actions that declare a relative verifier -- asserted here, because
that scoping is the whole point of the design.

All readers are patched; no test touches real audio hardware, and pycaw is not
required.
"""

from __future__ import annotations

from typing import Any

import pytest

from grandpa import pc_control
from grandpa.desktop.control import verification as verify_mod
from grandpa.desktop.control.verification import (
    PRE_READ_ACTIONS,
    capture_pre_state,
    verify_action,
)
from grandpa.pc_control import LocalActionRequest, LocalActionResponse


def _req(action_type: str, target: str = "", **args: Any) -> LocalActionRequest:
    return LocalActionRequest(action_type=action_type, target=target, args=dict(args))


def _ok(message: str = "Volume increased.") -> LocalActionResponse:
    return LocalActionResponse(
        ok=True,
        action_id=None,
        status="completed",
        message=message,
        approval_required=False,
        risk_level="LOW",
        evidence={},
    )


class VolumeReader:
    """Returns a scripted sequence of volume readings and counts the calls."""

    def __init__(self, *readings: int | None) -> None:
        self.readings = list(readings)
        self.calls = 0

    def __call__(self) -> int | None:
        self.calls += 1
        if not self.readings:
            return None
        value = self.readings[0]
        if len(self.readings) > 1:
            self.readings.pop(0)
        return value


# ---------------------------------------------------------------------------
# Pre-read scoping -- the reason this design exists
# ---------------------------------------------------------------------------


class TestPreReadIsNarrowlyScoped:
    def test_only_relative_volume_declares_a_pre_read(self):
        assert PRE_READ_ACTIONS == frozenset({"volume_up", "volume_down"})

    @pytest.mark.parametrize("action", ["volume_up", "volume_down"])
    def test_pre_read_captures_the_current_volume(self, monkeypatch, action):
        reader = VolumeReader(40)
        monkeypatch.setattr(verify_mod, "read_volume_percent", reader)

        state = capture_pre_state(_req(action))

        assert state == {"volume": 40}
        assert reader.calls == 1

    @pytest.mark.parametrize(
        "action",
        [
            "open_app",
            "volume_set",
            "volume_mute",
            "maximize_window",
            "keyboard_type",
            "mouse_move",
            "clipboard_write",
            "file_copy",
        ],
    )
    def test_unrelated_actions_perform_no_volume_read(self, monkeypatch, action):
        reader = VolumeReader(40)
        monkeypatch.setattr(verify_mod, "read_volume_percent", reader)

        state = capture_pre_state(_req(action))

        assert state is None
        assert reader.calls == 0, f"{action} read the volume device unnecessarily"

    def test_unreadable_device_yields_no_pre_state(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: None)

        assert capture_pre_state(_req("volume_up")) is None

    def test_a_raising_reader_does_not_propagate(self, monkeypatch):
        def boom():
            raise OSError("audio device gone")

        monkeypatch.setattr(verify_mod, "read_volume_percent", boom)

        assert capture_pre_state(_req("volume_up")) is None


# ---------------------------------------------------------------------------
# Direction semantics
# ---------------------------------------------------------------------------


class TestRelativeVolumeDirection:
    @pytest.mark.parametrize(
        ("action", "before", "after", "expected"),
        [
            # Correct direction.
            ("volume_up", 40, 42, "verified"),
            ("volume_up", 40, 60, "verified"),
            ("volume_down", 40, 38, "verified"),
            ("volume_down", 40, 10, "verified"),
            # Unchanged.
            ("volume_up", 40, 40, "failed"),
            ("volume_down", 40, 40, "failed"),
            # Wrong direction.
            ("volume_up", 40, 30, "failed"),
            ("volume_down", 40, 50, "failed"),
        ],
    )
    def test_direction_decides_the_outcome(
        self, monkeypatch, action, before, after, expected
    ):
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: after)

        outcome = verify_action(_req(action), _ok(), pre_state={"volume": before})

        assert outcome.status == expected
        assert outcome.expected is not None
        assert outcome.observed == after

    @pytest.mark.parametrize("action", ["volume_up", "volume_down"])
    def test_rounding_noise_counts_as_unchanged(self, monkeypatch, action):
        """A 1% wobble is device rounding, not a real step."""
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: 41)

        outcome = verify_action(_req(action), _ok(), pre_state={"volume": 40})

        assert outcome.status == "failed"

    def test_missing_pre_state_is_unknown_not_failed(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: 50)

        outcome = verify_action(_req("volume_up"), _ok(), pre_state=None)

        assert outcome.status == "unknown"

    def test_unreadable_post_state_is_unknown(self, monkeypatch):
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: None)

        outcome = verify_action(_req("volume_up"), _ok(), pre_state={"volume": 40})

        assert outcome.status == "unknown"

    def test_verify_action_without_pre_state_argument_still_works(self, monkeypatch):
        """Backward compatible: existing callers pass two arguments."""
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: 50)

        assert verify_action(_req("volume_up"), _ok()).status == "unknown"


# ---------------------------------------------------------------------------
# Integration through run_local_action
# ---------------------------------------------------------------------------


class TestThroughRunLocalAction:
    def _patch_execute(self, monkeypatch, message="Volume increased."):
        monkeypatch.setattr(pc_control, "_execute", lambda request, risk: _ok(message))

    def test_increase_is_verified_end_to_end(self, monkeypatch):
        self._patch_execute(monkeypatch)
        monkeypatch.setattr(verify_mod, "read_volume_percent", VolumeReader(40, 46))

        response = pc_control.run_local_action({"action_type": "volume_up"})

        assert response.ok is True
        verification = response.evidence["verification"]
        assert verification["status"] == "verified"
        assert verification["observed"] == 46

    def test_decrease_is_verified_end_to_end(self, monkeypatch):
        self._patch_execute(monkeypatch, "Volume decreased.")
        monkeypatch.setattr(verify_mod, "read_volume_percent", VolumeReader(40, 34))

        response = pc_control.run_local_action({"action_type": "volume_down"})

        assert response.evidence["verification"]["status"] == "verified"

    def test_unchanged_volume_is_not_reported_as_success(self, monkeypatch):
        self._patch_execute(monkeypatch)
        monkeypatch.setattr(verify_mod, "read_volume_percent", VolumeReader(40, 40))

        response = pc_control.run_local_action({"action_type": "volume_up"})

        assert response.ok is False
        assert response.status == "failed"
        assert response.error == "verification_failed"

    def test_unknown_does_not_downgrade(self, monkeypatch):
        self._patch_execute(monkeypatch)
        monkeypatch.setattr(verify_mod, "read_volume_percent", lambda: None)

        response = pc_control.run_local_action({"action_type": "volume_up"})

        assert response.ok is True
        assert response.evidence["verification"]["status"] == "unknown"

    def test_dry_run_performs_zero_volume_reads(self, monkeypatch):
        reader = VolumeReader(40)
        monkeypatch.setattr(verify_mod, "read_volume_percent", reader)

        response = pc_control.run_local_action(
            {"action_type": "volume_up", "dry_run": True}
        )

        assert response.status == "dry_run"
        assert reader.calls == 0, "dry run touched the volume device"
        assert "verification" not in response.evidence

    def test_unrelated_action_reads_no_volume_through_the_real_path(self, monkeypatch):
        reader = VolumeReader(40)
        monkeypatch.setattr(verify_mod, "read_volume_percent", reader)
        monkeypatch.setattr(
            pc_control, "_execute", lambda request, risk: _ok("Mouse moved.")
        )

        pc_control.run_local_action({"action_type": "mouse_move", "target": "1,1"})

        assert reader.calls == 0

    def test_blocked_action_reads_no_volume(self, monkeypatch):
        reader = VolumeReader(40)
        monkeypatch.setattr(verify_mod, "read_volume_percent", reader)

        response = pc_control.run_local_action({"action_type": "shell_run"})

        assert response.status == "blocked"
        assert reader.calls == 0

    def test_risk_and_approval_are_untouched(self, monkeypatch):
        self._patch_execute(monkeypatch)
        monkeypatch.setattr(verify_mod, "read_volume_percent", VolumeReader(40, 40))

        response = pc_control.run_local_action({"action_type": "volume_up"})

        assert response.risk_level == "LOW"
        assert response.approval_required is False

    def test_origin_and_audit_still_carry_through(self, monkeypatch, tmp_path):
        import json

        log = tmp_path / "audit.log"
        monkeypatch.setattr(pc_control, "get_audit_log_path", lambda: log)
        self._patch_execute(monkeypatch)
        monkeypatch.setattr(verify_mod, "read_volume_percent", VolumeReader(40, 46))

        pc_control.run_local_action({"action_type": "volume_up", "origin": "voice"})

        record = json.loads(
            [line for line in log.read_text(encoding="utf-8").splitlines() if line][-1]
        )
        assert record["origin"] == "voice"
        assert record["verification"] == "verified"


# ---------------------------------------------------------------------------
# The voice surface
# ---------------------------------------------------------------------------


class TestVoiceSurface:
    def _turn(self, text, monkeypatch, before, after):
        from types import SimpleNamespace

        from grandpa.voice.operator import process_voice_operator_turn

        monkeypatch.setattr(
            pc_control, "_execute", lambda request, risk: _ok("Volume changed.")
        )
        monkeypatch.setattr(
            verify_mod, "read_volume_percent", VolumeReader(before, after)
        )
        seen: list[str] = []

        def runner(payload):
            seen.append(payload["action_type"])
            return pc_control.run_local_action(payload)

        class Auto:
            target_window = None

            def has_pending_confirmation(self):
                return False

            def has_pending_window_choice(self):
                return False

            def has_pending_dialog(self):
                return False

            def handle(self, command, dry_run=False):
                return SimpleNamespace(
                    status="handled", message="", data={}, confirmation_token=None
                )

        response = process_voice_operator_turn(
            text, action_runner=runner, automation_service=Auto()
        )
        return response, seen

    def test_turn_up_the_volume_reaches_volume_up_and_is_confirmed(self, monkeypatch):
        response, seen = self._turn("turn up the volume", monkeypatch, 40, 46)

        assert seen == ["volume_up"]
        assert "could not confirm" not in response.spoken_text

    def test_turn_down_the_volume_reaches_volume_down(self, monkeypatch):
        _response, seen = self._turn("turn down the volume", monkeypatch, 40, 34)

        assert seen == ["volume_down"]

    def test_a_volume_change_that_did_not_happen_is_audible(self, monkeypatch):
        response, _seen = self._turn("turn up the volume", monkeypatch, 40, 40)

        assert "did not take effect" in response.spoken_text
