"""A6: expressions per state, click-to-talk, and the tray toggle.

Click-to-talk is tested through the real socket and a fake listener, so no
microphone opens: the point is that a spoken line goes the same way as a typed
one (same bridge, same confirmation) and that ``{"type": "talk"}`` carries
nothing. The tray is driven with a fake pystray module and a fake window. The
page's expressions are checked as written; they were rendered in headless
Chromium for the PR, and WebView2 is Captain's to see.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import pytest

from grandpa.cli.avatar_cmd import build, microphone_listener
from grandpa.ui.avatar_controller import (
    NO_MICROPHONE,
    NOTHING_HEARD,
    AvatarController,
)
from grandpa.ui.avatar_states import (
    AvatarState,
    ChatMessage,
    StateMessage,
    parse_inbound,
)
from grandpa.ui.avatar_window import WEB_DIR, AvatarTray, run_window, start_tray
from grandpa.ui.bridge import BridgeTranscript

pytestmark = pytest.mark.core


@dataclass
class Reply:
    text: str = "ok"
    status: str = "ok"
    failed: bool = False
    kind: str | None = None


class FakeBridge:
    def __init__(self, *replies: Reply):
        self.replies = list(replies)
        self.sent: list[str] = []
        self.heard: list = []

    def send(self, text: str) -> Reply:
        self.sent.append(text)
        return self.replies.pop(0) if self.replies else Reply()

    def transcribe(self, audio) -> BridgeTranscript:
        self.heard.append(audio)
        return BridgeTranscript(text="set volume to 30")


def _states(published) -> list[str]:
    return [str(m.state) for m in published if isinstance(m, StateMessage)]


def _lines(published) -> list[tuple[str, str]]:
    return [(m.role, m.text) for m in published if isinstance(m, ChatMessage)]


# --- the inbound message --------------------------------------------------------


def test_talk_is_accepted_and_carries_nothing() -> None:
    assert parse_inbound(json.dumps({"type": "talk"})) == ("talk", "")


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "talk", "text": "delete everything"},
        {"type": "talk", "action": "system_shutdown"},
        {"type": "Talk"},
    ],
)
def test_a_talk_with_anything_extra_is_dropped(raw) -> None:
    assert parse_inbound(json.dumps(raw)) is None


# --- the controller -------------------------------------------------------------


def test_a_spoken_line_is_routed_exactly_like_a_typed_one() -> None:
    published: list = []
    bridge = FakeBridge(Reply("Volume set to 30.", kind="automation"))
    controller = AvatarController(
        bridge=bridge, publish=published.append, listener=lambda: "set volume to 30"
    )

    assert controller.talk() is True

    assert bridge.sent == ["set volume to 30"]
    assert _states(published)[:2] == ["listening", "thinking"]
    assert ("user", "set volume to 30") in _lines(published)
    assert not controller.busy


def test_a_spoken_risky_request_still_asks_first() -> None:
    published: list = []
    bridge = FakeBridge(
        Reply("Lock the screen now? Say yes or no.", status="requires_confirmation")
    )
    controller = AvatarController(
        bridge=bridge, publish=published.append, listener=lambda: "lock the screen"
    )

    controller.talk()

    assert controller.state.state is AvatarState.CONFIRM
    assert controller.state.question.startswith("Lock the screen")
    assert bridge.sent == ["lock the screen"]  # asked, not done


def test_a_transcript_object_is_read_for_its_words() -> None:
    bridge = FakeBridge()
    controller = AvatarController(
        bridge=bridge,
        publish=lambda _m: None,
        listener=lambda: BridgeTranscript(text="  what time is it "),
    )
    controller.talk()
    assert bridge.sent == ["what time is it"]


@pytest.mark.parametrize(
    "heard", ["", "   ", BridgeTranscript(text="", reason="silence")]
)
def test_nothing_heard_is_said_and_nothing_is_routed(heard) -> None:
    published: list = []
    bridge = FakeBridge()
    controller = AvatarController(
        bridge=bridge, publish=published.append, listener=lambda: heard
    )

    controller.talk()

    assert bridge.sent == []
    assert ("grandpa", NOTHING_HEARD) in _lines(published)
    assert _states(published) == ["listening", "idle"]


def test_a_failing_microphone_is_an_error_not_a_crash() -> None:
    published: list = []

    def broken():
        raise RuntimeError("No microphone found.\ndetail")

    bridge = FakeBridge()
    controller = AvatarController(
        bridge=bridge, publish=published.append, listener=broken
    )

    assert controller.talk() is True

    assert bridge.sent == []
    assert _states(published) == ["listening", "error"]
    assert _lines(published)[-1] == (
        "grandpa",
        "I could not use the microphone: No microphone found.",
    )
    assert not controller.busy


def test_without_a_microphone_talk_says_so() -> None:
    published: list = []
    controller = AvatarController(bridge=FakeBridge(), publish=published.append)
    assert controller.talk() is False
    assert _lines(published) == [("grandpa", NO_MICROPHONE)]
    assert _states(published) == []


def test_talk_waits_for_a_request_in_flight() -> None:
    heard: list = []
    controller = AvatarController(
        bridge=FakeBridge(), publish=lambda _m: None, listener=lambda: heard.append(1)
    )
    controller._busy = True
    assert controller.talk() is False
    assert heard == []


# --- the microphone listener ----------------------------------------------------


class FakeCapture:
    def __init__(self, speech: bool = True):
        self.speech = speech
        self.closed = False

    def capture(self):
        return type("Audio", (), {"speech_detected": self.speech})()

    def close(self):
        self.closed = True


def test_the_listener_records_once_transcribes_and_closes_the_mic() -> None:
    bridge = FakeBridge()
    capture = FakeCapture()
    listen = microphone_listener(bridge, capture_factory=lambda: capture)

    heard = listen()

    assert heard.text == "set volume to 30"
    assert len(bridge.heard) == 1
    assert capture.closed


def test_silence_is_not_sent_to_the_transcriber() -> None:
    bridge = FakeBridge()
    capture = FakeCapture(speech=False)
    listen = microphone_listener(bridge, capture_factory=lambda: capture)
    assert listen() == ""
    assert bridge.heard == []
    assert capture.closed


# --- the real socket ------------------------------------------------------------

websockets = pytest.importorskip("websockets")


def _recv_until(ws, predicate, timeout: float = 5.0) -> list[dict]:
    seen: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = json.loads(ws.recv(timeout=deadline - time.monotonic()))
        seen.append(data)
        if predicate(data):
            return seen
    raise AssertionError(f"never saw it; got {seen}")


def test_a_page_clicks_talk_and_the_heard_line_is_answered() -> None:
    from websockets.sync.client import connect

    bridge = FakeBridge(Reply("Volume set to 30.", kind="automation"))
    controller, server = build(bridge, listener=lambda: "set volume to 30")
    server.start()
    try:
        with connect(server.url, open_timeout=3) as ws:
            json.loads(ws.recv(timeout=3))  # the snapshot's idle
            ws.send(json.dumps({"type": "talk", "text": "rm -rf"}))  # dropped
            ws.send(json.dumps({"type": "talk"}))
            seen = _recv_until(
                ws,
                lambda d: d.get("type") == "state" and d["state"] in {"done", "idle"},
            )
    finally:
        server.stop()

    assert bridge.sent == ["set volume to 30"]
    states = [d["state"] for d in seen if d["type"] == "state"]
    assert states[:2] == ["listening", "thinking"]


# --- the tray -------------------------------------------------------------------


class FakeWindow:
    def __init__(self):
        self.calls: list[str] = []

    def hide(self):
        self.calls.append("hide")

    def show(self):
        self.calls.append("show")

    def destroy(self):
        self.calls.append("destroy")


class FakePystray:
    class MenuItem:
        def __init__(self, text, action, default=False):
            self.text, self.action, self.default = text, action, default

    class Menu:
        def __init__(self, *items):
            self.items = items

    class Icon:
        last = None

        def __init__(self, name, icon=None, title="", menu=None):
            self.name, self.title, self.menu = name, title, menu
            self.running = False
            self.updates = 0
            FakePystray.Icon.last = self

        def run_detached(self):
            self.running = True

        def stop(self):
            self.running = False

        def update_menu(self):
            self.updates += 1


def test_the_tray_click_hides_then_shows_the_window() -> None:
    window = FakeWindow()
    tray = AvatarTray(window, FakePystray, image=object())
    tray.start()
    icon = FakePystray.Icon.last
    toggle, quit_item = icon.menu.items

    assert toggle.default  # a left-click on the icon toggles
    assert toggle.text() == "Hide Grandpa"
    toggle.action()
    assert window.calls == ["hide"] and toggle.text() == "Show Grandpa"
    toggle.action()
    assert window.calls == ["hide", "show"] and toggle.text() == "Hide Grandpa"
    assert icon.updates == 2

    quit_item.action()
    assert window.calls[-1] == "destroy"
    assert not icon.running


def test_the_tray_only_shows_hides_and_quits() -> None:
    public = {n for n in dir(AvatarTray) if not n.startswith("_")}
    assert public == {"toggle", "quit", "label", "menu", "start", "stop"}


def test_without_pystray_there_is_no_tray_and_the_window_still_opens(
    monkeypatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def no_pystray(name, *args, **kwargs):
        if name == "pystray":
            raise ImportError("no pystray")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pystray)
    assert start_tray(FakeWindow()) is None


def test_run_window_starts_and_stops_the_tray(monkeypatch) -> None:
    import grandpa.ui.avatar_window as avatar_window

    monkeypatch.setattr(
        avatar_window.AvatarTray,
        "start",
        lambda self: setattr(self, "icon", FakePystray.Icon("t", menu=self.menu())),
    )

    class Hook:
        def __iadd__(self, _handler):
            return self

    window = FakeWindow()
    window.events = type("E", (), {"loaded": Hook()})()
    lines: list[str] = []

    class FakeWebview:
        @staticmethod
        def create_window(*_args, **_kwargs):
            return window

        @staticmethod
        def start(**_kwargs):
            assert FakePystray.Icon.last is not None

    run_window(
        "ws://127.0.0.1:1/avatar?token=t",
        tray=True,
        echo=lines.append,
        webview_module=FakeWebview,
        pystray_module=FakePystray,
    )
    assert lines == ["Tray: click the Grandpa icon to show or hide him."]


# --- the page -------------------------------------------------------------------

CHARACTER = (WEB_DIR / "character.js").read_text(encoding="utf-8")
AVATAR = (WEB_DIR / "avatar.js").read_text(encoding="utf-8")
INDEX_HTML = (WEB_DIR / "index.html").read_text(encoding="utf-8")


def test_every_state_has_an_expression() -> None:
    block = re.search(r"const EXPRESSION = \{(.*?)\n\};", CHARACTER, re.S).group(1)
    named = set(re.findall(r"^\s*(\w+):\s*\{", block, re.M))
    assert named == {str(s) for s in AvatarState}
    for line in re.findall(r"\{ smile: [^}]+\}", block):
        values = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", line)]
        smile, think, brows = values
        assert 0 <= smile <= 1 and 0 <= think <= 1 and -1 <= brows <= 1


def test_he_smiles_when_speaking_and_looks_thoughtful_when_thinking() -> None:
    def face(state: str) -> list[float]:
        line = re.search(rf"^\s*{state}:\s*(\{{[^}}]+\}})", CHARACTER, re.M).group(1)
        return [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", line)]

    assert face("speaking")[0] > face("thinking")[0]
    assert face("thinking")[1] == max(face(s)[1] for s in map(str, AvatarState))
    assert face("confirm")[2] == max(face(s)[2] for s in map(str, AvatarState))


def test_both_characters_have_a_face_and_a_glb_uses_its_shape_keys() -> None:
    assert CHARACTER.count("setExpression(face)") >= 3  # placeholder, .glb, the call
    assert '=== "smile"' in CHARACTER and '=== "think"' in CHARACTER
    assert "expressFace();" in CHARACTER


def test_the_page_has_a_talk_button_that_sends_only_talk() -> None:
    assert 'id="talk"' in INDEX_HTML
    sent = re.findall(r"socket\.send\(JSON\.stringify\((\{[^)]*\})\)\)", AVATAR)
    assert '{ type: "talk" }' in sent
    assert all("talk" not in s or s == '{ type: "talk" }' for s in sent)


def test_a_right_click_talks_and_never_toggles_the_panel() -> None:
    assert 'addEventListener("contextmenu"' in AVATAR
    assert "if (event.button !== 0) return;" in AVATAR
    assert "if (!press) return;" in AVATAR
