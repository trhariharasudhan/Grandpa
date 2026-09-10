"""Multi-step spoken commands must reach the planner, not the app launcher.

``open chrome and go to gmail`` is two actions. Until this slice it became one:
``open_app`` with the target "chrome and go to gmail" -- an application by that
name does not exist, so the user heard a success message and nothing happened.

The routing order was never wrong. ``process_voice_operator_turn`` already asks
the executive planner first (voice/operator.py:1130) and only then the device
parser. The planner declined because ``DeterministicDecomposer`` had no pattern
for "open X and go to Y", so its catch-all ``_single_step`` matched instead,
greedily reading the whole tail as an application name and producing exactly one
step -- and ``planner/routing.py:47`` declines anything under two steps. The
device parser's ``_match_app`` then made the same greedy read.

So there are two failures with one shape, and both are tested here:

* the decomposer must recognise the clause forms the planner can already
  execute, and
* nothing anywhere may accept a conjunction-joined phrase as an application
  name -- including for the forms the planner still cannot represent, which
  must be declined honestly rather than mangled.

Nothing here launches an application, types a key, or opens a browser. The
actuator is a recorder, the automation service is a double, and the planner is
observed at its decision boundary (see ``PlannerSpy``).
"""

from __future__ import annotations

from typing import Any

import pytest

from grandpa import pc_control
from grandpa.pc_control import _coerce_request
from grandpa.planner.decomposer import DeterministicDecomposer, normalize_goal
from grandpa.planner.models import Goal, PlannerLimits
from grandpa.voice.operator import parse_voice_operator_command


class RecordingActuator:
    """Stands in for ``run_local_action`` and records the coerced request."""

    def __init__(self) -> None:
        self.requests: list[Any] = []
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]):
        self.payloads.append(dict(payload))
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

    @property
    def targets(self) -> list[str]:
        return [request.target for request in self.requests]


class RecordingAutomation:
    """Stands in for ScreenAutomationService; records the command handed to it."""

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
        from types import SimpleNamespace

        self.commands.append(command)
        return SimpleNamespace(
            status="handled",
            message=f"recorded: {command}",
            data={},
            confirmation_token=None,
        )


class PlannerSpy:
    """Observes the planner at its decision boundary without executing a plan.

    The spy is deliberately not a stub with invented behaviour: it applies the
    *production* discriminator -- ``DeterministicDecomposer`` plus the two-step
    floor from ``planner/routing.py:47`` -- and returns None for anything the
    real router would decline, so the turn falls through to the device parser
    exactly as it does in production.

    It stops short of ``ExecutivePlanner.execute`` because that drives the
    desktop: it enumerates real windows, launches real applications and opens a
    real browser. Whether a claimed plan then succeeds is the executive
    planner's own concern, covered by ``tests/test_executive_planner.py``. What
    this file is responsible for is the routing decision, which is exactly what
    the spy captures.
    """

    def __init__(self) -> None:
        self.claimed: list[str] = []
        self.seen: list[str] = []
        self.steps: list[Any] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(
        self,
        text: str,
        *,
        automation_service=None,
        source: str = "chat",
        action_runner=None,
        origin: str = "direct",
    ):
        self.seen.append(text)
        self.kwargs.append({"action_runner": action_runner, "origin": origin})
        steps = DeterministicDecomposer().decompose(
            Goal(text, normalize_goal(text), "spy"), PlannerLimits()
        )
        if steps is None or len(steps) < 2:
            return None
        self.claimed.append(text)
        self.steps = list(steps)
        return f"Planning your task: {len(steps)} steps."


def _turn(text: str, monkeypatch, *, dry_run: bool = True):
    """Run the real production entry point with every side effect replaced."""
    from grandpa.voice.operator import process_voice_operator_turn

    spy = PlannerSpy()
    monkeypatch.setattr("grandpa.planner.routing.handle_executive_goal", spy)
    actuator = RecordingActuator()
    automation = RecordingAutomation()
    response = process_voice_operator_turn(
        text,
        dry_run=dry_run,
        action_runner=actuator,
        automation_service=automation,
    )
    return response, actuator, automation, spy


def _steps(text: str):
    return DeterministicDecomposer().decompose(
        Goal(text, normalize_goal(text), "t"), PlannerLimits()
    )


def _actions(text: str) -> list[str]:
    steps = _steps(text)
    return [] if steps is None else [step.action for step in steps]


