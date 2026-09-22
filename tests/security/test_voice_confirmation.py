"""Voice cannot actuate keys or mouse without consent -- and today, not at all.

The property: nothing a person says to Grandpa, including "yes", sends keyboard
or mouse input. Voice has no way to consent to synthetic input: its only
question is the next utterance, and an utterance is exactly what a stray
sentence, a television, or a misheard word supplies.

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

# Opted out of the default-deny actuation fixture (tests/actuation_guard.py):
pytestmark = pytest.mark.real_actions(
    reason="drives the real browser implementation with the opener and hotkey runner the test supplies"
)

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
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
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

# Every kind of input voice can phrase, and browser hotkeys, which reach the
# keyboard by a route of their own.
INPUT_PHRASES = (
    "type hello",
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


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_voice_cannot_actuate_keys_or_mouse_by_any_route(
    recorder, monkeypatch, tmp_path, entry
) -> None:
    """Fails loudly the day voice can type, click or scroll -- whatever lets it."""
    say = _voice(entry, monkeypatch, tmp_path)
    # A pinned target is what Screen Automation needs before it acts; voice can
    # pin one by saying so. Without it most of these stop at "which window?",
    # and the test would be checking that instead of consent.
    say("bring notepad to the front")

    reached: dict[str, list[str]] = {}
    for phrase in INPUT_PHRASES:
        recorder.calls.clear()
        say(phrase)
        say("yes")
        say("yes")
        if actuated := _input_only(recorder.actuated):
            reached[phrase] = actuated

    assert reached == {}, f"voice actuated input: {reached}"
