"""Voice cannot actuate keys or mouse without consent -- and typing is the only
thing it can consent to.

This file's property changed when the route opened, and the change is recorded
rather than quietly applied. It used to be absolute: nothing a person says,
including "yes", sends keyboard or mouse input. It is now three parts:

  1. typing is the only input voice can actuate, and only through the whole
     consent sequence -- a witnessed stage, a yes on the very next turn, and the
     foreground window unchanged;
  2. a staged keystroke with no yes actuates nothing;
  3. every other input kind voice can phrase still actuates nothing, whatever it
     is answered with.

The original reasoning was that voice has no way to consent to synthetic input:
its only question is the next utterance, and an utterance is exactly what a stray
sentence, a television, or a misheard word supplies. That objection was not
dismissed -- it was answered. A stray "yes" now has to arrive on the turn
immediately after the ask, against a foreground window that has not changed since
it, for an action whose read-back named that window out loud. A television
supplies none of that.

What has not changed is that the property is checked by driving voice and
watching the actuators at the bottom of the stack, never by reading a status.

These tests used to pin a mechanism instead -- "every voice call site passes
``confirm=refuse_confirmation``". That mechanism is gone: voice now opts into
deferred consent (``deferred_origin="voice"``), so a staged action can be
approved by voice's own next turn, and a callback that always said no is no
longer what stands between voice and the keyboard. The old assertion would
pass or fail on a keyword argument; the property can only be checked by
driving voice and watching the actuators.

So three things are pinned here, each for a different way of losing it:

a) Outcome. Voice synthetic input, then a spoken "yes", actuates nothing --
   asserted on recorders that replaced every input primitive, never on a
   returned status.
b) Coverage. Every voice call site into local actions opts into deferred
   consent and passes no inline callback that could approve, and every
   automation service voice builds refuses input. Enumerated from the source,
   so a new call site added without the guard fails here.
c) Tranche guard. Every input kind voice can phrase -- typing, keys, clicks,
   scroll, browser hotkeys -- through every voice entry point, after pinning a
   target and answering yes twice, actuates nothing. Recorded at the bottom of
   the stack, so it holds whichever component does the refusing: the synthetic-
   input tranche will replace today's gates, and this is what tells it whether
   it kept the property.

Every actuator is replaced by ``input_recorder.install`` before anything runs,
and the fixture proves the replacement held. A probe in this session sent a
real Ctrl+C to the foreground window through a gate that was assumed to hold.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.security.input_recorder import install

VOICE_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "grandpa" / "voice"

# Not keyboard or mouse input. Window focus and state: focusing asks nowhere in
# Grandpa, and closing asks on every route. Launches: the recorder refuses them
# so a test cannot start anything, but opening a page or an app is guarded by
# the launch confirmations, not by this property.
_NOT_INPUT = (
    "subprocess.Popen",
    "os.startfile",
    "webbrowser.open",
    "ShellExecuteW",
    "ShellExecute",
    "launch_app",
    "grandpa.automation.windows.focus_window_handle",
    "grandpa.windows_window_control._apply_action",
    "user32.SetForegroundWindow",
    "user32.BringWindowToTop",
    "user32.ShowWindow",
    "win32gui.SetForegroundWindow",
    "win32gui.BringWindowToTop",
    "win32gui.ShowWindow",
)


def _input_only(actuated: list[str]) -> list[str]:
    return [name for name in actuated if name not in _NOT_INPUT]


@pytest.fixture
def recorder(monkeypatch, tmp_path):
    import grandpa.desktop.control.automation as automation

    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    # Module state. AutomationControlService refuses an action within
    # _ACTION_COOLDOWN_SECONDS of the last successful one, and that timestamp
    # lives on the module, so it survives between tests. Every test in this file
    # used to assert that *nothing* actuated, and a leftover cooldown made those
    # pass for the wrong reason without anyone noticing. The positive tests added
    # with the typing route are the first here that need an action to succeed, and
    # they failed only when run after the others -- which is exactly what
    # tests/security/test_no_staged_input.py's fixture warns about.
    monkeypatch.setattr(automation, "_last_action_at", 0.0)
    return install(monkeypatch)


# --- the three voice entry points, each built the way voice builds it ----------


def _processor(monkeypatch):
    from grandpa.voice.assistant import VoiceAssistantResponse, VoiceCommandProcessor

    # The model is not under test; a turn that reaches it says so.
    monkeypatch.setattr(
        VoiceCommandProcessor,
        "_generate_response",
        lambda self, text, **kwargs: VoiceAssistantResponse(
            "LLM fallback", status="handled", kind="chat"
        ),
    )
    processor = VoiceCommandProcessor()
    return lambda text: processor.handle_user_input(text).text


def _session(monkeypatch):
    """VoiceRuntime's route, with the automation service it keeps across turns."""
    import grandpa.voice.session as session

    for helper in (
        "_safe_planner",
        "_safe_knowledge_context",
        "_safe_memory_context",
        "_safe_agent_goal",
    ):
        monkeypatch.setattr(session, helper, lambda _text: None)
    service = session.VoiceRuntime.__dataclass_fields__[
        "automation_service"
    ].default_factory()
    return lambda text: str(
        session._route_voice_request(text, automation_service=service).get("message")
    )