def _params(text: str, action: str) -> dict[str, Any]:
    for step in _steps(text) or []:
        if step.action == action:
            return dict(step.parameters)
    raise AssertionError(f"{action!r} not in plan for {text!r}: {_actions(text)}")


# ---------------------------------------------------------------------------
# Controls -- single-step, conversational and blocked routing must not move
# ---------------------------------------------------------------------------


class TestSingleStepStillGoesToTheDevicePath:
    def test_open_chrome_is_one_device_action(self, monkeypatch):
        _response, actuator, _automation, spy = _turn("open chrome", monkeypatch)

        assert spy.claimed == [], "the planner claimed a single-step command"
        assert actuator.action_types == ["open_app"]
        assert actuator.targets == ["chrome"]

    def test_turn_up_the_volume_is_one_device_action(self, monkeypatch):
        _response, actuator, _automation, spy = _turn("turn up the volume", monkeypatch)

        assert spy.claimed == []
        assert actuator.action_types == ["volume_up"]

    def test_greeting_stays_conversational(self, monkeypatch):
        _response, actuator, _automation, spy = _turn("hello", monkeypatch)

        assert spy.claimed == []
        assert actuator.requests == [], "a greeting reached the actuator"

    def test_dangerous_command_is_blocked(self, monkeypatch):
        response, actuator, _automation, spy = _turn("shutdown", monkeypatch)

        assert response.status == "blocked"
        assert spy.claimed == []
        assert actuator.requests == []


# ---------------------------------------------------------------------------
# The gap: multi-step phrases the planner can already execute
# ---------------------------------------------------------------------------


class TestMultiStepReachesThePlanner:
    MULTISTEP = [
        "open chrome and go to gmail",
        "open chrome then go to gmail",
        "open chrome and search for fastapi",
        "open notepad and type hello world",
        "open chrome and go to github and search for fastapi",
    ]

    @pytest.mark.parametrize("phrase", MULTISTEP)
    def test_the_planner_claims_the_phrase(self, phrase, monkeypatch):
        _response, _actuator, _automation, spy = _turn(phrase, monkeypatch)

        assert spy.claimed == [phrase]

    @pytest.mark.parametrize("phrase", MULTISTEP)
    def test_the_device_parser_never_sees_it(self, phrase, monkeypatch):
        _response, actuator, _automation, _spy = _turn(phrase, monkeypatch)

        assert actuator.requests == [], (
            f"the device parser executed {actuator.action_types} for a phrase "
            "the planner had already claimed"
        )

    @pytest.mark.parametrize("phrase", MULTISTEP)
    def test_no_step_treats_the_whole_phrase_as_an_app_name(self, phrase, monkeypatch):
        _response, _actuator, _automation, spy = _turn(phrase, monkeypatch)

        apps = [
            str(step.parameters.get("app", ""))
            for step in spy.steps
            if "app" in step.parameters
        ]
        assert apps, f"no application step in the plan for {phrase!r}"
        for app in apps:
            assert " and " not in app and " then " not in app, (
                f"the whole phrase was read as the application name: {app!r}"
            )

    @pytest.mark.parametrize("phrase", MULTISTEP)
    def test_the_planner_is_given_the_turns_actuator_and_provenance(
        self, phrase, monkeypatch
    ):
        """A plan's steps end at the caller's actuator, attributed to voice."""
        _response, actuator, _automation, spy = _turn(phrase, monkeypatch)

        assert spy.kwargs[0]["action_runner"] is actuator
        assert spy.kwargs[0]["origin"] == "voice"

    @pytest.mark.parametrize("phrase", MULTISTEP)
    def test_the_response_reports_a_plan(self, phrase, monkeypatch):
        response, _actuator, _automation, _spy = _turn(phrase, monkeypatch)

        assert response.status == "handled"
        assert "Planning your task" in response.text


# ---------------------------------------------------------------------------
# Step content -- the individual steps must survive decomposition intact
# ---------------------------------------------------------------------------


