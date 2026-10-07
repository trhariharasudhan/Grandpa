"""The bubble's behaviour, with no window, no microphone and no speaker.

The view is injected, as ``HighlightOverlay`` injects its renderer, so the whole
controller runs against a recorder. The audio guard and the default-deny fixture
stay armed throughout.

The assertion this file exists for is the LOADING state. ``grandpa voice
accuracy-test`` showed a surface that looked ready while 145 MB of model
downloaded during the first prompt, and measured the user's answer against a
transcriber that did not exist yet. A bubble that says "Ready" while the model
loads is the same bug behind a window, so it is pinned here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from grandpa.ui.bubble import (
    DEFAULT_POSITION,
    STATES_THAT_REFUSE_A_HOLD,
    BubbleController,
    BubbleState,
    load_position,
    position_file,
    save_position,
)

pytestmark = pytest.mark.core


# --- doubles ----------------------------------------------------------------------


@dataclass
class FakeView:
    states: list[tuple[str, str]] = field(default_factory=list)
    status_lines: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
    transcripts: list[str] = field(default_factory=list)
    cleared: int = 0
    shown: list[dict] = field(default_factory=list)
    closed: int = 0
    at: tuple[int, int] = (111, 222)

    def show(self, *, position, topmost) -> None:
        self.shown.append({"position": position, "topmost": topmost})

    def set_state(self, state: str, label: str) -> None:
        self.states.append((state, label))

    def set_status_line(self, text: str) -> None:
        self.status_lines.append(text)

    def set_reply(self, text: str) -> None:
        self.replies.append(text)

    def set_transcript(self, text: str) -> None:
        self.transcripts.append(text)

    def clear_entry(self) -> None:
        self.cleared += 1

    def position(self) -> tuple[int, int]:
        return self.at

    def close(self) -> None:
        self.closed += 1


@dataclass
class FakeReply:
    text: str
    status: str = "ok"
    failed: bool = False


@dataclass
class FakeTranscript:
    text: str
    reason: str = ""
    explanation: str = "nothing recognisable was in it"


@dataclass
class FakeBridge:
    reply: FakeReply = field(default_factory=lambda: FakeReply("Opening Notepad."))
    transcript: FakeTranscript = field(
        default_factory=lambda: FakeTranscript("open notepad")
    )
    warm_result: tuple[bool, str] = (True, "ready")
    sent: list[str] = field(default_factory=list)
    transcribed: list[Any] = field(default_factory=list)
    warmed: int = 0
    speech_ready: bool = False
    transcriber: Any = None

    def warm(self) -> tuple[bool, str]:
        self.warmed += 1
        self.speech_ready = self.warm_result[0]
        return self.warm_result

    def send(self, text: str) -> FakeReply:
        self.sent.append(text)
        return self.reply

    def transcribe(self, audio: Any) -> FakeTranscript:
        self.transcribed.append(audio)
        return self.transcript


class FakeProbe:
    def __init__(self, downs: list[bool] | None = None) -> None:
        self.script = list(downs if downs is not None else [True, False])

    def is_down(self, key: str) -> bool:
        return self.script.pop(0) if self.script else False


@dataclass
class FakeCapture:
    audio: Any = "captured-audio"
    stop_was_set: bool = False

    def capture(self, stop_event=None, on_speech_start=None):
        if stop_event is not None:
            self.stop_was_set = stop_event.wait(timeout=5.0)
        return self.audio

    def close(self) -> None:
        pass


def _held_for(seconds: float):
    """A clock reading 0.0 once, then *seconds* forever.

    The hold's watcher thread calls the clock an unpredictable number of times,
    so a scripted list is consumed non-deterministically. This is stable
    whatever order the two threads interleave in.
    """
    calls: list[int] = []

    def clock() -> float:
        calls.append(1)
        return 0.0 if len(calls) == 1 else seconds

    return clock


def _controller(**overrides) -> tuple[BubbleController, FakeView, FakeBridge]:
    view = overrides.pop("view", None) or FakeView()
    bridge = overrides.pop("bridge", None) or FakeBridge()
    parts = {
        "probe": FakeProbe(),
        "capture": FakeCapture(),
        "sleep": lambda _seconds: None,
        # Advances, because record_while_held measures the hold and the
        # controller now refuses anything under minimum_hold_seconds. A fixed
        # clock makes every hold a 0.00s tap.
        "clock": _held_for(1.5),

    }
    parts.update(overrides)
    return BubbleController(view=view, bridge=bridge, **parts), view, bridge


# --- 1. model readiness: the bug this file exists for -----------------------------


def test_it_starts_in_loading_not_idle() -> None:
    """The window appears immediately, and says the model is not ready."""
    controller, view, _bridge = _controller()

    controller.start()

    assert controller.state is BubbleState.LOADING
    assert view.states[0][0] == "loading"
    assert "Loading" in view.states[0][1]


def test_the_status_line_says_loading_before_the_model_is_warm() -> None:
    controller, view, _bridge = _controller()

    controller.start()

    assert "loading" in view.status_lines[-1]
    assert "speech ready" not in view.status_lines[-1]


def test_a_hold_during_loading_records_nothing() -> None:
    """Recording into a transcriber that does not exist yet is the live bug."""
    controller, view, bridge = _controller()
    controller.start()

    transcript = controller.on_hold()

    assert transcript == ""
    assert bridge.transcribed == [], "it recorded while the model was loading"
    assert controller.capture.stop_was_set is False
    assert "still loading" in view.status_lines[-1]


def test_loading_is_in_the_set_that_refuses_a_hold() -> None:
    """Stated as data, so a new state has to decide."""
    assert BubbleState.LOADING in STATES_THAT_REFUSE_A_HOLD
    assert BubbleState.IDLE not in STATES_THAT_REFUSE_A_HOLD


def test_it_reaches_idle_only_after_warming() -> None:
    controller, view, bridge = _controller()
    controller.start()

    assert controller.state is BubbleState.LOADING
    controller.warm()

    assert bridge.warmed == 1
    assert controller.state is BubbleState.IDLE
    assert "speech ready" in view.status_lines[-1]


def test_a_failed_warm_says_so_and_does_not_claim_ready() -> None:
    bridge = FakeBridge(warm_result=(False, "model not found"))
    controller, view, _ = _controller(bridge=bridge)
    controller.start()

    assert controller.warm() is False
    assert controller.state is BubbleState.ERROR
    assert "model not found" in view.status_lines[-1]
    assert "speech ready" not in view.status_lines[-1]


# --- 2. the hold ------------------------------------------------------------------


def test_a_hold_records_transcribes_and_routes() -> None:
    controller, view, bridge = _controller()
    controller.start()
    controller.warm()

    transcript = controller.on_hold()

    assert transcript == "open notepad"
    assert bridge.transcribed == ["captured-audio"]
    assert bridge.sent == ["open notepad"]
    assert view.transcripts[-1] == "open notepad"
    assert view.replies[-1] == "Opening Notepad."
    assert controller.state is BubbleState.IDLE


def test_the_capture_is_stopped_by_the_key_coming_up() -> None:
    controller, _view, _bridge = _controller(probe=FakeProbe([True, True, False]))
    controller.start()
    controller.warm()

    controller.on_hold()

    assert controller.capture.stop_was_set is True


def test_the_states_pass_through_recording_and_transcribing() -> None:
    controller, view, _bridge = _controller()
    controller.start()
    controller.warm()
    view.states.clear()

    controller.on_hold()

    seen = [state for state, _label in view.states]
    assert seen[:3] == ["recording", "transcribing", "thinking"]
    assert seen[-1] == "idle"


def test_an_empty_transcript_is_not_routed() -> None:
    """Nothing recognisable is not a command, and must not be read as one."""
    bridge = FakeBridge(transcript=FakeTranscript("", reason="no_segments"))
    controller, view, _ = _controller(bridge=bridge)
    controller.start()
    controller.warm()

    assert controller.on_hold() == ""
    assert bridge.sent == []
    assert "nothing usable" in view.status_lines[-1]
    assert controller.state is BubbleState.IDLE


def test_a_capture_that_raises_does_not_kill_the_bubble() -> None:
    class Exploding:
        def capture(self, stop_event=None, on_speech_start=None):
            raise RuntimeError("device vanished")

        def close(self) -> None:
            pass

    controller, view, _bridge = _controller(capture=Exploding())
    controller.start()
    controller.warm()

    assert controller.on_hold() == ""
    assert controller.state is BubbleState.ERROR
    assert "device vanished" in view.status_lines[-1]


def test_a_hold_without_a_probe_refuses_rather_than_crashing() -> None:
    controller, view, _bridge = _controller(probe=None)
    controller.start()
    controller.warm()

    assert controller.on_hold() == ""
    assert "no microphone capture" in view.status_lines[-1]
    assert "F9" in view.status_lines[-1], "the message should name the key seen"


# --- 3. the text box ---------------------------------------------------------------


def test_submitting_text_routes_it_and_shows_the_reply() -> None:
    controller, view, bridge = _controller()
    controller.start()
    controller.warm()

    reply = controller.submit("what is the time")

    assert bridge.sent == ["what is the time"]
    assert reply == "Opening Notepad."
    assert view.replies[-1] == "Opening Notepad."
    assert view.cleared == 1


def test_an_empty_submission_does_nothing() -> None:
    controller, view, bridge = _controller()
    controller.start()
    controller.warm()

    assert controller.submit("   ") == ""
    assert bridge.sent == []
    assert view.cleared == 0


def test_a_failed_reply_is_shown_and_the_state_says_error() -> None:
    bridge = FakeBridge(reply=FakeReply("I cannot do that.", failed=True))
    controller, view, _ = _controller(bridge=bridge)
    controller.start()
    controller.warm()

    controller.submit("delete everything")

    assert controller.state is BubbleState.ERROR
    assert view.replies[-1] == "I cannot do that."
    assert "I cannot do that." in view.status_lines[-1]


def test_a_successful_reply_clears_the_previous_error() -> None:
    controller, view, bridge = _controller()
    controller.start()
    controller.warm()
    bridge.reply = FakeReply("nope", failed=True)
    controller.submit("bad")
    assert controller.last_error

    bridge.reply = FakeReply("fine")
    controller.submit("good")

    assert controller.last_error == ""
    assert controller.state is BubbleState.IDLE


# --- 4. position ------------------------------------------------------------------


def test_it_opens_at_the_remembered_position(tmp_path: Path) -> None:
    store = tmp_path / "pos.json"
    save_position((815, 442), store)

    controller, view, _bridge = _controller()
    controller.start(position_path=store)

    assert view.shown[0]["position"] == (815, 442)
    assert view.shown[0]["topmost"] is True


def test_a_missing_file_gives_the_default(tmp_path: Path) -> None:
    assert load_position(tmp_path / "absent.json") == DEFAULT_POSITION


def test_a_corrupt_file_gives_the_default_rather_than_raising(tmp_path: Path) -> None:
    store = tmp_path / "pos.json"
    store.write_text("{not json", encoding="utf-8")

    assert load_position(store) == DEFAULT_POSITION


def test_closing_remembers_where_the_window_was(tmp_path: Path) -> None:
    store = tmp_path / "pos.json"
    controller, view, _bridge = _controller()
    controller.start(position_path=store)
    view.at = (640, 480)

    controller.stop()

    assert load_position(store) == (640, 480)
    assert view.closed == 1


def test_an_unwritable_position_file_does_not_stop_it_closing(
    tmp_path: Path,
) -> None:
    store = tmp_path / "nope" / "deep"  # a directory where a file must go
    store.mkdir(parents=True)

    controller, view, _bridge = _controller()
    controller.start(position_path=store)

    controller.stop()

    assert view.closed == 1


def test_the_position_file_resolves_at_call_time(monkeypatch, tmp_path: Path) -> None:
    """A module-level default computed from GRANDPA_HOME points at a real home."""
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "elsewhere"))

    assert str(tmp_path / "elsewhere") in str(position_file())


# --- 5. the status line ------------------------------------------------------------


def test_the_status_line_carries_model_speech_and_error() -> None:
    bridge = FakeBridge(reply=FakeReply("no", failed=True))
    bridge.transcriber = type("T", (), {"model": "base.en"})()
    controller, view, _ = _controller(bridge=bridge)
    controller.start()
    controller.warm()
    controller.submit("something")

    line = view.status_lines[-1]
    assert "base.en" in line
    assert "speech ready" in line
    assert "no" in line


def test_the_status_line_is_readable_without_an_error() -> None:
    bridge = FakeBridge()
    bridge.transcriber = type("T", (), {"model": "small.en"})()
    controller, view, _ = _controller(bridge=bridge)
    controller.start()
    controller.warm()

    line = view.status_lines[-1]
    assert line.startswith("small.en")
    assert line.count("|") == 1, line


def test_an_unknown_model_says_so_rather_than_showing_nothing() -> None:
    controller, view, _bridge = _controller()
    controller.start()
    controller.warm()

    assert "model unknown" in view.status_lines[-1]


# --- 6. the hold is the production one, not a copy -------------------------------


def test_the_hold_delegates_to_push_to_talk_session() -> None:
    """Reused, not reimplemented.

    An earlier version of this controller copied record_while_held and silently
    dropped its stuck-key cap. Delegation is asserted so the copy cannot return.
    """
    import inspect

    from grandpa.ui import bubble as bubble_module

    source = inspect.getsource(bubble_module.BubbleController._record_while_held)

    assert "record_while_held()" in source
    assert "threading.Event" not in source, "the watcher belongs to the session"


def test_the_session_it_builds_carries_this_controllers_collaborators() -> None:
    controller, _view, _bridge = _controller()

    session = controller._hold_session()

    assert session.capture is controller.capture
    assert session.probe is controller.probe
    assert session.key == controller.key
    assert session.maximum_seconds >= 30.0, "the stuck-key cap must survive"


def test_run_once_is_never_called() -> None:
    """It owns a blocking loop that prints, so the view could not be updated.

    Checked as a call rather than as a mention, because the docstring explaining
    why it is avoided names it -- and a test that forbids the explanation of a
    decision is a test against documenting decisions.
    """
    import inspect

    from grandpa.ui import bubble as bubble_module

    code = "".join(
        line.split("#")[0]
        for line in inspect.getsource(bubble_module).splitlines()
    )

    assert "run_once(" not in code
    assert ".run_once" not in code