def _http(monkeypatch, tmp_path):
    """/v1/voice/command with ``confirmed: true`` -- consent given up front."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from grandpa.server.api_routes import voice_router

    monkeypatch.setenv("GRANDPA_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_EMBEDDING_MODE", "fallback")
    app = FastAPI()
    app.include_router(voice_router)
    client = TestClient(app)

    def say(text: str) -> str:
        body = client.post(
            "/v1/voice/command", json={"transcript": text, "confirmed": True}
        ).json()
        token = body.get("confirmation_token")
        if token:
            body = client.post(
                "/v1/voice/confirm", json={"confirmation_token": token}
            ).json()
        return str(body.get("assistant_text") or body)

    return say


ENTRY_POINTS = ("processor", "session", "http")


def _voice(entry: str, monkeypatch, tmp_path):
    if entry == "processor":
        return _processor(monkeypatch)
    if entry == "session":
        return _session(monkeypatch)
    return _http(monkeypatch, tmp_path)


# --- a) outcome ------------------------------------------------------------------


@pytest.mark.parametrize("phrase", ["press enter", "copy selected text"])
@pytest.mark.parametrize("entry", ["processor", "session"])
def test_voice_input_then_a_spoken_yes_actuates_nothing(
    recorder, monkeypatch, tmp_path, entry, phrase
) -> None:
    say = _voice(entry, monkeypatch, tmp_path)

    say(phrase)
    say("yes")

    assert _input_only(recorder.actuated) == [], recorder.calls


# --- b) coverage -------------------------------------------------------------------


def _voice_modules() -> list[tuple[str, ast.Module]]:
    return [
        (path.name, ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(VOICE_PACKAGE.rglob("*.py"))
    ]


def _called_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


# Callbacks that can only refuse. Anything else passed as ``confirm`` from voice
# could approve.
_REFUSING_CALLBACKS = {"refuse_confirmation"}


def test_every_voice_call_into_local_actions_opts_into_deferred_consent() -> None:
    calls = [
        (module, call)
        for module, tree in _voice_modules()
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and _called_name(call) == "handle_local_action"
    ]
    # Enumerated, not listed: a new call site is checked the moment it exists.
    # This only guards against the enumeration itself going blind.
    assert calls, "no voice call into handle_local_action found -- did it move?"

    for module, call in calls:
        where = f"voice/{module}:{call.lineno}"
        origin = _keyword(call, "deferred_origin")
        assert isinstance(origin, ast.Constant) and origin.value == "voice", (
            f'{where} calls handle_local_action without deferred_origin="voice"'
        )
        confirm = _keyword(call, "confirm")
        if confirm is not None:
            assert (
                isinstance(confirm, ast.Name) and confirm.id in _REFUSING_CALLBACKS
            ), f"{where} passes confirm={ast.unparse(confirm)}, which could approve"


def test_every_automation_service_voice_builds_refuses_input() -> None:
    builds = []
    for module, tree in _voice_modules():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and _called_name(node) == "ScreenAutomationService"
            ):
                builds.append((module, node))
            # field(default_factory=ScreenAutomationService) builds one too,
            # without a call to see.
            if isinstance(node, ast.keyword) and node.arg == "default_factory":
                assert not (
                    isinstance(node.value, ast.Name)
                    and node.value.id == "ScreenAutomationService"
                ), (
                    f"voice/{module}:{node.value.lineno} defaults to an input-capable service"
                )
    assert builds, "voice builds no automation service -- did it move?"

    for module, call in builds:
        allow = _keyword(call, "allow_input")
        assert isinstance(allow, ast.Constant) and allow.value is False, (
            f"voice/{module}:{call.lineno} builds ScreenAutomationService "
            "without allow_input=False"
        )


# --- c) tranche guard --------------------------------------------------------------
#
# This guard used to say: voice actuates no keyboard or mouse input, by any
# route, ever. That property is gone, deliberately, and this is the record of the
# moment it went.
#
# It held for two reasons stacked on each other. Screen Automation V2 refused
# every input phrase for a caller with allow_input=False, and even if it had not,
# no parsed phrase mapped to a catalogued synthetic action so the action layer
# would have refused too. Voice consent (the witness, the turn counter, the spoken
# read-back) was built under that shadow and could not be reached.
#
# Both were opened, one bolt at a time. The new property is narrower and has to be
# stated in three parts rather than one, because "nothing" is no longer the
# answer:
#
#   1. Typing is the only input voice can actuate, and only through the full
#      consent sequence: a witnessed stage, then a yes on the very next turn,
#      with the foreground window unchanged.
#   2. A staged keystroke with no yes actuates nothing. Staging is not sending.
#   3. Every other input kind voice can phrase -- keys, paste, clicks, scroll,
#      browser hotkeys -- still actuates nothing, whatever it is answered with.
#
# Part 3 is the old guard, unchanged, over everything except typing. Parts 1 and 2
# are what replaced it for typing. If part 1 ever passes for a second kind,
# something opened a bolt without reading this.

#: The one kind voice can now actuate, and the phrase that reaches it.
TYPING_PHRASE = "type hello"

#: Every other kind of input voice can phrase, including browser hotkeys, which
#: reach the keyboard by a route of their own.
OTHER_INPUT_PHRASES = (
    "press enter",
    "paste",
    "select all",
    "copy selected text",
    "click",
    "double click",
    "right click",
    "scroll down",
    "go back",
    "reload the page",
    "open a new tab",
)


@pytest.fixture
def steady_window(monkeypatch):
    """The same window in front for every reading.

    The consent path takes a real reading of the foreground window, which during
    a test run is whatever the developer happens to have focused -- so an alt-tab
    between the ask and the yes would fail these tests for a reason that has
    nothing to do with what voice may actuate. Pinning the reading keeps this
    guard about its subject; tests/desktop cover the reading itself.
    """
    from grandpa.desktop import focus_witness
    from tests.witness_support import make_witness

    monkeypatch.setattr(
        focus_witness,
        "capture",
        lambda **_kwargs: make_witness(title="Untitled - Notepad"),
    )


@pytest.mark.real_actions(
    reason="reaches the real grandpa.browser.executor.BrowserExecutor.execute, grandpa.browser_control.execute_browser_action"
)
@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_voice_actuates_no_input_kind_except_typing(
    recorder, monkeypatch, tmp_path, entry, steady_window
) -> None:
    """Part 3: the old guard, still absolute, over everything but typing.

    Fails loudly the day voice can press, paste, click or scroll -- whatever
    lets it.
    """
    say = _voice(entry, monkeypatch, tmp_path)
    # A pinned target is what Screen Automation needs before it acts; voice can
    # pin one by saying so. Without it most of these stop at "which window?",
    # and the test would be checking that instead of consent.
    say("bring notepad to the front")

    reached: dict[str, list[str]] = {}
    for phrase in OTHER_INPUT_PHRASES:
        recorder.calls.clear()
        say(phrase)
        say("yes")
        say("yes")
        if actuated := _input_only(recorder.actuated):
            reached[phrase] = actuated

    assert reached == {}, f"voice actuated input it may not: {reached}"


@pytest.mark.real_actions(
    reason="drives the real AutomationControlService for the approved keystroke; "
    "input_recorder replaced pyautogui, so it is recorded rather than typed"
)
@pytest.mark.parametrize("entry", ["processor", "session"])
def test_voice_staging_a_keystroke_sends_nothing_until_the_yes(
    recorder, monkeypatch, tmp_path, entry, steady_window
) -> None:
    """Part 2: staging is not sending.

    The ask is a whole turn on its own, and nothing may reach an actuator during
    it. Without this, part 1 passing would not distinguish "typed after consent"
    from "typed on being asked".
    """
    say = _voice(entry, monkeypatch, tmp_path)
    say("bring notepad to the front")
    recorder.calls.clear()

    say(TYPING_PHRASE)

    assert _input_only(recorder.actuated) == [], (
        f"voice typed while only asking: {recorder.calls}"
    )


@pytest.mark.real_actions(
    reason="drives the real AutomationControlService for the approved keystroke; "
    "input_recorder replaced pyautogui, so it is recorded rather than typed"
)
@pytest.mark.parametrize("entry", ["processor", "session"])
def test_voice_typing_reaches_an_actuator_after_a_yes(
    recorder, monkeypatch, tmp_path, entry, steady_window
) -> None:
    """Part 1: the capability this tranche added, asserted positively.

    A guard that only says what cannot happen would pass just as well if voice
    were broken. This is the thing that had to become true.
    """
    say = _voice(entry, monkeypatch, tmp_path)
    say("bring notepad to the front")
    recorder.calls.clear()

    say(TYPING_PHRASE)
    say("yes")

    assert _input_only(recorder.actuated), (
        f"the approved keystroke never reached an actuator: {recorder.calls}"
    )


@pytest.mark.real_actions(reason="same real path as above, actuators recorded")
@pytest.mark.parametrize("entry", ["processor", "session"])
def test_a_yes_one_turn_late_types_nothing(
    recorder, monkeypatch, tmp_path, entry, steady_window
) -> None:
    """Part 1's boundary: the consent is good for the next turn, not for later."""
    say = _voice(entry, monkeypatch, tmp_path)
    say("bring notepad to the front")
    recorder.calls.clear()

    say(TYPING_PHRASE)
    say("what is the time")
    say("yes")

    assert _input_only(recorder.actuated) == [], (
        f"a stale yes typed something: {recorder.calls}"
    )


@pytest.mark.real_actions(reason="same real path as above, actuators recorded")
@pytest.mark.parametrize("entry", ["processor", "session"])
def test_typing_is_refused_when_the_window_changed(
    recorder, monkeypatch, tmp_path, entry
) -> None:
    """Part 1's other boundary, and the reason the witness exists at all."""
    from grandpa.desktop import focus_witness
    from tests.witness_support import make_witness, stub_capture

    say = _voice(entry, monkeypatch, tmp_path)
    say("bring notepad to the front")
    recorder.calls.clear()
    # Notepad when staged, Chrome when the yes arrives.
    stub_capture(
        monkeypatch,
        [
            make_witness(title="Untitled - Notepad"),
            make_witness(exe_path=r"c:\chrome.exe", title="New Tab - Chrome"),
        ],
    )

    say(TYPING_PHRASE)
    say("yes")

    assert _input_only(recorder.actuated) == [], (
        f"voice typed into a window that was not the one approved: {recorder.calls}"
    )
    assert focus_witness.WITNESS_ORIGINS == frozenset({"voice"})
