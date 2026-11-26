""""Hey Grandpa" on the orb: when it listens, what it routes, the toggle."""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.ui import wake_talk
from grandpa.ui.avatar_window import WindowApi
from grandpa.ui.wake_talk import WakeToTalk, strip_wake

WEB = Path(__file__).resolve().parents[2] / "src" / "grandpa" / "ui" / "avatar_web"


class Controller:
    def __init__(self) -> None:
        self.busy = False
        self.routed: list = []

    def talk(self, listener):
        self.routed.append(listener())
        return True


class Listener:
    def __init__(self) -> None:
        self.started = self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class Transcript:
    def __init__(self, text: str) -> None:
        self.text = text


class Bridge:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def transcribe(self, _audio):
        return Transcript(self.text)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))
    return tmp_path


def make(*, said_next="open notepad", bridge_text="", enabled=True):
    controller = Controller()
    listener = Listener()
    made: dict = {}

    def engine_factory(on_model, on_spoken, gate):
        made.update(on_model=on_model, on_spoken=on_spoken, gate=gate)

        class Engine:
            label = "test engine"

        return Engine()

    clock = Clock()
    wake = WakeToTalk(
        controller,
        Bridge(bridge_text),
        lambda: Transcript(said_next),
        enabled=enabled,
        engine_factory=engine_factory,
        listener_factory=lambda engine, on_event: listener,
        clock=clock,
        spawn=lambda job: job(),
        chime=lambda: None,
    )
    return wake, controller, listener, made, clock


class Match:
    def __init__(self, rest: int) -> None:
        self.rest = rest


def test_a_wake_alone_listens_for_the_next_sentence() -> None:
    wake, controller, listener, made, _ = make(said_next="Hey Grandpa, open Notepad")
    assert wake.start() and listener.started == 1 and wake.label == "test engine"
    made["on_spoken"]([0] * 1600, Match(0))
    assert controller.routed == ["open Notepad"]


def test_words_said_with_the_wake_are_used_directly() -> None:
    wake, controller, _l, made, _ = make(bridge_text="Hey Grandpa, what time is it?")
    wake.start()
    np = pytest.importorskip("numpy")
    made["on_spoken"](np.zeros(1600, dtype=np.int16), Match(4))
    assert controller.routed == ["what time is it?"]


def test_silence_after_the_wake_is_a_quiet_return() -> None:
    wake, controller, _l, made, _ = make(said_next="")
    wake.start()
    made["on_model"]()
    assert controller.routed == [None]


def test_it_does_not_listen_while_busy_or_just_after() -> None:
    wake, controller, _l, made, clock = make()
    wake.start()
    gate = made["gate"]
    assert gate()
    controller.busy = True
    assert not gate()
    controller.busy = False
    assert not gate()  # Grandpa's own last words may still be in the air
    clock.now += wake_talk.AFTER_BUSY_SECONDS + 0.1
    assert gate()


def test_the_toggle_closes_the_mic_and_is_remembered(home) -> None:
    wake, _c, listener, made, _ = make()
    wake.start()
    wake.set_enabled(False)
    assert listener.stopped == 1 and not wake.running and not made["gate"]()
    assert wake_talk.load_wake_enabled() is False
    wake.set_enabled(True)
    assert wake.running and wake_talk.load_wake_enabled() is True


def test_no_microphone_is_reported_not_raised() -> None:
    def broken(*_a):
        raise OSError("No input device\nmore")

    wake = WakeToTalk(Controller(), Bridge(), lambda: "", engine_factory=broken, chime=lambda: None)
    assert wake.start() is False and wake.error == "No input device"


def test_the_window_api_shows_and_switches_it() -> None:
    wake, *_ = make()
    wake.start()
    api = WindowApi(wake)
    assert api.wake_status() == {"available": True, "on": True, "label": "test engine", "error": ""}
    assert api.set_wake(False)["on"] is False
    assert api.set_wake("yes")["on"] is False  # only a real boolean
    assert WindowApi().wake_status()["available"] is False
    assert "_wake" not in [n for n in dir(api) if not n.startswith("_")]


def test_phrase_is_stripped_from_the_command() -> None:
    assert strip_wake("Hey Grandpa, open Notepad") == "open Notepad"
    assert strip_wake("Grandpa what time is it") == "what time is it"
    assert strip_wake("open notepad") == "open notepad"


def test_the_panel_has_no_mic_button() -> None:
    """Captain asked for it gone; listening stays on (``--no-wake`` turns it off)."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "avatar.js").read_text(encoding="utf-8")
    assert 'id="wake"' not in html and "set_wake(" not in js


def test_after_a_question_the_answer_needs_no_second_wake() -> None:
    from grandpa.ui.avatar_controller import StateMessage
    from grandpa.ui.avatar_states import AvatarState

    heard = iter([Transcript("close notepad"), Transcript("seri")])

    class Asking(Controller):
        def talk(self, listener):
            said = listener()
            self.routed.append(said)
            ask = said == "close notepad"
            self.state = StateMessage(AvatarState.CONFIRM if ask else AvatarState.IDLE)
            return True

    controller = Asking()
    wake = WakeToTalk(
        controller,
        Bridge(),
        lambda: next(heard),
        engine_factory=lambda *a: type("E", (), {"label": "x"})(),
        listener_factory=lambda e, cb: Listener(),
        spawn=lambda job: job(),
        chime=lambda: None,
    )
    wake._wake(None)
    assert controller.routed == ["close notepad", "seri"]
