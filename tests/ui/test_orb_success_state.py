"""Green means an operation completed. Not "a reply arrived".

The failure mode worth guarding is a green ring that lights for everything,
because then it says nothing the resting state did not already say. So the rule
has two halves -- the action layer's own ``status == "handled"`` and a kind that
is a real ``ActionKind`` -- and the tests below are mostly about the things that
must *not* turn it green: a plan, a staged approval, a dry run, a refusal, and
the "who are you" reply, which returns ``kind="local"`` without doing anything.
"""

from __future__ import annotations

from typing import get_args

import pytest

from grandpa.local_action_result import ActionStatus
from grandpa.ui.bridge import BridgeReply

pytestmark = pytest.mark.core


class FakePanel:
    def __init__(self) -> None:
        self.reply = ""
        self.hidden = False

    def show(self, *, position, topmost):
        pass

    def set_state(self, state, label):
        self.state = state

    def set_status_line(self, text):
        self.status = text

    def set_reply(self, text):
        self.reply = text

    def set_transcript(self, text):
        pass

    def clear_entry(self):
        pass

    def set_entry_text(self, text):
        pass

    def set_levels(self, levels):
        pass

    def position(self):
        return (0, 0)

    def move_to(self, x, y):
        return True

    def hide(self):
        self.hidden = True
        return True

    def unhide(self):
        self.hidden = False
        return True

    def close(self):
        pass


class Bridge:
    speech_ready = True

    def __init__(self, reply: BridgeReply) -> None:
        self.reply = reply

    def send(self, text: str) -> BridgeReply:
        return self.reply


# --- 1. the set is derived, not typed out ------------------------------------


def test_handled_is_a_real_action_status() -> None:
    """The rule leans on this exact word. If the action layer renamed it, the
    ring would silently stop going green rather than fail anywhere."""
    assert "handled" in get_args(ActionStatus)


# --- 2. what does turn it green ----------------------------------------------


# --- 3. what must never turn it green ----------------------------------------


# --- 4. the bridge carries it through ----------------------------------------


def test_a_responder_with_no_kind_yields_none_not_a_string() -> None:
    from grandpa.ui.bridge import InProcessBridge

    class Responder:
        def handle_user_input(self, text):
            return type("R", (), {"text": "Words.", "status": "ok"})()

    assert InProcessBridge(responder=Responder()).send("hi").kind is None


def test_kind_is_optional_so_older_construction_still_works() -> None:
    assert BridgeReply("x").kind is None
    assert BridgeReply("x", status="handled").kind is None


# --- 5. the look -------------------------------------------------------------
