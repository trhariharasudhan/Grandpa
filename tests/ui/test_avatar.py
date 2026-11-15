"""A1: `grandpa avatar` -- states, the socket, and the page contract.

The controller is driven with a fake bridge, so no model and no action runs.
The server is real (websockets on 127.0.0.1) because the token check and the
inbound filter are the security of this window and a mock would prove nothing.
The window itself (pywebview / WebView2) is Windows-only and is exercised by
substitution: a fake ``webview`` module records what would have been opened.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from grandpa.core.events import EventBus, EventType
from grandpa.ui.avatar_controller import AvatarController, state_for_reply
from grandpa.ui.avatar_states import (
    MAX_INBOUND_TEXT,
    STATE_COLOURS,
    AvatarState,
    ChatMessage,
    StateMessage,
    encode,
    parse_inbound,
)
from grandpa.ui.avatar_window import INDEX, WEB_DIR, connect_script, run_window

pytestmark = pytest.mark.core


@dataclass
class Reply:
    text: str = "ok"
    status: str = "ok"
    failed: bool = False
    kind: str | None = None


class FakeBridge:
    def __init__(self, *replies: Reply, during=None):
        self.replies = list(replies)
        self.sent: list[str] = []
        self.during = during

    def send(self, text: str) -> Reply:
        self.sent.append(text)
        if self.during is not None:
            self.during()
        return self.replies.pop(0) if self.replies else Reply()

    def transcribe(self, audio):  # pragma: no cover - not used by the avatar
        raise NotImplementedError


def _states(published) -> list[str]:
    return [str(m.state) for m in published if isinstance(m, StateMessage)]


# --- the state contract -------------------------------------------------------


def test_the_eight_states_from_the_spec() -> None:
    assert {str(s) for s in AvatarState} == {
        "idle",
        "listening",
        "thinking",
        "speaking",
        "working",
        "done",
        "error",
        "confirm",
    }


def test_every_state_has_a_colour_from_the_bubble_palette() -> None:
    from grandpa.ui import palette

    assert set(STATE_COLOURS) == set(AvatarState)
    assert STATE_COLOURS[AvatarState.ERROR] == palette.RED_ERROR
    assert STATE_COLOURS[AvatarState.WORKING] == palette.PURPLE_EXECUTING


def test_a_state_message_is_self_describing_json() -> None:
    data = json.loads(encode(StateMessage(AvatarState.WORKING, action="volume_set")))
    assert data["type"] == "state"
    assert data["state"] == "working"
    assert data["action"] == "volume_set"
    assert data["label"] == "Working..."
    assert data["colour"].startswith("#")


@pytest.mark.parametrize(
    ("reply", "state"),
    [
        (Reply("Lock the screen?", status="requires_confirmation"), "confirm"),
        (Reply("Lock the screen?", status="needs_confirmation"), "confirm"),
        (Reply("No.", status="blocked", failed=True), "error"),
        (Reply("Volume is 30.", status="handled", kind="pc_control"), "done"),
        (Reply("Hello!", status="ok", kind="assistant"), "idle"),
    ],
)
def test_the_resting_state_comes_from_the_status_not_the_words(reply, state) -> None:
    assert str(state_for_reply(reply).state) == state


# --- the controller -----------------------------------------------------------


def test_a_request_goes_thinking_then_rests_and_both_lines_are_shown() -> None:
    published: list = []
    controller = AvatarController(FakeBridge(Reply("It is 10:52.")), published.append)

    assert controller.submit("what time is it") is True

    assert _states(published) == ["thinking", "idle"]
    chat = [(m.role, m.text) for m in published if isinstance(m, ChatMessage)]
    assert chat == [("user", "what time is it"), ("grandpa", "It is 10:52.")]


def test_a_confirmation_shows_the_question_and_yes_is_just_text() -> None:
    published: list = []
    bridge = FakeBridge(
        Reply("Lock the screen now?", status="requires_confirmation"),
        Reply("Locked.", status="handled", kind="pc_control"),
    )
    controller = AvatarController(bridge, published.append)

    controller.submit("lock the screen")
    assert controller.state.state is AvatarState.CONFIRM
    assert controller.state.question == "Lock the screen now?"

    controller.submit("yes")
    assert bridge.sent == ["lock the screen", "yes"]
    assert controller.state.state is AvatarState.DONE


def test_an_action_announcement_shows_working_with_its_name() -> None:
    bus = EventBus()
    published: list = []

    def announce() -> None:
        bus.publish(EventType.TOOL_CALL_START, {"action": "volume_set"})
        bus.publish(EventType.TOOL_CALL_END, {"action": "volume_set"})

    controller = AvatarController(
        FakeBridge(
            Reply("Set to 30.", status="handled", kind="pc_control"), during=announce
        ),
        published.append,
        bus=bus,
    )
    assert controller.watch_actions()
    controller.submit("set volume to 30")

    assert _states(published) == ["thinking", "working", "thinking", "done"]
    working = [m for m in published if isinstance(m, StateMessage)][1]
    assert working.action == "volume_set"
    controller.unwatch_actions()


def test_an_action_from_elsewhere_does_not_move_an_idle_orb() -> None:
    bus = EventBus()
    published: list = []
    controller = AvatarController(FakeBridge(), published.append, bus=bus)
    controller.watch_actions()

    bus.publish(EventType.TOOL_CALL_START, {"action": "notes_list"})

    assert _states(published) == []
    controller.unwatch_actions()


def test_one_request_at_a_time() -> None:
    gate = threading.Event()
    published: list = []
    controller = AvatarController(FakeBridge(during=gate.wait), published.append)

    worker = threading.Thread(target=controller.submit, args=("first",))
    worker.start()
    while not controller.busy:
        time.sleep(0.01)
    assert controller.submit("second") is False
    gate.set()
    worker.join(5)
    assert [
        m.text for m in published if isinstance(m, ChatMessage) and m.role == "user"
    ] == ["first"]


def test_a_bridge_that_raises_is_an_error_state_not_a_crash() -> None:
    class Boom(FakeBridge):
        def send(self, text):
            raise RuntimeError("model gone")

    published: list = []
    controller = AvatarController(Boom(), published.append)
    controller.submit("hello")
    assert controller.state.state is AvatarState.ERROR


def test_a_new_page_gets_the_conversation_then_the_state() -> None:
    controller = AvatarController(FakeBridge(Reply("hi")), lambda _m: None)
    controller.submit("hello")
    snap = controller.snapshot()
    assert [type(m).__name__ for m in snap] == [
        "ChatMessage",
        "ChatMessage",
        "StateMessage",
    ]


# --- what the page may send ---------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        json.dumps({"type": "run", "action": "system_shutdown"}),
        json.dumps({"type": "send"}),
        json.dumps({"type": "send", "text": 42}),
        json.dumps({"type": "send", "text": "   "}),
        json.dumps({"type": "send", "text": "x" * (MAX_INBOUND_TEXT + 1)}),
        json.dumps(["send", "hi"]),
        b"\xff\xfe",
    ],
)
def test_anything_but_a_send_line_is_dropped(raw) -> None:
    assert parse_inbound(raw) is None


def test_a_send_line_is_accepted_trimmed() -> None:
    assert parse_inbound(json.dumps({"type": "send", "text": "  hi  "})) == (
        "send",
        "hi",
    )


# --- the real socket ----------------------------------------------------------

websockets = pytest.importorskip("websockets")


@pytest.fixture
def running():
    from grandpa.cli.avatar_cmd import build

    bridge = FakeBridge(Reply("It is 10:52."))
    controller, server = build(bridge)
    server.start()
    yield controller, server, bridge
    server.stop()


def _recv_until(ws, predicate, timeout: float = 5.0) -> list[dict]:
    seen: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = json.loads(ws.recv(timeout=deadline - time.monotonic()))
        seen.append(data)
        if predicate(data):
            return seen
    raise AssertionError(f"never saw it; got {seen}")


def test_it_binds_loopback_only(running) -> None:
    _controller, server, _bridge = running
    assert server.url.startswith("ws://127.0.0.1:")
    sock = server._server.sockets[0]
    assert sock.getsockname()[0] == "127.0.0.1"


def test_without_the_token_the_handshake_is_refused(running) -> None:
    from websockets.exceptions import InvalidStatus
    from websockets.sync.client import connect

    _controller, server, bridge = running
    for url in (
        f"ws://127.0.0.1:{server.port}/avatar",
        f"ws://127.0.0.1:{server.port}/avatar?token=wrong",
    ):
        with pytest.raises(InvalidStatus):
            connect(url, open_timeout=3).close()
    assert bridge.sent == []


def test_a_page_with_the_token_chats_and_sees_states(running) -> None:
    from websockets.sync.client import connect

    _controller, server, bridge = running
    with connect(server.url, open_timeout=3) as ws:
        first = json.loads(ws.recv(timeout=3))
        assert first == {**first, "type": "state", "state": "idle"}

        ws.send(json.dumps({"type": "run", "action": "system_shutdown"}))
        ws.send(json.dumps({"type": "send", "text": "what time is it"}))
        seen = _recv_until(
            ws, lambda d: d.get("type") == "state" and d["state"] == "idle"
        )

    assert bridge.sent == ["what time is it"]
    assert [d["state"] for d in seen if d["type"] == "state"] == ["thinking", "idle"]
    assert {"type": "chat", "role": "grandpa", "text": "It is 10:52."}.items() <= next(
        d for d in seen if d.get("role") == "grandpa"
    ).items()


# --- the page and the window --------------------------------------------------


def test_the_page_ships_with_the_package() -> None:
    for name in ("index.html", "avatar.js", "avatar.css"):
        assert (WEB_DIR / name).is_file(), name


def test_the_page_loads_nothing_from_the_internet() -> None:
    text = "".join(
        (WEB_DIR / n).read_text(encoding="utf-8")
        for n in ("index.html", "avatar.js", "avatar.css")
    )
    assert "http://" not in text.replace("http://127.0.0.1", "")
    assert "https://" not in text
    html = INDEX.read_text(encoding="utf-8")
    assert "default-src 'none'" in html
    assert "connect-src ws://127.0.0.1:*" in html


def test_the_page_renders_text_never_html() -> None:
    js = (WEB_DIR / "avatar.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js
    assert "textContent" in js


def test_the_page_knows_every_state_it_animates() -> None:
    css = (WEB_DIR / "avatar.css").read_text(encoding="utf-8")
    for state in ("thinking", "working", "speaking", "listening", "confirm"):
        assert f'[data-state="{state}"]' in css, state


def test_the_window_is_frameless_on_top_and_gets_the_address_after_load() -> None:
    calls: dict = {}

    class Hook:
        def __init__(self):
            self.handlers = []

        def __iadd__(self, handler):
            self.handlers.append(handler)
            return self

    class Window:
        def __init__(self):
            self.events = type("E", (), {"loaded": Hook()})()
            self.js: list[str] = []

        def evaluate_js(self, script):
            self.js.append(script)

    window = Window()

    class FakeWebview:
        @staticmethod
        def create_window(title, url, **kwargs):
            calls["create"] = (title, url, kwargs)
            return window

        @staticmethod
        def start(**kwargs):
            calls["start"] = kwargs
            for handler in window.events.loaded.handlers:
                handler()

    run_window("ws://127.0.0.1:1/avatar?token=t", webview_module=FakeWebview)

    title, url, kwargs = calls["create"]
    assert Path(url) == INDEX
    assert kwargs["frameless"] and kwargs["on_top"] and kwargs["transparent"]
    assert calls["start"]["http_server"] is True
    assert window.js == [connect_script("ws://127.0.0.1:1/avatar?token=t")]


def test_the_command_is_registered() -> None:
    from click.testing import CliRunner

    from grandpa.cli import cli

    result = CliRunner().invoke(cli, ["avatar", "--help"])
    assert result.exit_code == 0, result.output
    assert "--no-window" in result.output
