"""The orb talks to the app's chat engine (one brain)."""

from __future__ import annotations

import threading

from grandpa.ui.avatar_controller import CONFIRM_STATUSES
from grandpa.ui.session_bridge import SessionBridge, _reply_from


class FakeSession:
    """Plays the engine: each send publishes a scripted turn on a thread."""

    def __init__(self, publish, script):
        self.publish = publish
        self.script = list(script)
        self.sent: list[str] = []
        self.started = False

    def start(self):
        self.started = True
        self.publish({"type": "state", "state": "idle"})

    def stop(self):
        pass

    def send(self, text):
        self.sent.append(text)
        events = self.script.pop(0)
        self.publish({"type": "state", "state": "thinking"})

        def play():
            for event in events:
                self.publish(event)

        threading.Thread(target=play).start()
        return True


class Speech:
    def transcribe(self, audio):
        return audio

    def speech_ready(self):
        return True


def bridge(script):
    made = {}

    def factory(publish):
        made["session"] = FakeSession(publish, script)
        return made["session"]

    return SessionBridge(session_factory=factory, transcriber=Speech()), made


def test_a_turn_returns_the_reply_not_the_tool_notes() -> None:
    b, made = bridge(
        [
            [
                {"type": "note", "text": "  · volume_set ok"},
                {"type": "reply", "text": "Volume is now 30%."},
                {"type": "state", "state": "idle"},
            ]
        ]
    )
    reply = b.send("volume 30")
    assert reply.text == "Volume is now 30%." and reply.status == "ok"
    assert made["session"].started and made["session"].sent == ["volume 30"]


def test_a_question_becomes_a_confirm_and_the_next_words_answer_it() -> None:
    b, made = bridge(
        [
            [
                {"type": "ask", "kind": "confirm", "prompt": "Confirm: close_app (target='notepad') [y/N]"},
                {"type": "state", "state": "asking"},
            ],
            [{"type": "reply", "text": "Closed Notepad."}, {"type": "state", "state": "idle"}],
        ]
    )
    asked = b.send("close notepad")
    assert asked.status == "pending_confirmation" and asked.status in CONFIRM_STATUSES
    assert asked.text.endswith("Say yes or no.") and "[y/N]" not in asked.text
    done = b.send("seri")
    assert done.text == "Closed Notepad."
    assert made["session"].sent == ["close notepad", "seri"]


def test_a_local_action_message_printed_as_a_note_is_spoken() -> None:
    reply = _reply_from([{"type": "note", "text": "Calculator is open."}])
    assert reply.text == "Calculator is open."


def test_silence_is_never_reported_as_done() -> None:
    assert "Done" not in _reply_from([]).text


def test_an_engine_that_did_not_start_says_so() -> None:
    def factory(publish):
        class Down(FakeSession):
            def start(self):
                self.publish({"type": "engine_down", "reason": "Ollama is not running"})
                self.publish({"type": "state", "state": "stopped"})

        return Down(publish, [])

    b = SessionBridge(session_factory=factory, transcriber=Speech())
    ok, why = b.warm()
    assert not ok and "Ollama" in why
    assert b.send("hello").failed


def test_a_confirm_question_is_said_once_in_plain_words() -> None:
    prompt = "Confirm: Close Calculator? Unsaved work may be lost. (requires_confirmation) [y/N]"
    reply = _reply_from(
        [
            {"type": "note", "text": prompt.replace(" [y/N]", "")},
            {"type": "ask", "kind": "confirm", "prompt": prompt},
            {"type": "state", "state": "asking"},
        ]
    )
    assert reply.text == "Close Calculator? Unsaved work may be lost. Say yes or no."
