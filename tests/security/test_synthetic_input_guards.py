"""The guards on synthetic input, on every route that can reach it.

Keys and mouse are arbitrary code execution: Win+R opens the Run dialog and
typing fills it in, which is exactly what BLOCKED_ACTIONS (script_run,
shell_run) exists to deny. These five properties came out of Phase 1.6, when
two modules owned synthetic input and each blocked what the other allowed:

1. Win+R, Win+X, Ctrl+Shift+Esc and Ctrl+Alt+Del are refused outright -- never
   offered for approval, because approving them is approving a shell.
2. Text naming a shell or a destructive command is refused.
3. Input is refused while the active window looks sensitive.
4. A refusal does not start the cooldown: one blocked hotkey must not make the
   next honest action fail, and fail with the wrong reason.
5. (tests/security/test_voice_confirmation.py) Voice cannot actuate at all.

Each is checked on every route that reaches the actuator -- the spec runner,
the action layer, pc_control with an approved code, a parsed phrase, and Screen
Automation V2 -- because the 1.6 bug was a guard that held on one route and not
another. Every actuator is replaced by tests.security.input_recorder first, so
a failure here is recorded rather than typed into the machine running the test.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.security.input_recorder import install

# Opted out of the default-deny actuation fixture (tests/actuation_guard.py):
pytestmark = pytest.mark.real_actions(
    reason="drives the real desktop service, with the OS-level calls under it stubbed or recorded by the test"
)

BLOCKED_HOTKEYS = ["win+r", "win+x", "ctrl+shift+esc", "ctrl+alt+delete"]
BLOCKED_TEXT = ["powershell", "cmd.exe", "format c:"]


@pytest.fixture
def recorder(monkeypatch, tmp_path):
    import grandpa.desktop.control.automation as automation

    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    # The cooldown is module state: without this, a test that actuates leaves
    # the next one blocked for 0.35s and the assertion would read as a guard.
    monkeypatch.setattr(automation, "_last_action_at", 0.0)
    return install(monkeypatch)


def _typed_or_pressed(rec) -> list[str]:
    return [
        name
        for name in rec.actuated
        if name.startswith(("pyautogui.", "user32.keybd_event", "win32api."))
    ]


# --- the routes ------------------------------------------------------------------
#
# Each takes a catalogued action and its parameters, and drives one way in with
# consent already given, so what stops the action is the guard and not a missing
# yes.


def _via_spec(action: str, parameters: dict[str, Any]) -> Any:
    from grandpa.desktop.control.automation import execute_spec

    spec = {
        "keyboard_hotkey": lambda p: "hotkey|" + "+".join(p["keys"]),
        "keyboard_type": lambda p: f"type|{p['text']}",
    }[action](parameters)
    return execute_spec(spec, confirm_callback=lambda *_a: True)


def _via_layer(action: str, parameters: dict[str, Any]) -> Any:
    from grandpa.action_layer.catalogue import get
    from grandpa.action_layer.executor import execute
    from grandpa.action_layer.model import ActionRequest, Origin

    spec = get(action)
    return execute(
        ActionRequest(
            action,
            parameters,
            origin=Origin.USER_CHAT,
            risk=spec.risk,
            requires_confirmation=spec.requires_confirmation,
        ),
        lambda *_a, **_k: True,
    )


def _via_pc_control(action: str, parameters: dict[str, Any]) -> Any:
    """pc_control's own route: stage, then approve with the out-of-band code."""
    from grandpa import pc_control

    staged = pc_control.run_local_action({"action_type": action, "args": parameters})
    if not staged.approval_required or not staged.action_id:
        return staged
    record = pc_control._load_pending_record(staged.action_id)
    assert record is not None, "pc_control did not stage the action"
    return pc_control.approve_local_action(staged.action_id, record.approval_token)


def _via_phrase(action: str, parameters: dict[str, Any]) -> Any:
    """A typed phrase through local_actions, with chat's inline yes."""
    from grandpa.local_actions import handle_local_action

    phrase = {
        "keyboard_hotkey": lambda p: "press " + "+".join(p["keys"]),
        "keyboard_type": lambda p: f"type {p['text']}",
    }[action](parameters)
    return handle_local_action(phrase, confirm=lambda *_a: True)


ROUTES = {
    "spec": _via_spec,
    "layer": _via_layer,
    "pc_control": _via_pc_control,
    "phrase": _via_phrase,
}

# Routes that can carry arbitrary keys. The phrase route is not one of them:
# local_actions' parser has a fixed vocabulary (enter, tab, escape, copy,
# paste, alt+tab) with no way to ask for Win+R at all, which the test below
# pins instead. Mutation-checked: with the denylist disabled, every route here
# fails and the phrase route does not, which is what told me it was vacuous.
ARBITRARY_KEY_ROUTES = ["layer", "pc_control", "spec"]


# --- 1: command-execution hotkeys ------------------------------------------------


@pytest.mark.parametrize("route", ARBITRARY_KEY_ROUTES)
@pytest.mark.parametrize("keys", BLOCKED_HOTKEYS)
def test_a_command_execution_hotkey_is_refused_on_every_route(
    recorder, route, keys
) -> None:
    ROUTES[route]("keyboard_hotkey", {"keys": keys.split("+")})

    assert _typed_or_pressed(recorder) == [], f"{route} pressed {keys}"


