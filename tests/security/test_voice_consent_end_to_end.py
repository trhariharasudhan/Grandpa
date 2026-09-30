"""Voice stages a keystroke; the window changes; nothing is typed.

The one test that would catch this whole tranche being wrong. Everything else
checks a tier, a wording or a counter in isolation; this drives the voice turn
loop the way a person does -- an utterance, then "yes" -- and watches the
actuators at the bottom of the stack.

Driven through ``VoiceCommandProcessor.handle_user_input``, so the turn counter
is incremented by the same wrapper that does it in production rather than by the
test. A turn that does not count itself would make the expiry untestable.

**No test-only mapping.** An earlier version of this file had to install one --
``("automation", "hotkey|ctrl+c")`` -- because the route did not exist and the
consent path was unreachable. That was the honest way to test mechanism without a
route, and it is gone: "type hello" is a phrase the shipped parser turns into
``("automation", "type|hello")``, ``_PREFIXED`` maps to ``keyboard_type``, and
Screen Automation V2 hands to the layer. If any of that regresses, these tests
fail rather than quietly testing a fixture.

The actuator is recorded, not live: ``input_recorder.install`` replaces every
input primitive before anything runs, so the happy path proves a keystroke
*reached* an actuator without one reaching the machine.

The only thing stubbed is which window is in front. ``focus_witness.capture``
reads the real foreground window, which during a test run is whatever the
developer happens to have focused -- so an alt-tab between the ask and the yes
would fail these for a reason that has nothing to do with the route. Reading the
window is covered by tests/desktop; this file is about what voice can actuate.

The audio guard stays armed throughout. Nothing here opens a microphone or
speaks: the read-back is returned as text and asserted as text.
"""

from __future__ import annotations

import pytest

from grandpa import pc_control
from grandpa.desktop.kernel import approvals
from tests.security.input_recorder import install
from tests.witness_support import make_witness, stub_capture

#: A phrase the shipped parser handles, mapped by the shipped tables.
PHRASE = "type hello"
ACTION = "keyboard_type"


@pytest.fixture
def recorder(monkeypatch, tmp_path):
    import grandpa.desktop.control.automation as automation

    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    monkeypatch.setattr(automation, "_last_action_at", 0.0)
    return install(monkeypatch)


@pytest.fixture
def voice(monkeypatch):
    """VoiceRuntime's route, with nothing about the route stubbed.

    Both Python voice entry points reach the layer now that V2 yields typing --
    the processor does too, once a target is pinned. This one is used because it
    is the shortest path to the layer; the tranche guard exercises both.
    """
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

    def say(text: str) -> str:
        routed = session._route_voice_request(text, automation_service=service)
        return str(routed.get("message") or "")

    # Screen Automation needs a pinned window before it will consider an input
    # phrase at all; a person pins one by saying so. Without it the turn stops at
    # "which window?" and the test would be measuring that instead of consent.
    say("bring notepad to the front")
    return say


def _keys_sent(recorder) -> list[str]:
    return [name for name in recorder.actuated if name.startswith("pyautogui.")]


def _pending() -> list[dict]:
    with pc_control._connect_approval_db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT action_type, status, witness_json FROM "
                "pc_control_approvals WHERE status = 'pending'"
            ).fetchall()
        ]


def test_the_audio_guard_is_armed_for_these_tests() -> None:
    """Stated here so this file cannot quietly become the one that speaks aloud."""
    import sounddevice as sd

    from tests.actuation_guard import is_denied

    assert is_denied(sd, "play")
    assert is_denied(sd, "rec")


@pytest.mark.real_actions(
    reason="drives the real AutomationControlService so an approved keystroke "
    "reaches an actuator; input_recorder replaced pyautogui before anything ran, "
    "so it is recorded rather than sent to the machine"
)
def test_the_window_changes_and_nothing_is_typed(recorder, monkeypatch, voice) -> None:
    """The case the witness exists for.

    Voice stages a keystroke against Notepad. Before the yes arrives the
    foreground window is Chrome. The keystroke must not be sent, and the user
    must be told what did not happen.
    """
    notepad = make_witness(title="Untitled - Notepad")
    chrome = make_witness(exe_path=r"c:\chrome.exe", title="New Tab - Chrome")
    stub_capture(monkeypatch, [notepad, chrome])

    staged = voice(PHRASE)
    assert "Untitled - Notepad" in staged, staged
    assert _pending(), "voice did not stage the keystroke"
    assert _keys_sent(recorder) == [], "staging sent a keystroke"

    answered = voice("yes")

    assert _keys_sent(recorder) == [], (
        f"a keystroke was sent after the window changed: {recorder.calls}"
    )
    # Typing's own wording, not the hotkey's: the read-back names what did not
    # happen per action, and this route is keyboard_type.
    assert "did not type anything" in answered, answered
    assert "Chrome" in answered and "Notepad" in answered

    # The row approved against Notepad is gone. What is pending is the re-ask,
    # and it is witnessed against Chrome -- the window actually in front now. A
    # row still witnessed against Notepad would mean the old approval survived.
    rows = _pending()
    assert len(rows) == 1, rows
    assert "New Tab - Chrome" in rows[0]["witness_json"]
    assert "Untitled - Notepad" not in rows[0]["witness_json"]