class TestStepsArePreserved:
    def test_open_and_navigate_becomes_launch_then_navigate(self):
        actions = _actions("open chrome and go to gmail")

        assert actions[0] == "launch_application"
        assert "navigate_url" in actions

    def test_the_application_is_just_the_application(self):
        assert _params("open chrome and go to gmail", "launch_application") == {
            "app": "chrome"
        }

    def test_the_destination_is_carried_through_verbatim(self):
        assert _params("open chrome and go to gmail", "navigate_url") == {
            "url": "gmail"
        }

    @pytest.mark.parametrize("connector", ["and", "then"])
    def test_both_connectors_decompose_identically(self, connector):
        actions = _actions(f"open chrome {connector} go to gmail")

        assert actions == _actions("open chrome and go to gmail")

    @pytest.mark.parametrize("verb", ["go to", "navigate to"])
    def test_both_navigation_verbs_are_understood(self, verb):
        assert _params(f"open chrome and {verb} gmail", "navigate_url") == {
            "url": "gmail"
        }

    @pytest.mark.parametrize(
        ("spoken", "typed"),
        [
            ("open notepad and type Hello World", "Hello World"),
            ("open notepad and type Dear Dr Chen", "Dear Dr Chen"),
            ("open notepad and type API keys are SECRET", "API keys are SECRET"),
        ],
    )
    def test_typed_text_keeps_its_original_capitalisation(self, spoken, typed):
        """``type_text`` is a literal parameter -- casefolding would corrupt it.

        The pattern matches against the normalised (casefolded) goal, so the
        payload has to be sliced back out of the original text. Reading it off
        the match instead would type "dear dr chen".
        """
        assert _params(spoken, "type_text") == {"text": typed, "window": "notepad"}

    def test_typed_text_may_contain_the_connector_word(self):
        """The payload is terminal, so "and" inside it is text, not a clause."""
        assert (
            _params("open notepad and type salt and pepper", "type_text")["text"]
            == "salt and pepper"
        )

    def test_a_three_clause_command_keeps_all_three(self):
        text = "open chrome and go to github and search for fastapi"

        assert _actions(text)[0] == "launch_application"
        assert _params(text, "launch_application") == {"app": "chrome"}
        assert _params(text, "navigate_url") == {"url": "github"}
        assert _params(text, "browser_search")["query"] == "fastapi"

    def test_a_three_clause_command_orders_navigation_before_search(self):
        actions = _actions("open chrome and go to github and search for fastapi")

        assert actions.index("navigate_url") < actions.index("browser_search")

    def test_every_planned_action_is_in_the_existing_catalog(self):
        """No new planner action may be invented to make this route work."""
        from grandpa.planner.action_catalog import ACTION_CATALOG

        for phrase in TestMultiStepReachesThePlanner.MULTISTEP:
            for action in _actions(phrase):
                assert action in ACTION_CATALOG, f"{action!r} is not a catalog action"

    def test_the_existing_search_decomposition_is_unchanged(self):
        """The pattern that already worked must not be re-routed."""
        text = "open chrome and search for fastapi"

        assert _actions(text) == [
            "launch_application",
            "wait_for_window",
            "focus_window",
            "browser_search",
        ]
        assert _params(text, "browser_search") == {
            "query": "fastapi",
            "provider": "google",
        }


# ---------------------------------------------------------------------------
# Forms the planner cannot represent must be declined, never mangled
# ---------------------------------------------------------------------------


class TestUnsupportedMultiStepIsDeclinedHonestly:
    """There is no create-folder action in the planner catalog.

    "open downloads and create a folder called test" therefore cannot be
    planned, and inventing a step for it is out of scope. What must not happen
    is the old behaviour: launching an application called "downloads and create
    a folder called test". Declining is the correct answer.
    """

    UNSUPPORTED = [
        "open downloads and create a folder called test",
        "open chrome and water the plants",
    ]

    @pytest.mark.parametrize("phrase", UNSUPPORTED)
    def test_no_bogus_application_is_launched(self, phrase, monkeypatch):
        _response, actuator, _automation, _spy = _turn(phrase, monkeypatch)

        for target in actuator.targets:
            assert " and " not in target, f"launched an app named {target!r}"

    @pytest.mark.parametrize("phrase", UNSUPPORTED)
    def test_the_device_parser_does_not_claim_it_as_an_app(self, phrase):
        intent = parse_voice_operator_command(phrase)

        assert not (intent.action == "open_app" and " and " in intent.target)

    @pytest.mark.parametrize("phrase", UNSUPPORTED)
    def test_the_decomposer_declines_rather_than_guessing(self, phrase):
        assert _steps(phrase) is None

    @pytest.mark.parametrize("phrase", UNSUPPORTED)
    def test_the_single_step_catch_all_does_not_claim_it(self, phrase):
        """The catch-all is what used to manufacture the bogus one-step plan.

        It matched "open <anything>" and produced ``launch_application`` for an
        application named by the whole tail -- and a one-step plan is exactly
        what makes routing decline (planner/routing.py:47), so the same greedy
        read both invented the nonsense app and hid the goal from the planner.
        """
        from grandpa.planner.decomposer import _single_step, normalize_goal

        assert _single_step(normalize_goal(phrase)) is None

    @pytest.mark.parametrize(
        "phrase",
        ["open chrome and go to gmail", "open notepad and type hello world"],
    )
    def test_the_catch_all_declines_the_supported_forms_too(self, phrase):
        """Even the forms that now work must not fall back to a bogus app.

        Their plans come from the clause patterns above the catch-all. If one
        of those patterns is ever removed, the goal must stop being routable
        rather than quietly return to launching "chrome and go to gmail".
        """
        from grandpa.planner.decomposer import _single_step, normalize_goal

        assert _single_step(normalize_goal(phrase)) is None


