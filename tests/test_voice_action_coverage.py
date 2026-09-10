"""Natural-language coverage for the voice control layer.

These run the real production entry point, ``process_voice_operator_turn``
(voice/operator.py:952), with a recording actuator injected in place of
``run_local_action``. Nothing launches an app, presses a key, or moves a
window, and no microphone, TTS engine, model, or network is involved.

The property under test is narrow and deliberate: a phrasing a person would
plausibly say must resolve to an action type that **already exists** in
``pc_control``. No test here asks for an action type the actuator layer does not
implement -- ``screenshot`` in particular is absent from pc_control, so no test
pretends it works.
"""

from __future__ import annotations

from typing import Any

import pytest

from grandpa import pc_control
from grandpa.pc_control import _coerce_request
from grandpa.voice.operator import process_voice_operator_turn


class RecordingActuator:
    """Stands in for ``run_local_action`` and records the coerced request."""

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def __call__(self, payload: dict[str, Any]):
        request = _coerce_request(payload)
        self.requests.append(request)
        return pc_control.LocalActionResponse(
            ok=True,
            action_id=None,
            status="dry_run",
            message=f"would run {request.action_type}",
            approval_required=False,
            risk_level="LOW",
            evidence={"would_execute": True},
        )

    @property
    def action_types(self) -> list[str]:
        return [request.action_type for request in self.requests]


