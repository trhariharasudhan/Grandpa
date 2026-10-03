"""GrandpaMB driver against a fake board that speaks the firmware's protocol.

No serial port, simulator or pyserial needed: ``FakeBoard`` is a transport
that answers the way ``src/protocol.cpp`` in the GrandpaMB firmware does.
"""

from __future__ import annotations

import json
import queue
import threading
import time

import pytest

from grandpa.devices.grandpamb import (
    BoardError,
    BoardNotConnectedError,
    GrandpaMBClient,
    GrandpaMBConfig,
)

pytestmark = pytest.mark.core


class FakeBoard:
    """In-memory transport. ``write`` gets host lines, ``read`` returns board lines."""

    def __init__(self, *, silent: bool = False, skip_confirm: bool = False) -> None:
        self._out: "queue.Queue[bytes]" = queue.Queue()
        self.silent = silent
        self.skip_confirm = skip_confirm
        self.relay = False
        self.state = "offline"
        self.token = ""
        self.received: list[dict] = []
        self.closed = False

    # board -> host
    def emit(self, msg: dict) -> None:
        self._out.put((json.dumps(msg) + "\n").encode())

    def read(self, size: int = 1) -> bytes:
        try:
            return self._out.get(timeout=0.05)
        except queue.Empty:
            return b""

    def close(self) -> None:
        self.closed = True

    # host -> board
    def write(self, data: bytes) -> int:
        for line in data.decode().splitlines():
            self._handle(json.loads(line))
        return len(data)

    def _reply(self, rid, ok=True, **extra) -> None:
        if not self.silent:
            self.emit({"type": "reply", "id": rid, "ok": ok, **extra})

    def _handle(self, m: dict) -> None:
        self.received.append(m)
        rid, cmd = m.get("id"), m["cmd"]
        if cmd == "ping":
            self._reply(rid, msg="pong")
        elif cmd == "info":
            self._reply(rid, device="GrandpaMB", fw="0.1.0", state=self.state, relay=self.relay)
        elif cmd == "state":
            self.state = m["value"]
            self._reply(rid, msg=self.state)
        elif cmd in ("say", "beep"):
            self._reply(rid)
        elif cmd == "relay" and m["value"] == "off":
            self.relay = False
            self._reply(rid, msg="relay off")
        elif cmd == "relay" and m["value"] == "on":
            if self.skip_confirm:  # a broken firmware that switches straight on
                self.relay = True
                self._reply(rid, msg="relay on")
                return
            self.token = "3FA9C1"
            self._reply(rid, confirm_required=True, action="relay_on", token=self.token, expires_ms=10000)
        elif cmd == "confirm":
            if m.get("token") == self.token and self.token:
                self.relay, self.token = True, ""
                self._reply(rid, msg="relay on")
            else:
                self.token = ""
                self._reply(rid, ok=False, error="wrong token, action cancelled")
        elif cmd == "cancel":
            self.token = ""
            self._reply(rid, msg="cancelled")
        else:
            self._reply(rid, ok=False, error="unknown cmd (try: help)")


def make(board: FakeBoard, timeout: float = 1.0) -> GrandpaMBClient:
    return GrandpaMBClient(GrandpaMBConfig(port="fake://", reply_timeout=timeout), transport=board)


