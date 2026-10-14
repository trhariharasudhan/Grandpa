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
from grandpa.ui.bubble import STATES_THAT_REFUSE_A_HOLD, BubbleController, BubbleState

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


def a_controller(tmp_path: Path) -> tuple[BubbleController, FakePanel, FakeOrb]:
    panel, orb = FakePanel(), FakeOrb()
    controller = BubbleController(
        view=panel, bridge=Bridge(), orb=orb, speak_replies=False
    )
    controller.start(position_path=tmp_path / "p.json")
    assert controller.watch_actions() is True
    return controller, panel, orb


def started() -> None:
    get_event_bus().publish(EventType.TOOL_CALL_START, {"action": "app_open"})


def finished() -> None:
    get_event_bus().publish(EventType.TOOL_CALL_END, {"action": "app_open"})


# --- 1. the state exists and is wired the right way round --------------------


def test_the_state_and_its_colour_exist() -> None:
    from grandpa.ui.orb_image import ORB_STYLES
    from grandpa.ui.palette import PURPLE_EXECUTING, rgb

    assert BubbleState.EXECUTING == "executing"
    assert ORB_STYLES["executing"].colour == rgb(PURPLE_EXECUTING)
    assert ORB_STYLES["executing"].animation == "chase"


def test_a_hold_is_refused_while_an_automation_runs() -> None:
    """Something is already happening to the machine."""
    assert BubbleState.EXECUTING in STATES_THAT_REFUSE_A_HOLD


def test_an_announcement_while_thinking_turns_the_ring_purple(
    tmp_path: Path,
) -> None:
    controller, _panel, orb = a_controller(tmp_path)
    controller._enter(BubbleState.THINKING)

    started()

    assert controller.state is BubbleState.EXECUTING
    assert orb.states[-1] == ("executing", False)


def test_the_end_hands_it_back_to_thinking(tmp_path: Path) -> None:
    """Not to idle: the reply is still coming when the automation returns."""
    controller, _panel, _orb = a_controller(tmp_path)
    controller._enter(BubbleState.THINKING)
    started()

    finished()

    assert controller.state is BubbleState.THINKING


def test_the_label_says_working(tmp_path: Path) -> None:
    from grandpa.ui.bubble import STATE_LABELS

    assert STATE_LABELS[BubbleState.EXECUTING] == "Working..."


# --- 2. the negative cases, which are the whole point ------------------------


@pytest.mark.parametrize(
    "state",
    [
        BubbleState.LOADING,
        BubbleState.IDLE,
        BubbleState.RECORDING,
        BubbleState.SPEAKING,
        BubbleState.SUCCESS,
        BubbleState.ERROR,
    ],
)
def test_an_announcement_with_no_request_in_flight_is_ignored(
    tmp_path: Path, state: BubbleState
) -> None:
    """The bus carries every catalogued action performed anywhere in the
    process -- a scheduled task, another surface, a background job. The orb
    speaks for the request the user just made and for nothing else."""
    controller, _panel, _orb = a_controller(tmp_path)
    controller._enter(state)

    started()

    assert controller.state is state, f"{state} was overwritten by an announcement"


def test_an_end_without_a_start_changes_nothing(tmp_path: Path) -> None:
    controller, _panel, _orb = a_controller(tmp_path)
    controller._enter(BubbleState.THINKING)

    finished()

    assert controller.state is BubbleState.THINKING


def test_a_second_start_does_not_disturb_the_first(tmp_path: Path) -> None:
    """A request can perform several actions. The ring stays purple across
    them rather than flickering back to yellow between."""
    controller, _panel, orb = a_controller(tmp_path)
    controller._enter(BubbleState.THINKING)
    started()
    before = len(orb.states)

    started()

    assert controller.state is BubbleState.EXECUTING
    assert len(orb.states) == before + 1  # re-entered, not toggled


def test_unsubscribing_stops_the_state_changing(tmp_path: Path) -> None:
    controller, _panel, _orb = a_controller(tmp_path)
    controller._enter(BubbleState.THINKING)

    controller.unwatch_actions()
    started()

    assert controller.state is BubbleState.THINKING


def test_stopping_the_bubble_unsubscribes(tmp_path: Path) -> None:
    """Otherwise a closed window keeps a callback alive on a process-wide bus."""
    controller, _panel, _orb = a_controller(tmp_path)

    controller.stop()

    assert controller._action_watch is None


def test_watching_twice_subscribes_once(tmp_path: Path) -> None:
    controller, _panel, _orb = a_controller(tmp_path)
    controller._enter(BubbleState.THINKING)

    assert controller.watch_actions() is True
    started()
    controller._enter(BubbleState.THINKING)
    before = controller.state

    assert before is BubbleState.THINKING


def test_a_controller_with_no_bus_still_runs(tmp_path: Path) -> None:
    """A bubble whose event bus is unavailable loses the purple ring and
    nothing else."""
    panel = FakePanel()
    controller = BubbleController(view=panel, bridge=Bridge(), speak_replies=False)
    controller.start(position_path=tmp_path / "p.json")
    controller.unwatch_actions()  # never watched; must not raise
    controller.submit("open notepad")

    assert panel.reply == "done"


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