@pytest.mark.parametrize("keys", BLOCKED_HOTKEYS)
def test_no_phrase_can_ask_for_a_command_execution_hotkey(keys) -> None:
    """The phrase route's defence is vocabulary: there is no way to say it."""
    from grandpa.local_actions import _normalise, _parse_safe_action

    for phrase in (f"press {keys}", f"hotkey {keys}", f"press the {keys} keys"):
        parsed = _parse_safe_action(_normalise(phrase))
        assert parsed.kind != "automation" or keys not in parsed.target, parsed


def test_screen_automation_v2_does_not_actuate_a_command_execution_hotkey(
    recorder,
) -> None:
    """V2 asks, and its yes still does not reach the keyboard.

    Not the denylist doing the work here -- V2 hands the action to pc_control,
    whose approval code nobody in this flow has. Pinned so that a future tranche
    routing V2 past that gate has to keep the denylist in front of it.
    """
    from grandpa.automation.service import ScreenAutomationService
    from tests.security.input_recorder import _fake_windows

    service = ScreenAutomationService()
    service.pin_target(_fake_windows()[0])

    asked = service.handle("press win+r")
    if asked.confirmation_token:
        service.confirm(asked.confirmation_token)

    assert _typed_or_pressed(recorder) == []


def test_an_ordinary_hotkey_still_works(recorder) -> None:
    """The guard is a denylist, not a refusal of everything."""
    _via_spec("keyboard_hotkey", {"keys": ["ctrl", "c"]})

    assert _typed_or_pressed(recorder) == ["pyautogui.hotkey"]


# --- 2: text naming a shell ------------------------------------------------------


@pytest.mark.parametrize("route", ARBITRARY_KEY_ROUTES)
@pytest.mark.parametrize("text", BLOCKED_TEXT)
def test_text_naming_a_shell_is_refused_on_every_route(recorder, route, text) -> None:
    ROUTES[route]("keyboard_type", {"text": text})

    assert _typed_or_pressed(recorder) == [], f"{route} typed {text!r}"


@pytest.mark.parametrize("text", BLOCKED_TEXT)
def test_a_phrase_naming_a_shell_is_refused_before_it_is_parsed(recorder, text) -> None:
    """The phrase route refuses earlier, at local_actions' dangerous-text guard."""
    from grandpa.local_actions import BLOCKED_MESSAGE

    result = _via_phrase("keyboard_type", {"text": text})

    # The message says which guard refused: the service's own refusal reads
    # differently, so this fails if the phrase only gets as far as that one.
    assert result.status == "blocked", result
    assert result.message == BLOCKED_MESSAGE, result
    assert _typed_or_pressed(recorder) == []


def test_ordinary_text_is_still_typed(recorder) -> None:
    _via_spec("keyboard_type", {"text": "hello there"})

    assert _typed_or_pressed(recorder) == ["pyautogui.write"]


# --- 3: a sensitive active window ------------------------------------------------


@pytest.fixture
def sensitive_window(monkeypatch):
    import grandpa.desktop_context as desktop_context

    monkeypatch.setattr(desktop_context, "active_window_is_protected", lambda: True)
    assert desktop_context.active_window_is_protected(), "the stand-in did not hold"


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_a_sensitive_window_refuses_input_on_every_route(
    recorder, sensitive_window, route
) -> None:
    ROUTES[route]("keyboard_type", {"text": "hello"})

    assert _typed_or_pressed(recorder) == [], f"{route} typed into a sensitive window"


# --- 4: a refusal does not start the cooldown ------------------------------------


def test_a_refused_hotkey_does_not_start_the_cooldown(recorder, monkeypatch) -> None:
    """Otherwise one blocked hotkey fails the next honest action, for the wrong reason."""
    import grandpa.desktop.control.automation as automation

    monkeypatch.setattr(automation, "_last_action_at", 0.0)

    _via_spec("keyboard_hotkey", {"keys": ["win", "r"]})
    allowed = _via_spec("keyboard_hotkey", {"keys": ["ctrl", "c"]})

    assert _typed_or_pressed(recorder) == ["pyautogui.hotkey"]
    assert allowed.status == "handled", allowed


def test_a_refused_text_does_not_start_the_cooldown(recorder, monkeypatch) -> None:
    import grandpa.desktop.control.automation as automation

    monkeypatch.setattr(automation, "_last_action_at", 0.0)

    _via_spec("keyboard_type", {"text": "powershell"})
    allowed = _via_spec("keyboard_type", {"text": "hello"})

    assert _typed_or_pressed(recorder) == ["pyautogui.write"]
    assert allowed.status == "handled", allowed


def test_a_completed_action_does_start_the_cooldown(recorder, monkeypatch) -> None:
    import grandpa.desktop.control.automation as automation

    monkeypatch.setattr(automation, "_last_action_at", 0.0)

    first = _via_spec("keyboard_type", {"text": "hello"})
    second = _via_spec("keyboard_type", {"text": "again"})

    assert first.status == "handled"
    assert second.status == "blocked", second
    assert _typed_or_pressed(recorder) == ["pyautogui.write"]