def wait_for(predicate, timeout: float = 1.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- basics -------------------------------------------------------------------


def test_ping_and_info() -> None:
    with make(FakeBoard()) as mb:
        assert mb.ping() is True
        assert mb.info()["device"] == "GrandpaMB"


def test_state_is_validated_before_anything_is_sent() -> None:
    board = FakeBoard()
    with make(board) as mb:
        mb.set_state("Thinking ")
        assert board.state == "thinking"
        with pytest.raises(ValueError):
            mb.set_state("dancing")
        assert [m["cmd"] for m in board.received] == ["state"]


def test_say_is_trimmed_to_what_the_oled_can_show() -> None:
    board = FakeBoard()
    with make(board) as mb:
        mb.say("Vanakkam   Captain\n" + "x" * 200)
        sent = board.received[-1]["text"]
        assert sent.startswith("Vanakkam Captain ")
        assert len(sent) == 60


def test_beep_is_clamped() -> None:
    board = FakeBoard()
    with make(board) as mb:
        mb.beep(ms=99999, freq=5)
        assert board.received[-1]["ms"] == 2000
        assert board.received[-1]["freq"] == 100


# --- errors ---------------------------------------------------------------------


def test_board_refusal_raises() -> None:
    with make(FakeBoard()) as mb:
        with pytest.raises(BoardError, match="unknown cmd"):
            mb.call("selfdestruct")


def test_silent_board_times_out() -> None:
    with make(FakeBoard(silent=True), timeout=0.2) as mb:
        with pytest.raises(BoardError, match="did not answer"):
            mb.ping()


def test_closed_client_refuses_calls() -> None:
    mb = make(FakeBoard())
    mb.close()
    assert wait_for(lambda: not mb.connected)
    with pytest.raises(BoardNotConnectedError):
        mb.ping()


def test_boot_noise_and_bad_json_are_ignored() -> None:
    board = FakeBoard()
    with make(board) as mb:
        board._out.put(b"ESP-ROM:esp32s3-20210327\n{not json\n")
        assert mb.ping() is True


# --- relay safety -----------------------------------------------------------------


def test_relay_on_needs_a_token_round_trip() -> None:
    board = FakeBoard()
    with make(board) as mb:
        pending = mb.request_relay_on()
        assert pending.token == "3FA9C1"
        assert board.relay is False, "asking must not switch anything"
        mb.confirm(pending.token)
        assert board.relay is True


def test_wrong_token_does_not_switch() -> None:
    board = FakeBoard()
    with make(board) as mb:
        mb.request_relay_on()
        with pytest.raises(BoardError, match="wrong token"):
            mb.confirm("000000")
        assert board.relay is False


def test_cancel_leaves_relay_off() -> None:
    board = FakeBoard()
    with make(board) as mb:
        mb.request_relay_on()
        mb.cancel()
        assert board.relay is False


def test_firmware_that_skips_confirmation_is_rejected() -> None:
    with make(FakeBoard(skip_confirm=True)) as mb:
        with pytest.raises(BoardError, match="did not ask for confirmation"):
            mb.request_relay_on()


def test_relay_off_is_immediate() -> None:
    board = FakeBoard()
    board.relay = True
    with make(board) as mb:
        mb.relay_off()
        assert board.relay is False


# --- events -----------------------------------------------------------------------


def test_events_reach_subscribers_and_telemetry_is_cached() -> None:
    board = FakeBoard()
    seen: list[dict] = []
    with make(board) as mb:
        mb.subscribe(seen.append)
        board.emit({"type": "event", "name": "wake"})
        board.emit({"type": "telemetry", "temp_c": 29.0, "humidity": 65.0})
        assert wait_for(lambda: len(seen) == 2)
        assert seen[0]["name"] == "wake"
        assert mb.latest_telemetry["temp_c"] == 29.0


def test_a_failing_subscriber_does_not_kill_the_link() -> None:
    board = FakeBoard()
    with make(board) as mb:
        mb.subscribe(lambda m: 1 / 0)
        board.emit({"type": "event", "name": "wake"})
        time.sleep(0.1)
        assert mb.ping() is True


def test_concurrent_calls_get_their_own_replies() -> None:
    board = FakeBoard()
    errors: list[Exception] = []
    with make(board) as mb:

        def worker() -> None:
            try:
                for _ in range(20):
                    assert mb.ping()
            except Exception as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert errors == []


def test_config_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRANDPA_MB_PORT", "COM5")
    monkeypatch.setenv("GRANDPA_MB_TIMEOUT", "1.5")
    cfg = GrandpaMBConfig.from_env()
    assert cfg.port == "COM5"
    assert cfg.reply_timeout == 1.5
