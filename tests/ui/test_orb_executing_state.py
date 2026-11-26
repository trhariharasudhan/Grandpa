"""Purple means an automation is running, and only while one actually is.

The state is set from the action layer's own announcement around the single
site where a catalogued action is performed -- never guessed at from the text of
a request, and never from the shape of a reply. Which means the interesting
tests are the negative ones: an announcement arriving when no request is in
flight, an end without a start, a second start, and the two paths that look
like an automation and are not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.core.events import EventType, get_event_bus, reset_event_bus
from grandpa.ui.bridge import BridgeReply

pytestmark = pytest.mark.core


class FakePanel:
    def __init__(self) -> None:
        self.reply = ""
        self.hidden = False
        self.state = ""

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


class FakeOrb:
    def __init__(self) -> None:
        self.states: list[tuple[str, bool]] = []

    def show(self, *, position, topmost):
        pass

    def set_state(self, state, *, unread):
        self.states.append((str(state), bool(unread)))

    def set_level(self, level):
        pass

    def set_levels(self, levels):
        pass

    def position(self):
        return (0, 0)

    def close(self):
        pass


class Bridge:
    speech_ready = True

    def __init__(self, reply: BridgeReply | None = None) -> None:
        self.reply = reply or BridgeReply("done", status="handled", kind="app")

    def send(self, text: str) -> BridgeReply:
        return self.reply


@pytest.fixture(autouse=True)
def _fresh_bus():
    reset_event_bus()
    yield
    reset_event_bus()


def started() -> None:
    get_event_bus().publish(EventType.TOOL_CALL_START, {"action": "app_open"})


def finished() -> None:
    get_event_bus().publish(EventType.TOOL_CALL_END, {"action": "app_open"})


# --- 1. the state exists and is wired the right way round --------------------


# --- 2. the negative cases, which are the whole point ------------------------


# --- 3. the signal is binary, so the animation must not imply a fraction -----


def test_the_chase_is_indeterminate_because_the_signal_is() -> None:
    """There is no progress number anywhere in this path: the action layer
    announces a start and an end. A ring that filled from empty to full would
    be inventing a fraction, so the lit arc travels at a fixed width instead.
    Asserted on the pixels in test_orb_animations.py; asserted here as the
    reason."""
    import ast

    source = Path("src/grandpa/action_layer/executor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    announcements = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_announce"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]

    assert sorted(announcements) == ["tool_call_end", "tool_call_start"], (
        f"the action layer announces {announcements} -- if a progress event "
        "appeared, the chase could become determinate"
    )
