"""What Grandpa says out loud must match what verification actually found.

``_apply_verification`` records whether an action was confirmed to have taken
effect, but that outcome lived only in ``LocalActionResponse.evidence`` -- the
user heard the same sentence whether the window moved or not. Someone operating
by voice has no screen to check against, so the reply is the only signal they
get.

These run the real production entry point, ``process_voice_operator_turn``,
with an injected actuator that returns a chosen verification outcome. Nothing
touches a real window, device, microphone, or TTS engine.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from grandpa import pc_control
from grandpa.voice.operator import (
    process_voice_operator_turn,
    spoken_text_for_verification,
)


class VerifyingActuator:
    """Returns a successful action carrying a chosen verification outcome."""

    def __init__(
        self,
        verification: dict[str, Any] | None,
        *,
        message: str = "Window maximized.",
        ok: bool = True,
        status: str = "completed",
    ) -> None:
        self.verification = verification
        self.message = message
        self.ok = ok
        self.status = status
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]):
        self.payloads.append(dict(payload))
        evidence: dict[str, Any] = {}
        if self.verification is not None:
            evidence["verification"] = self.verification
        return pc_control.LocalActionResponse(
            ok=self.ok,
            action_id=None,
            status=self.status,
            message=self.message,
            approval_required=False,
            risk_level="LOW",
            evidence=evidence,
        )


class RecordingAutomation:
    target_window = None

    def __init__(self) -> None:
        self.commands: list[str] = []

    def has_pending_confirmation(self) -> bool:
        return False

    def has_pending_window_choice(self) -> bool:
        return False

    def has_pending_dialog(self) -> bool:
        return False

    def handle(self, command: str, dry_run: bool = False):
        self.commands.append(command)
        return SimpleNamespace(
            status="handled",
            message=f"recorded: {command}",
            data={},
            confirmation_token=None,
        )


def _turn(text: str, actuator, *, dry_run: bool = False):
    return process_voice_operator_turn(
        text,
        dry_run=dry_run,
        action_runner=actuator,
        automation_service=RecordingAutomation(),
    )


# ---------------------------------------------------------------------------
# The three states
# ---------------------------------------------------------------------------


class TestVerifiedIsSpokenConcisely:
    @pytest.mark.parametrize(
        ("command", "message"),
        [
            ("maximize this window", "Window maximized."),
            ("turn up the volume", "Volume increased."),
            ("mute", "Muted."),
            ("open chrome", "Chrome is open."),
        ],
    )
    def test_confirmed_actions_keep_their_plain_message(self, command, message):
        actuator = VerifyingActuator(
            {"status": "verified", "detail": "window is maximized"}, message=message
        )

        response = _turn(command, actuator)

        assert response.spoken_text == message
        assert "could not confirm" not in response.spoken_text


class TestFailedDoesNotSoundLikeSuccess:
    def test_failed_verification_leads_with_the_failure(self):
        """The underlying message opens "Window maximized." -- in speech the
        opening words are what get heard, so a failure must not start there."""
        actuator = VerifyingActuator(
            {
                "status": "failed",
                "detail": "window is restored, expected maximized",
            },
            message="Window maximized. However, I could not confirm it took effect.",
        )

        response = _turn("maximize this window", actuator)

        assert not response.spoken_text.startswith("Window maximized")
        assert "did not take effect" in response.spoken_text
        assert "window is restored" in response.spoken_text

    @pytest.mark.parametrize(
        "command",
        ["maximize this window", "minimize this window", "restore this window", "mute"],
    )
    def test_failure_is_audible_for_every_window_and_volume_action(self, command):
        actuator = VerifyingActuator({"status": "failed", "detail": "no change"})

        response = _turn(command, actuator)

        assert "did not take effect" in response.spoken_text

    def test_failed_without_detail_still_says_it_failed(self):
        actuator = VerifyingActuator({"status": "failed"})

        response = _turn("mute", actuator)

        assert "did not take effect" in response.spoken_text


class TestUnknownIsDistinguishedFromBoth:
    def test_unknown_says_it_ran_but_was_not_confirmed(self):
        actuator = VerifyingActuator(
            {"status": "unknown", "detail": "volume could not be read back"},
            message="Volume increased",
        )

        response = _turn("turn up the volume", actuator)

        assert "Volume increased" in response.spoken_text
        assert "could not confirm" in response.spoken_text

    def test_unknown_is_not_phrased_as_a_failure(self):
        actuator = VerifyingActuator({"status": "unknown"}, message="Volume increased.")

        response = _turn("turn up the volume", actuator)

        assert "did not take effect" not in response.spoken_text

    def test_unknown_is_not_phrased_as_confirmed(self):
        actuator = VerifyingActuator({"status": "unknown"}, message="Volume increased.")

        response = _turn("turn up the volume", actuator)

        assert response.spoken_text != "Volume increased."


# ---------------------------------------------------------------------------
# Backward compatibility and robustness
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_response_without_verification_is_unchanged(self):
        """Actions with no verifier must keep their existing wording."""
        actuator = VerifyingActuator(None, message="Mouse moved.")

        response = _turn("open chrome", actuator)

        assert response.spoken_text == "Mouse moved."

    @pytest.mark.parametrize("verification", ["not a dict", 42, [], None])
    def test_malformed_verification_evidence_does_not_break_the_voice_path(
        self, verification
    ):
        actuator = VerifyingActuator(None, message="Chrome is open.")
        actuator.verification = verification

        response = _turn("open chrome", actuator)

        assert response.spoken_text == "Chrome is open."

    def test_unrecognised_verification_status_keeps_the_plain_message(self):
        actuator = VerifyingActuator({"status": "weird"}, message="Chrome is open.")

        response = _turn("open chrome", actuator)

        assert response.spoken_text == "Chrome is open."

    def test_missing_evidence_attribute_is_safe(self):
        def runner(payload):
            return SimpleNamespace(ok=True, status="completed", message="Done.")

        response = _turn("open chrome", runner)

        assert response.spoken_text == "Done."


class TestHelperDirectly:
    @pytest.mark.parametrize(
        ("status", "expected_fragment"),
        [
            ("verified", "Volume set to 50%."),
            ("failed", "did not take effect"),
            ("unknown", "could not confirm"),
        ],
    )
    def test_each_status_produces_its_own_phrasing(self, status, expected_fragment):
        response = SimpleNamespace(
            evidence={"verification": {"status": status, "detail": "d"}}
        )

        assert expected_fragment in spoken_text_for_verification(
            response, "Volume set to 50%."
        )

    def test_unknown_does_not_double_a_full_stop(self):
        response = SimpleNamespace(evidence={"verification": {"status": "unknown"}})

        spoken = spoken_text_for_verification(response, "Volume increased.")

        assert ".." not in spoken


# ---------------------------------------------------------------------------
# Nothing else about the voice path changed
# ---------------------------------------------------------------------------


class TestExistingBehaviourPreserved:
    def test_greeting_is_still_conversational(self):
        actuator = VerifyingActuator({"status": "verified"})

        response = _turn("hello", actuator)

        assert not actuator.payloads
        assert "did not take effect" not in response.spoken_text

    def test_shutdown_is_still_blocked(self):
        actuator = VerifyingActuator({"status": "verified"})

        response = _turn("shutdown", actuator)

        assert response.status == "blocked"
        assert not actuator.payloads

    def test_dry_run_carries_no_verification_and_is_not_hedged(self):
        """A dry run performs no actuation, so pc_control records no
        verification -- the reply must stay the plain dry-run message."""
        actuator = VerifyingActuator(
            None, message="Dry run: open_app would run on chrome with LOW risk."
        )

        response = _turn("open chrome", actuator, dry_run=True)

        assert response.spoken_text == actuator.message
        assert "could not confirm" not in response.spoken_text

    def test_approval_flag_still_propagates(self):
        actuator = VerifyingActuator({"status": "verified"})
        actuator.ok = False
        actuator.status = "approval_required"

        def runner(payload):
            actuator.payloads.append(dict(payload))
            return pc_control.LocalActionResponse(
                ok=False,
                action_id="abc",
                status="approval_required",
                message="I need your approval before I do that.",
                approval_required=True,
                risk_level="MEDIUM",
                evidence={},
            )

        response = _turn("maximize this window", runner)

        assert response.requires_confirmation is True
        assert "approval" in response.spoken_text.lower()

    def test_origin_is_still_voice(self):
        actuator = VerifyingActuator({"status": "verified"})

        _turn("maximize this window", actuator)

        assert actuator.payloads[0]["origin"] == "voice"

    def test_verification_does_not_change_risk_or_status_fields(self):
        actuator = VerifyingActuator({"status": "unknown"}, message="Done.")

        response = _turn("maximize this window", actuator)

        # The action still succeeded; only the wording is hedged.
        assert response.status == "handled"
