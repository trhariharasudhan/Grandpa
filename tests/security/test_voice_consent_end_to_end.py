"""Voice stages a keystroke; the window changes; nothing is typed.

The one test that would catch this whole tranche being wrong. Everything else
checks a tier, a wording or a counter in isolation; this drives the voice turn
loop the way a person does -- an utterance, then "yes" -- and watches the
actuators at the bottom of the stack.

Driven through ``VoiceCommandProcessor.handle_user_input``, so the turn counter
is incremented by the same wrapper that does it in production rather than by the
test. A turn that does not count itself would make the expiry untestable.

Two things are deliberate about the setup:

* **The actuator is recorded, not live.** ``input_recorder.install`` replaces
  every input primitive before anything runs, so the happy path proves a keystroke
  *reached* an actuator without one reaching the machine. The fixture asserts the
  replacement held.
* **The phrase is mapped for the test only.** ``("automation", "hotkey|ctrl+c")``
  is the shape the real parser already produces for "copy selected text" -- the
  trace is in the report -- but no product mapping turns it into a catalogued
  action yet. Mapping it here exercises the consent path end to end without
  shipping a route. This is also why the voice tranche guard still passes: it
  runs against the unmapped product, where Screen Automation V2 refuses first.

The audio guard stays armed throughout. Nothing here opens a microphone or
speaks: the read-back is returned as text and asserted as text.
"""

from __future__ import annotations

import pytest

from grandpa import pc_control
from grandpa.desktop.kernel import approvals
from tests.security.input_recorder import install
from tests.witness_support import make_witness, stub_capture

PHRASE = "copy selected text"
ACTION = "keyboard_hotkey"
PARAMETERS = {"keys": ["ctrl", "c"]}


@pytest.fixture
def recorder(monkeypatch, tmp_path):
    import grandpa.desktop.control.automation as automation

    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    monkeypatch.setattr(automation, "_last_action_at", 0.0)
    return install(monkeypatch)


@pytest.fixture
def voice(monkeypatch):
    """VoiceRuntime's route -- the one voice entry point that reaches the layer.

    Not ``VoiceCommandProcessor``: every input phrase there is taken by Screen
    Automation V2, which answers "This input action needs a target window" and
    never consults the action layer. The runtime's route does reach it, with a
    target pinned. Both are traced in the report; this is the one under test
    because it is the one the consent path is on.
    """
    import grandpa.natural_actions as natural_actions
    import grandpa.voice.session as session

    monkeypatch.setitem(
        natural_actions.MIGRATED,
        ("automation", "hotkey|ctrl+c"),
        (ACTION, PARAMETERS),
    )
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
    assert "did not send any keys" in answered, answered
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