class RecordingAutomation:
    """Stands in for ScreenAutomationService; records the command handed to it."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    def has_pending_confirmation(self) -> bool:
        return False

    def has_pending_window_choice(self) -> bool:
        return False

    def has_pending_dialog(self) -> bool:
        return False

    #: The executive planner's recovery path reads this when a step fails
    #: (planner/recovery.py:42), so the double has to carry it.
    target_window = None

    def handle(self, command: str, dry_run: bool = False):
        from types import SimpleNamespace

        self.commands.append(command)
        return SimpleNamespace(
            status="handled",
            message=f"recorded: {command}",
            data={},
            confirmation_token=None,
        )


def _turn(text: str):
    actuator = RecordingActuator()
    automation = RecordingAutomation()
    response = process_voice_operator_turn(
        text,
        dry_run=True,
        action_runner=actuator,
        automation_service=automation,
    )
    return response, actuator, automation


def _resolved_action(text: str) -> str:
    """Return the action type a phrase reaches, from either actuator path."""
    _response, actuator, automation = _turn(text)
    if actuator.action_types:
        return actuator.action_types[0]
    if automation.commands:
        return f"automation:{automation.commands[0]}"
    return ""


# ---------------------------------------------------------------------------
# Natural-language coverage of existing actions
# ---------------------------------------------------------------------------


class TestVolumeCoverage:
    @pytest.mark.parametrize(
        "phrase",
        ["volume up", "turn up the volume", "make it louder", "increase volume"],
    )
    def test_volume_up_phrasings(self, phrase):
        assert _resolved_action(phrase) == "volume_up"

    @pytest.mark.parametrize(
        "phrase",
        ["volume down", "turn down the volume", "make it quieter", "decrease volume"],
    )
    def test_volume_down_phrasings(self, phrase):
        assert _resolved_action(phrase) == "volume_down"

    @pytest.mark.parametrize(
        "phrase", ["mute", "mute the computer", "turn off the sound"]
    )
    def test_mute_phrasings(self, phrase):
        assert _resolved_action(phrase) == "volume_mute"

    @pytest.mark.parametrize("phrase", ["unmute", "turn the sound back on"])
    def test_unmute_phrasings(self, phrase):
        assert _resolved_action(phrase) == "volume_unmute"

    @pytest.mark.parametrize(
        "phrase", ["set volume to 50", "set the volume to 50 percent"]
    )
    def test_set_volume_phrasings(self, phrase):
        _response, actuator, _automation = _turn(phrase)
        assert actuator.action_types == ["volume_set"]
        assert actuator.requests[0].target == "50"


class TestBrightnessCoverage:
    """brightness_get/brightness_set exist in pc_control but had no voice path.

    Only absolute brightness is covered. ``execute_brightness``
    (desktop/control/power.py:113) reads an absolute level from
    ``args["level"]`` or the target and clamps it to 0-100; there is no
    brightness_up/brightness_down action and no read-modify-write step. So
    "make the screen brighter" and "dim the screen" have no actuator to reach,
    and are deliberately left unsupported rather than mapped to an invented
    step size. Relative brightness needs a new action type, which is a separate
    decision.
    """

    @pytest.mark.parametrize(
        "phrase",
        ["set brightness to 50", "set the brightness to 50 percent"],
    )
    def test_set_brightness_phrasings(self, phrase):
        _response, actuator, _automation = _turn(phrase)
        assert actuator.action_types == ["brightness_set"]
        assert actuator.requests[0].target == "50"

    def test_brightness_query(self):
        assert _resolved_action("what is the brightness") == "brightness_get"

    @pytest.mark.parametrize(
        "phrase", ["make the screen brighter", "dim the screen", "increase brightness"]
    )
    def test_relative_brightness_is_not_silently_invented(self, phrase):
        """No actuator supports this, so it must not resolve to a made-up level."""
        _response, actuator, _automation = _turn(phrase)

        assert not actuator.requests, (
            f"{phrase!r} resolved to an action with an invented brightness level"
        )


class TestClipboardCoverage:
    """clipboard_read/write/clear exist in pc_control but had no voice path."""

    @pytest.mark.parametrize(
        "phrase", ["read the clipboard", "what is on the clipboard"]
    )
    def test_clipboard_read(self, phrase):
        assert _resolved_action(phrase) == "clipboard_read"

    def test_clipboard_clear(self):
        assert _resolved_action("clear the clipboard") == "clipboard_clear"


class TestWindowCoverage:
    @pytest.mark.parametrize(
        "phrase", ["maximize this window", "make this window full screen"]
    )
    def test_maximize_phrasings(self, phrase):
        assert _resolved_action(phrase) == "maximize_window"

    def test_minimize(self):
        assert _resolved_action("minimize this window") == "minimize_window"

    def test_restore(self):
        assert _resolved_action("restore this window") == "restore_window"


class TestKeyboardCoverage:
    @pytest.mark.parametrize("phrase", ["type hello world", "write hello world"])
    def test_type_phrasings_reach_keyboard_type(self, phrase):
        resolved = _resolved_action(phrase)
        assert resolved in {"keyboard_type", "automation:type hello world"}

    @pytest.mark.parametrize("phrase", ["press enter", "press ctrl c"])
    def test_press_phrasings(self, phrase):
        resolved = _resolved_action(phrase)
        assert resolved.startswith("automation:press") or resolved == "keyboard_hotkey"


class TestAppAndFolderCoverage:
    @pytest.mark.parametrize(
        "phrase", ["open chrome", "launch chrome", "start chrome", "open google chrome"]
    )
    def test_open_app_phrasings(self, phrase):
        _response, actuator, _automation = _turn(phrase)
        assert actuator.action_types == ["open_app"]
        assert actuator.requests[0].target == "chrome"

    @pytest.mark.parametrize("phrase", ["open Downloads", "open my Downloads folder"])
    def test_open_folder_phrasings(self, phrase):
        assert _resolved_action(phrase) == "open_folder"

    def test_lock(self):
        assert _resolved_action("lock the pc") == "system_lock"


class TestUrlCoverage:
    """A URL must open a browser, not be treated as an application name."""

    @pytest.mark.parametrize(
        "phrase", ["open google.com", "go to google.com", "open https://google.com"]
    )
    def test_url_reaches_browser_open(self, phrase):
        _response, actuator, _automation = _turn(phrase)
        assert actuator.action_types == ["browser_open"]
        assert "google.com" in actuator.requests[0].target


# ---------------------------------------------------------------------------
# Origin, safety and conversation
# ---------------------------------------------------------------------------


class TestVoiceOriginIsTagged:
    @pytest.mark.parametrize(
        "phrase", ["open chrome", "volume up", "maximize this window", "lock the pc"]
    )
    def test_voice_actions_are_tagged_voice(self, phrase):
        _response, actuator, _automation = _turn(phrase)

        assert actuator.requests, f"{phrase!r} reached no actuator"
        assert actuator.requests[0].origin == "voice"

    @pytest.mark.parametrize("phrase", ["type hello world", "press enter"])
    def test_screen_automation_actions_are_also_tagged_voice(self, phrase):
        """Keyboard and mouse go through the automation executor, not the
        operator's own payload, so they need their own origin coverage --
        they are the actions most worth attributing in an audit.

        Corrected: this used to build the executor with no origin at all and
        still assert "voice". That passed only because ``AutomationExecutor``
        hardcoded ``payload.get("origin", "voice")``, so the test was pinning
        the defect rather than the behaviour -- a chat- or CLI-driven keypress
        was recorded as spoken too. The service is now built the way the voice
        path builds it, stating the origin, and
        ``test_a_default_service_is_not_voice`` below pins the other half.
        """
        from grandpa.automation.executor import AutomationExecutor
        from grandpa.automation.service import ScreenAutomationService

        seen: list[tuple[str, str]] = []

        def runner(payload):
            request = _coerce_request(payload)
            seen.append((request.action_type, request.origin))
            return pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="dry_run",
                message="ok",
                approval_required=False,
                risk_level="MEDIUM",
            )

        service = ScreenAutomationService(
            executor=AutomationExecutor(runner=runner, origin="voice")
        )
        service.handle(phrase, dry_run=True)

        assert seen, f"{phrase!r} reached no actuator"
        assert all(origin == "voice" for _action, origin in seen)

    @pytest.mark.parametrize("phrase", ["type hello world", "press enter"])
    def test_a_default_service_is_not_voice(self, phrase):
        """Provenance is stated, never assumed.

        A keypress issued from chat or the CLI must not be filed as spoken.
        """
        from grandpa.automation.executor import AutomationExecutor
        from grandpa.automation.service import ScreenAutomationService

        seen: list[str] = []

        def runner(payload):
            seen.append(_coerce_request(payload).origin)
            return pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="dry_run",
                message="ok",
                approval_required=False,
                risk_level="MEDIUM",
            )

        service = ScreenAutomationService(executor=AutomationExecutor(runner=runner))
        service.handle(phrase, dry_run=True)

        assert seen, f"{phrase!r} reached no actuator"
        assert seen == ["direct"] * len(seen)


class TestSafetyPreserved:
    @pytest.mark.parametrize("phrase", ["shutdown", "restart"])
    def test_dangerous_phrases_stay_blocked(self, phrase):
        response, actuator, automation = _turn(phrase)

        assert response.status == "blocked"
        assert not actuator.requests, "a blocked phrase reached the actuator"
        assert not automation.commands

    @pytest.mark.parametrize(
        "phrase", ["run powershell", "open cmd", "delete all my files"]
    )
    def test_shell_and_destructive_phrases_stay_blocked(self, phrase):
        response, actuator, _automation = _turn(phrase)

        assert response.status == "blocked"
        assert not actuator.requests

    def test_blocked_action_is_refused_at_the_boundary(self):
        """Even if a phrase resolved to it, policy refuses BLOCKED actions."""
        response = pc_control.run_local_action(
            {"action_type": "shell_run", "target": "whoami", "origin": "voice"}
        )

        assert response.ok is False
        assert response.status == "blocked"


class TestConversationalPreserved:
    @pytest.mark.parametrize("phrase", ["hello", "hi", "good morning"])
    def test_greetings_stay_conversational(self, phrase):
        _response, actuator, automation = _turn(phrase)

        assert not actuator.requests, f"{phrase!r} was treated as a device command"
        assert not automation.commands

    def test_greeting_words_inside_a_command_do_not_hijack_it(self):
        """The earlier P0 fix must survive this slice."""
        _response, actuator, automation = _turn("type hello world")

        assert actuator.requests or automation.commands


class TestMultiStepPreserved:
    def test_multistep_goal_is_not_mis_parsed_as_one_action(self):
        """The planner claims genuine multi-step goals before the device parser.

        The failure this guards against is the whole sentence being swallowed
        as a single app name -- ``open_app`` with target
        "chrome and search for fastapi" -- which reports success and then fails
        to resolve any such application.
        """
        _response, actuator, _automation = _turn("open chrome and search for fastapi")

        targets = [request.target for request in actuator.requests]
        assert "chrome and search for fastapi" not in targets

    @pytest.mark.parametrize(
        "phrase", ["open chrome", "volume up", "maximize this window"]
    )
    def test_single_step_commands_are_not_treated_as_multistep(self, phrase):
        _response, actuator, _automation = _turn(phrase)

        assert len(actuator.requests) == 1