# ---------------------------------------------------------------------------
# Safety: the block must run before the planner, not after it
# ---------------------------------------------------------------------------


class TestDangerousCommandsNeverReachAnExecutor:
    """The dangerous-command check used to run *after* the planner.

    It lives inside ``parse_voice_operator_command``, which the turn reaches
    only once the planner has declined. So a dangerous phrase the planner
    *claimed* was executed without the check ever running -- "open cmd and
    search for fastapi" decomposes to a four-step plan whose first step
    launches cmd. Widening what the planner claims widens that hole, so the
    check has to be ahead of the planner.
    """

    DANGEROUS = [
        "shutdown",
        "restart",
        "run powershell",
        "open cmd",
        "delete all my files",
        "format c drive",
        "open a shell",
        "run command",
    ]

    DANGEROUS_MULTISTEP = [
        "open cmd and search for fastapi",
        "open powershell and go to gmail",
        "open cmd and type whoami",
        "open notepad and type hello and then shutdown",
    ]

    @pytest.mark.parametrize("phrase", DANGEROUS + DANGEROUS_MULTISTEP)
    def test_blocked_with_zero_actuator_contact(self, phrase, monkeypatch):
        response, actuator, automation, _spy = _turn(phrase, monkeypatch)

        assert response.status == "blocked"
        assert actuator.requests == [], f"{phrase!r} reached the actuator"
        assert automation.commands == [], f"{phrase!r} reached the automation service"

    @pytest.mark.parametrize("phrase", DANGEROUS + DANGEROUS_MULTISTEP)
    def test_the_planner_is_not_even_consulted(self, phrase, monkeypatch):
        _response, _actuator, _automation, spy = _turn(phrase, monkeypatch)

        assert spy.seen == [], f"{phrase!r} was offered to the planner"

    @pytest.mark.parametrize("phrase", DANGEROUS + DANGEROUS_MULTISTEP)
    def test_the_parser_agrees_it_is_blocked(self, phrase):
        assert parse_voice_operator_command(phrase).kind == "blocked"


# ---------------------------------------------------------------------------
# The action boundary is still single
# ---------------------------------------------------------------------------


class TestOneActuatorBoundary:
    def test_single_step_voice_commands_reach_run_local_action(self, monkeypatch):
        _response, actuator, _automation, _spy = _turn("open chrome", monkeypatch)

        assert len(actuator.payloads) == 1
        assert actuator.payloads[0]["action_type"] == "open_app"
        assert actuator.payloads[0]["origin"] == "voice"

    def test_planner_steps_run_through_the_same_action_runner(self):
        """The planner does not carry its own executor to the device.

        Its steps go to the automation service, and the turn builds that
        service around the very ``action_runner`` the caller injected
        (voice/operator.py:1035), so both routes end at one boundary.
        """
        from grandpa.automation.executor import AutomationExecutor
        from grandpa.automation.service import ScreenAutomationService

        actuator = RecordingActuator()
        service = ScreenAutomationService(executor=AutomationExecutor(runner=actuator))

        assert service.executor.runner is actuator

    def test_the_default_runner_delegates_to_run_local_action(self, monkeypatch):
        """Injecting no runner still ends at the same boundary.

        ``AutomationExecutor`` defaults to ``_default_runner``, which imports
        and calls ``run_local_action`` lazily, so the identity check has to be
        made on the call rather than on the attribute.
        """
        from grandpa.automation.executor import AutomationExecutor, _default_runner

        seen: list[dict[str, Any]] = []
        monkeypatch.setattr(pc_control, "run_local_action", lambda p: seen.append(p))

        assert AutomationExecutor().runner is _default_runner
        _default_runner({"action_type": "volume_up"})
        assert seen == [{"action_type": "volume_up"}]
