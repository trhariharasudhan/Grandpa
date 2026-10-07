"""Does a held key actually reach a transcript? Verified, because it was not.

The reported symptom was a space in the text box and nothing else, and the key
problem could have been hiding a broken hold path behind it. So this drives the
whole chain with an injected probe -- poller, controller,
``PushToTalkSession.record_while_held``, the real stop event, the bridge -- and
asserts the state sequence a user would watch:

    idle -> recording -> transcribing -> thinking -> idle

Nothing real is opened: the probe is scripted, the capture is a double that
waits on the stop event the session sets, and the bridge is a double. The audio
guard and default-deny fixture stay armed.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

import pytest

from grandpa.cli.bubble_cmd import _hold_poller
from grandpa.ui.bubble import BubbleController, BubbleState

pytestmark = pytest.mark.core


@dataclass
class ScriptedProbe:
    """Down for *down_polls* reads, then up. Mirrors a real press and release."""

    down_polls: int = 3
    reads: int = 0

    def is_down(self, key: str) -> bool:
        self.reads += 1
        return self.reads <= self.down_polls


@dataclass
class WaitingCapture:
    """Returns only once the session's watcher sets the stop event.

    This is what proves the key release ends the recording rather than a timer:
    if the watcher never set it, this would time out and return False.
    """

    audio: Any = "captured"
    stop_observed: bool = False

    def capture(self, stop_event: threading.Event | None = None, **_kwargs):
        if stop_event is not None:
            self.stop_observed = stop_event.wait(timeout=5.0)
        return self.audio

    def close(self) -> None:
        pass


@dataclass
class Transcript:
    text: str = "what is the time"
    reason: str = ""
    explanation: str = ""


@dataclass
class Reply:
    text: str = "It is just past four."
    status: str = "ok"
    failed: bool = False


@dataclass
class Bridge:
    speech_ready: bool = True
    transcriber: Any = field(default_factory=lambda: type("T", (), {"model": "base.en"})())
    sent: list[str] = field(default_factory=list)
    transcribed: list[Any] = field(default_factory=list)

    def warm(self) -> tuple[bool, str]:
        self.speech_ready = True
        return True, "ready"

    def transcribe(self, audio: Any) -> Transcript:
        self.transcribed.append(audio)
        return Transcript()

    def send(self, text: str) -> Reply:
        self.sent.append(text)
        return Reply()


@dataclass
class RecordingView:
    states: list[str] = field(default_factory=list)
    status_lines: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
    transcripts: list[str] = field(default_factory=list)
    cleared: int = 0

    def show(self, *, position, topmost) -> None:
        pass

    def set_state(self, state: str, label: str) -> None:
        self.states.append(state)

    def set_status_line(self, text: str) -> None:
        self.status_lines.append(text)

    def set_reply(self, text: str) -> None:
        self.replies.append(text)

    def set_transcript(self, text: str) -> None:
        self.transcripts.append(text)

    def clear_entry(self) -> None:
        self.cleared += 1

    def position(self) -> tuple[int, int]:
        return (0, 0)

    def close(self) -> None:
        pass


def _advancing_clock(seconds: float):
    calls: list[int] = []

    def clock() -> float:
        calls.append(1)
        return 0.0 if len(calls) == 1 else seconds

    return clock


def _ready() -> tuple[BubbleController, RecordingView, Bridge, WaitingCapture]:
    view = RecordingView()
    bridge = Bridge()
    capture = WaitingCapture()
    controller = BubbleController(
        view=view,
        bridge=bridge,
        probe=ScriptedProbe(),
        capture=capture,
        sleep=lambda _s: None,
        clock=_advancing_clock(1.4),
    )
    controller.start()
    controller.warm()
    view.states.clear()
    return controller, view, bridge, capture


# --- the whole chain ---------------------------------------------------------------


def test_a_held_key_reaches_a_transcript_and_a_reply() -> None:
    controller, view, bridge, capture = _ready()

    transcript = controller.on_hold()

    assert transcript == "what is the time"
    assert bridge.transcribed == ["captured"], "the audio never reached transcribe"
    assert bridge.sent == ["what is the time"], "the transcript was never routed"
    assert view.replies[-1] == "It is just past four."


def test_the_state_sequence_is_what_a_user_would_watch() -> None:
    controller, view, _bridge, _capture = _ready()

    controller.on_hold()

    assert view.states == ["recording", "transcribing", "thinking", "idle"]


def test_the_release_is_what_ends_the_recording() -> None:
    """The stop event is set by the session's watcher when the key comes up.

    Without that, ``capture`` would block for its full timeout and report False.
    """
    controller, _view, _bridge, capture = _ready()

    controller.on_hold()

    assert capture.stop_observed is True


def test_the_probe_is_polled_until_the_key_comes_up() -> None:
    controller, _view, _bridge, _capture = _ready()
    probe = controller.probe

    controller.on_hold()

    assert probe.reads > 1, "the watcher read the key exactly once"


def test_it_returns_to_idle_so_a_second_hold_works() -> None:
    controller, view, bridge, _capture = _ready()

    controller.on_hold()
    assert controller.state is BubbleState.IDLE

    controller.probe = ScriptedProbe()
    controller.clock = _advancing_clock(1.1)
    controller.on_hold()

    assert len(bridge.sent) == 2
    assert controller.state is BubbleState.IDLE


# --- driven through the poller, as the running bubble does -------------------------


def test_the_poller_drives_the_whole_chain() -> None:
    """The wiring the running command uses, not just the controller."""
    controller, view, bridge, _capture = _ready()

    _hold_poller(controller)()

    assert bridge.sent == ["what is the time"]
    assert view.states == ["recording", "transcribing", "thinking", "idle"]


def test_the_poller_does_nothing_while_the_key_is_up() -> None:
    controller, view, bridge, _capture = _ready()
    controller.probe = ScriptedProbe(down_polls=0)

    _hold_poller(controller)()

    assert bridge.sent == []
    assert view.states == []


def test_a_tap_is_reported_and_not_routed() -> None:
    """Short holds now say what they were instead of recording silence."""
    controller, view, bridge, _capture = _ready()
    controller.clock = _advancing_clock(0.05)

    assert controller.on_hold() == ""
    assert bridge.sent == []
    assert "tap" in view.status_lines[-1]
    assert controller.state is BubbleState.IDLE


def test_the_status_line_after_a_successful_hold_carries_no_error() -> None:
    controller, view, _bridge, _capture = _ready()

    controller.on_hold()

    assert controller.last_error == ""
    assert "base.en" in view.status_lines[-1]
    assert "speech ready" in view.status_lines[-1]
