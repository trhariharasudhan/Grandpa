"""Green means an operation completed. Not "a reply arrived".

The failure mode worth guarding is a green ring that lights for everything,
because then it says nothing the resting state did not already say. So the rule
has two halves -- the action layer's own ``status == "handled"`` and a kind that
is a real ``ActionKind`` -- and the tests below are mostly about the things that
must *not* turn it green: a plan, a staged approval, a dry run, a refusal, and
the "who are you" reply, which returns ``kind="local"`` without doing anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from grandpa.local_action_result import ActionKind, ActionStatus
from grandpa.ui.bridge import BridgeReply
from grandpa.ui.bubble import (
    NOT_DONE_KINDS,
    BubbleController,
    BubbleState,
    completed_an_operation,
    done_kinds,
)

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


def run_one(tmp_path: Path, reply: BridgeReply) -> BubbleController:
    panel = FakePanel()
    controller = BubbleController(
        view=panel, bridge=Bridge(reply), speak_replies=False
    )
    controller.start(position_path=tmp_path / "p.json")
    controller.submit("do the thing")
    return controller


# --- 1. the set is derived, not typed out ------------------------------------


def test_the_excluded_kinds_are_all_real_action_kinds() -> None:
    """A typo here would exclude nothing and nobody would notice: the set
    would still be built, still be non-empty, and quietly include the kind it
    was meant to leave out."""
    known = set(get_args(ActionKind))

    assert NOT_DONE_KINDS <= known, f"not real ActionKinds: {NOT_DONE_KINDS - known}"


def test_the_set_is_every_other_action_kind() -> None:
    assert done_kinds() == set(get_args(ActionKind)) - NOT_DONE_KINDS
    assert done_kinds(), "nothing would ever be a success"


def test_handled_is_a_real_action_status() -> None:
    """The rule leans on this exact word. If the action layer renamed it, the
    ring would silently stop going green rather than fail anywhere."""
    assert "handled" in get_args(ActionStatus)


def test_the_kinds_are_not_restated_in_the_ui() -> None:
    """Inspected as a syntax tree: the UI may name the three exclusions and
    nothing else, so a kind added to the action layer cannot be missed here."""
    import ast

    tree = ast.parse(Path("src/grandpa/ui/bubble.py").read_text(encoding="utf-8"))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    restated = (set(get_args(ActionKind)) - NOT_DONE_KINDS) & literals

    assert restated == set(), f"action kinds copied into the UI: {restated}"


# --- 2. what does turn it green ----------------------------------------------


@pytest.mark.parametrize("kind", sorted(done_kinds()))
def test_a_performed_action_completes(kind: str) -> None:
    assert completed_an_operation(BridgeReply("done", status="handled", kind=kind))


def test_the_controller_rests_in_success_after_an_automation(tmp_path: Path) -> None:
    controller = run_one(
        tmp_path, BridgeReply("Opening Notepad.", status="handled", kind="app")
    )

    assert controller.state is BubbleState.SUCCESS


def test_success_persists_rather_than_flashing(tmp_path: Path) -> None:
    """Like ERROR. A failure you can still see a minute later is useful, and so
    is a success -- and neither needs a timer to be honest."""
    controller = run_one(
        tmp_path, BridgeReply("Opened.", status="handled", kind="window")
    )

    for _ in range(50):
        controller.refresh_meter()

    assert controller.state is BubbleState.SUCCESS


def test_the_next_hold_leaves_success_behind(tmp_path: Path) -> None:
    """It is a resting state, not a sticky one."""
    controller = run_one(
        tmp_path, BridgeReply("Opened.", status="handled", kind="app")
    )

    controller._enter(BubbleState.RECORDING)

    assert controller.state is BubbleState.RECORDING


def test_success_does_not_refuse_the_next_hold(tmp_path: Path) -> None:
    from grandpa.ui.bubble import STATES_THAT_REFUSE_A_HOLD

    assert BubbleState.SUCCESS not in STATES_THAT_REFUSE_A_HOLD


def test_speaking_does_not_eat_the_green(tmp_path: Path) -> None:
    """_speak returns the state to IDLE when it finishes, so the order matters:
    the green has to land after it, not before."""

    class Speaker:
        def speak(self, text):
            return type("R", (), {"status": "spoken"})()

        def stop(self):
            pass

    panel = FakePanel()
    controller = BubbleController(
        view=panel,
        bridge=Bridge(BridgeReply("Opened.", status="handled", kind="app")),
        speak_replies=True,
        speaker=Speaker(),
    )
    controller.start(position_path=tmp_path / "p.json")
    controller.submit("open notepad")

    assert controller.state is BubbleState.SUCCESS


# --- 3. what must never turn it green ----------------------------------------


def test_a_plan_is_not_a_performance() -> None:
    """agent_plan produced a plan. Nothing ran."""
    assert not completed_an_operation(
        BridgeReply("Here is the plan.", status="handled", kind="agent_plan")
    )


def test_a_refusal_is_not_a_success() -> None:
    assert not completed_an_operation(
        BridgeReply("Refused.", status="handled", kind="blocked")
    )
    assert not completed_an_operation(
        BridgeReply("Refused.", status="blocked", kind="app")
    )


def test_a_lookup_changed_nothing() -> None:
    assert not completed_an_operation(
        BridgeReply("Notepad is at C:/...", status="handled", kind="app_lookup")
    )


@pytest.mark.parametrize(
    "status", ["requires_confirmation", "unsupported", "no_match", "error", "cancelled"]
)
def test_no_status_other_than_handled_completes(status: str) -> None:
    """A staged approval and a dry run both come back like this. Green for
    either would be a ring saying "done" about something that never ran."""
    assert not completed_an_operation(
        BridgeReply("...", status=status, kind="app")
    )


def test_the_staged_approval_sentence_does_not_go_green(tmp_path: Path) -> None:
    controller = run_one(
        tmp_path,
        BridgeReply(
            "That needs confirmation. Say yes.",
            status="requires_confirmation",
            kind="app",
        ),
    )

    assert controller.state is BubbleState.IDLE


def test_the_who_are_you_reply_never_completes() -> None:
    """It returns status="handled" with kind="local" and performs nothing.
    "local" is not an ActionKind, which is the whole reason the rule is
    membership in the set and never ``kind != "voice"``."""
    assert "local" not in get_args(ActionKind)
    assert not completed_an_operation(
        BridgeReply("I can chat, open and control applications...",
                    status="handled", kind="local")
    )


@pytest.mark.parametrize("kind", ["voice", "assistant", "local", "session_control",
                                  "web_search", "error", ""])
def test_a_conversational_reply_leaves_the_ring_resting(kind: str) -> None:
    assert not completed_an_operation(
        BridgeReply("Some words.", status="handled", kind=kind)
    )


def test_a_reply_with_no_kind_at_all_completes_nothing() -> None:
    """Every BridgeReply built before this existed has kind=None."""
    assert not completed_an_operation(BridgeReply("hello", status="handled"))
    assert not completed_an_operation(object())


def test_a_chat_reply_still_rests_in_standby(tmp_path: Path) -> None:
    controller = run_one(tmp_path, BridgeReply("A sentence.", status="ok"))

    assert controller.state is BubbleState.IDLE


def test_a_failure_still_goes_to_error(tmp_path: Path) -> None:
    controller = run_one(
        tmp_path, BridgeReply("Nope.", status="error", failed=True, kind="app")
    )

    assert controller.state is BubbleState.ERROR


# --- 4. the bridge carries it through ----------------------------------------


def test_the_bridge_passes_the_responders_kind_along() -> None:
    """It used to drop it. Nothing else in the chain invents it."""
    from grandpa.ui.bridge import InProcessBridge

    class Responder:
        def handle_user_input(self, text):
            return type("R", (), {"text": "Opened.", "status": "handled",
                                  "kind": "app"})()

    bridge = InProcessBridge(responder=Responder())
    reply = bridge.send("open notepad")

    assert (reply.status, reply.kind) == ("handled", "app")
    assert completed_an_operation(reply)


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


def test_success_has_a_look_and_it_is_green_and_still() -> None:
    from grandpa.ui.orb_image import ORB_STYLES, is_animated
    from grandpa.ui.palette import GREEN_SUCCESS, rgb

    style = ORB_STYLES["success"]

    assert style.colour == rgb(GREEN_SUCCESS)
    assert style.arc is None
    assert style.pulse == 0.0
    assert not is_animated("success"), "a resting state must cost nothing"


def test_the_label_is_done() -> None:
    from grandpa.ui.bubble import STATE_LABELS

    assert STATE_LABELS[BubbleState.SUCCESS] == "Done"