@pytest.mark.real_actions(
    reason="drives the real AutomationControlService so the approved keystroke "
    "reaches an actuator; input_recorder replaced pyautogui, so it is recorded"
)
def test_the_same_window_and_a_yes_sends_the_keystroke(
    recorder, monkeypatch, voice
) -> None:
    """The happy path, and the reason the refusal above is not just a blanket no.

    Same window at both readings, yes on the next turn: the keystroke reaches an
    actuator. Recorded, so nothing lands on the machine running this.
    """
    notepad = make_witness(title="Untitled - Notepad")
    stub_capture(monkeypatch, [notepad, make_witness(title="Untitled - Notepad")])

    staged = voice(PHRASE)
    assert _pending(), staged
    assert _keys_sent(recorder) == []

    voice("yes")

    assert _keys_sent(recorder), (
        "the approved keystroke never reached an actuator; "
        f"recorded calls: {recorder.calls}"
    )
    assert _pending() == [], "the row was not consumed by the approval"


@pytest.mark.real_actions(
    reason="same real path as the tests above, with the actuators recorded"
)
def test_the_turn_counter_advanced_by_the_voice_loop_itself(
    recorder, monkeypatch, voice
) -> None:
    """The expiry is only real if the production loop counts the turns.

    If the wrapper on handle_user_input stopped bumping, every staged keystroke
    would sit at current == staged and never be redeemable -- a failure that
    looks like safety and is actually a broken feature. This asserts the counter
    moves because voice took a turn.
    """
    stub_capture(monkeypatch, [make_witness(), make_witness()])
    before = approvals.current_turn("voice")

    voice(PHRASE)
    after_stage = approvals.current_turn("voice")
    voice("yes")

    assert after_stage == before + 1, "a voice turn did not advance the counter"
    assert approvals.current_turn("voice") == before + 2
    assert _keys_sent(recorder), "the happy path stopped working"


@pytest.mark.real_actions(reason="same real path, actuators recorded")
def test_a_yes_one_turn_too_late_sends_nothing(recorder, monkeypatch, voice) -> None:
    """An idle turn between the ask and the yes drops the keystroke."""
    stub_capture(monkeypatch, [make_witness()])

    voice(PHRASE)
    voice("what is the time")  # an unrelated turn passes
    answered = voice("yes")

    assert _keys_sent(recorder) == [], recorder.calls
    assert "too late" in answered.lower(), answered
    assert _pending() == []


@pytest.mark.real_actions(reason="same real path, actuators recorded")
def test_no_witness_means_voice_is_refused_exactly_as_before(
    recorder, monkeypatch, voice
) -> None:
    """The invariant that did not change.

    On a platform or a machine where the foreground window cannot be read, voice
    is refused and nothing is staged -- which is what every caller without a
    witness still gets.
    """
    stub_capture(monkeypatch, [None])

    answered = voice(PHRASE)

    assert _pending() == [], "an unwitnessed keystroke was staged"
    assert _keys_sent(recorder) == []
    assert "nothing was run" in answered or "cannot ask" in answered, answered


# --- the same real phrase, from callers that are not voice ----------------------


@pytest.mark.real_actions(reason="same real path, actuators recorded")
def test_chat_saying_the_same_phrase_gets_no_deferred_keystroke(
    recorder, monkeypatch
) -> None:
    """Chat reaches the same mapping and gets nothing staged.

    Not a weaker version of voice's path -- a different one. Chat has an inline
    callback, so run_parsed never reaches the deferred branch; and if it somehow
    arrived there without one, the origin allowlist refuses it. Both are checked
    here: no pending row, and nothing typed.
    """
    from grandpa.local import handle_local_action

    stub_capture(monkeypatch, [make_witness()])

    handle_local_action(PHRASE, deferred_origin="chat")
    handle_local_action("yes", deferred_origin="chat")

    assert _pending() == [], f"chat staged a keystroke: {_pending()}"
    assert _keys_sent(recorder) == [], recorder.calls


@pytest.mark.real_actions(reason="same real path, actuators recorded")
def test_http_saying_the_same_phrase_gets_no_deferred_keystroke(
    recorder, monkeypatch
) -> None:
    """The HTTP API has no turns and nobody to read a read-back to."""
    from grandpa.local import handle_local_action

    stub_capture(monkeypatch, [make_witness()])

    handle_local_action(PHRASE, deferred_origin="http")
    handle_local_action("yes", deferred_origin="http")

    assert _pending() == [], f"http staged a keystroke: {_pending()}"
    assert _keys_sent(recorder) == [], recorder.calls


def test_the_route_needs_no_test_only_mapping() -> None:
    """Stated directly, because it is the difference between this and last task.

    If the shipped tables stopped resolving the phrase, every test above would
    still pass by refusing things -- a suite that proves the route is shut while
    claiming to prove it is open. This one fails instead.
    """
    from grandpa.local.parsers import _normalise, _parse_automation_action
    from grandpa.natural_actions import request_for

    parsed = _parse_automation_action(_normalise(PHRASE))
    assert parsed.kind == "automation", parsed
    mapped = request_for(parsed.kind, parsed.target)

    assert mapped is not None, (
        f"{PHRASE!r} no longer resolves to a catalogued action, so the e2e tests "
        f"in this file are passing without exercising a route"
    )
    assert mapped[0] == ACTION, mapped
