"""Collapsed is voice-only, and a reply nobody heard leaves a mark.

Three promises are checked here, each of which has a way of quietly breaking:

* **the panel keeps the last exchange.** Collapsing withdraws the window; it
  must not destroy it, because speech is not reviewable and the panel is the
  only place a reply can be read after the fact.
* **the unread ring.** With speech off, a reply that arrives while the panel is
  away is a thing that happened and nobody encountered. It shows as amber, it
  clears when the panel opens, and it never times out -- a notification that
  disappears on its own is one that can be missed entirely.
* **the remembered state.** Which of the two it was in survives the process,
  and a save that knows nothing about collapse cannot erase it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from grandpa.ui.bubble import (
    DEFAULT_ORB_POSITION,
    BubbleController,
    BubbleState,
    load_collapsed,
    load_orb_position,
    load_position,
    save_position,
)
from grandpa.ui.orb_view import anchor_panel_to_orb

pytestmark = pytest.mark.core

AREA = (0, 0, 1920, 1080)
PANEL = (400, 324)


class FakePanel:
    """The panel, reduced to what collapsing touches."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.hidden = False
        self.destroyed = False
        self.reply = ""
        self.transcript = ""
        self.at = (40, 40)
        self.state = ""

    def show(self, *, position, topmost):
        self.at = tuple(position)
        self.calls.append("show")

    def set_state(self, state, label):
        self.state = state

    def set_status_line(self, text):
        self.status = text

    def set_reply(self, text):
        self.reply = text
        self.calls.append("set_reply")

    def set_transcript(self, text):
        self.transcript = text

    def clear_entry(self):
        pass

    def set_entry_text(self, text):
        pass

    def set_levels(self, levels):
        self.levels = levels

    def position(self):
        return self.at

    def move_to(self, x, y):
        self.at = (int(x), int(y))
        self.calls.append("move_to")
        return True

    def hide(self):
        self.hidden = True
        self.calls.append("hide")
        return True

    def unhide(self):
        self.hidden = False
        self.calls.append("unhide")
        return True

    def close(self):
        self.destroyed = True
        self.calls.append("close")


class FakeOrb:
    def __init__(self) -> None:
        self.states: list[tuple[str, bool]] = []
        self.levels: list[float] = []
        self.at = DEFAULT_ORB_POSITION
        self.closed = False

    def show(self, *, position, topmost):
        self.at = tuple(position)

    def set_state(self, state, *, unread):
        self.states.append((str(state), bool(unread)))

    def set_level(self, level):
        self.levels.append(float(level))

    def position(self):
        return self.at

    def close(self):
        self.closed = True

    @property
    def unread_shown(self) -> bool:
        return bool(self.states) and self.states[-1][1]


class Reply:
    def __init__(self, text: str, failed: bool = False) -> None:
        self.text = text
        self.failed = failed


class Bridge:
    speech_ready = True

    def __init__(self, reply: Reply | None = None) -> None:
        self.reply = reply or Reply("the answer")
        self.sent: list[str] = []

    def send(self, text: str) -> Reply:
        self.sent.append(text)
        return self.reply


class Speaker:
    def __init__(self, status: str = "spoken") -> None:
        self.status = status
        self.said: list[str] = []

    def speak(self, text: str):
        self.said.append(text)
        return type("Result", (), {"status": self.status})()

    def stop(self) -> None:
        pass


def a_controller(tmp_path: Path, **kwargs) -> tuple[BubbleController, FakePanel, FakeOrb]:
    panel, orb = FakePanel(), FakeOrb()
    controller = BubbleController(
        view=panel,
        bridge=kwargs.pop("bridge", Bridge()),
        orb=orb,
        anchor=lambda at: anchor_panel_to_orb(at, PANEL, area=AREA),
        speak_replies=kwargs.pop("speak_replies", False),
        speaker=kwargs.pop("speaker", None),
        **kwargs,
    )
    controller.start(position_path=tmp_path / "bubble-position.json")
    return controller, panel, orb


# --- 1. which state it starts in --------------------------------------------


def test_a_first_run_opens_as_the_orb(tmp_path: Path) -> None:
    """Collapsed, with no remembered state. The decision, pinned: the panel is
    400x324 of always-on-top window and the orb is the thing that earns its
    place on a desktop by not being in the way."""
    controller, panel, _orb = a_controller(tmp_path)

    assert controller.collapsed is True
    assert panel.hidden is True


def test_both_windows_exist_even_though_one_is_hidden(tmp_path: Path) -> None:
    """Measured reason, not a preference: creating a window takes the
    foreground. A panel built on first expand would take it then, every time."""
    controller, panel, orb = a_controller(tmp_path)

    assert "show" in panel.calls
    assert orb.at == DEFAULT_ORB_POSITION
    assert panel.destroyed is False
    assert controller.collapsed is True


def test_the_state_is_remembered_across_runs(tmp_path: Path) -> None:
    store = tmp_path / "bubble-position.json"
    first, panel, _orb = a_controller(tmp_path)
    first.expand()
    first.stop()

    assert load_collapsed(store) is False

    second, second_panel, _orb2 = a_controller(tmp_path)

    assert second.collapsed is False
    assert second_panel.hidden is False


def test_the_orb_remembers_where_it_was_dragged(tmp_path: Path) -> None:
    store = tmp_path / "bubble-position.json"
    controller, _panel, orb = a_controller(tmp_path)
    controller.orb_position = (900, 600)
    orb.at = (900, 600)
    controller.stop()

    assert load_orb_position(store) == (900, 600)

    again, _panel2, orb2 = a_controller(tmp_path)

    assert again.orb_position == (900, 600)
    assert orb2.at == (900, 600)


def test_a_save_that_knows_nothing_about_collapse_cannot_erase_it(
    tmp_path: Path,
) -> None:
    """The keys are merged, not rewritten. Otherwise an unrelated code path
    saving a position silently forgets which state the window was in."""
    store = tmp_path / "bubble-position.json"
    save_position((10, 20), store, collapsed=True, orb_position=(700, 300))

    save_position((11, 21), store)

    assert load_collapsed(store) is True
    assert load_orb_position(store) == (700, 300)
    assert load_position(store) == (11, 21)


def test_an_unreadable_state_file_is_not_fatal(tmp_path: Path) -> None:
    """It is a window position, not data worth failing over."""
    store = tmp_path / "bubble-position.json"
    store.write_text("{not json", encoding="utf-8")

    assert load_collapsed(store) is True
    assert load_orb_position(store) == DEFAULT_ORB_POSITION


def test_an_old_position_file_without_the_new_keys_still_works(
    tmp_path: Path,
) -> None:
    """Written by the version before the orb existed."""
    store = tmp_path / "bubble-position.json"
    store.write_text(json.dumps({"x": 300, "y": 400}), encoding="utf-8")

    assert load_position(store) == (300, 400)
    assert load_orb_position(store) == DEFAULT_ORB_POSITION
    assert load_collapsed(store) is True


# --- 2. collapsing and expanding --------------------------------------------


def test_toggling_hides_and_restores_the_panel(tmp_path: Path) -> None:
    controller, panel, _orb = a_controller(tmp_path)

    assert controller.toggle_collapsed() is False
    assert panel.hidden is False

    assert controller.toggle_collapsed() is True
    assert panel.hidden is True


def test_the_panel_still_holds_the_last_exchange_after_a_collapse(
    tmp_path: Path,
) -> None:
    """The whole reason collapsing withdraws rather than destroys. Speech is
    not reviewable; this is the only place the reply can be read later."""
    controller, panel, _orb = a_controller(tmp_path)
    controller.expand()
    controller.submit("what is the time")

    reply = panel.reply
    assert reply

    controller.collapse()
    controller.expand()

    assert panel.destroyed is False
    assert panel.reply == reply


def test_expanding_puts_the_panel_beside_the_orb(tmp_path: Path) -> None:
    controller, panel, _orb = a_controller(tmp_path)
    controller.orb_position = (1800, 980)

    controller.expand()

    assert panel.at == anchor_panel_to_orb((1800, 980), PANEL, area=AREA)
    assert controller.position == panel.at


def test_the_panel_is_moved_before_it_is_shown(tmp_path: Path) -> None:
    """Otherwise it appears at its old place and then jumps, which reads as a
    glitch rather than a placement."""
    controller, panel, _orb = a_controller(tmp_path)

    controller.expand()

    moved = panel.calls.index("move_to")
    shown = panel.calls.index("unhide")
    assert moved < shown


def test_a_bad_anchor_does_not_trap_the_panel_collapsed(tmp_path: Path) -> None:
    """The anchor reads the work area from the system. A machine that refuses
    to answer must not cost the user their panel."""
    panel, orb = FakePanel(), FakeOrb()

    def broken(_at):
        raise RuntimeError("no work area")

    controller = BubbleController(
        view=panel, bridge=Bridge(), orb=orb, anchor=broken, speak_replies=False
    )
    controller.start(position_path=tmp_path / "p.json")

    assert controller.expand() is False
    assert panel.hidden is False


def test_a_controller_with_no_orb_still_works(tmp_path: Path) -> None:
    """The panel predates the orb and every path through it must still run."""
    panel = FakePanel()
    controller = BubbleController(view=panel, bridge=Bridge(), speak_replies=False)
    controller.start(position_path=tmp_path / "p.json")
    controller.submit("hello")
    controller.refresh_meter()
    controller.toggle_collapsed()
    controller.stop()

    assert panel.reply == "the answer"


def test_closing_shuts_both_windows(tmp_path: Path) -> None:
    controller, panel, orb = a_controller(tmp_path)

    controller.stop()

    assert panel.destroyed is True
    assert orb.closed is True


# --- 3. the state reaches the orb -------------------------------------------


def test_every_state_change_reaches_the_orb(tmp_path: Path) -> None:
    controller, _panel, orb = a_controller(tmp_path)
    orb.states.clear()

    controller.submit("hello")

    seen = [state for state, _unread in orb.states]
    assert "thinking" in seen
    assert "idle" in seen


def test_the_orb_gets_the_microphone_level_while_recording(tmp_path: Path) -> None:
    """The same number the panel's meter consumes, which is what makes the ring
    answer "is it hearing me" with no panel to look at."""
    controller, _panel, orb = a_controller(tmp_path)
    controller.state = BubbleState.RECORDING
    controller.note_level(2000.0)

    controller.refresh_meter()

    assert orb.levels, "the orb was never told the level"
    assert orb.levels[-1] > 0.5


def test_the_level_goes_to_zero_when_the_recording_stops(tmp_path: Path) -> None:
    """Otherwise the ring stays fat after the key is released."""
    controller, _panel, orb = a_controller(tmp_path)
    controller.state = BubbleState.RECORDING
    controller.note_level(2000.0)
    controller.refresh_meter()
    controller.state = BubbleState.IDLE

    controller.refresh_meter()

    assert orb.levels[-1] == 0.0


def test_the_status_line_names_the_painter(tmp_path: Path) -> None:
    """ITEM 1's requirement: the status says which one is running."""
    controller, _panel, orb = a_controller(tmp_path)
    orb.painter_description = lambda: "orb: flat disc (no layered windows)"

    assert "flat disc" in controller.status_line()


# --- 4. the unread ring ------------------------------------------------------


def test_a_reply_arriving_collapsed_and_unspoken_leaves_an_amber_ring(
    tmp_path: Path,
) -> None:
    controller, _panel, orb = a_controller(tmp_path, speak_replies=False)

    controller.submit("anything")

    assert controller.unread is True
    assert orb.unread_shown is True


def test_a_spoken_reply_leaves_no_ring(tmp_path: Path) -> None:
    """It was heard. The ring is for replies nobody encountered."""
    controller, _panel, orb = a_controller(
        tmp_path, speak_replies=True, speaker=Speaker()
    )

    controller.submit("anything")

    assert controller.unread is False
    assert orb.unread_shown is False


def test_speech_that_silently_fell_back_to_printing_counts_as_unheard(
    tmp_path: Path,
) -> None:
    """The engine reports rather than raises. "fallback" means it printed
    instead of speaking, so nobody heard it and the ring is owed."""
    controller, _panel, _orb = a_controller(
        tmp_path, speak_replies=True, speaker=Speaker(status="fallback")
    )

    controller.submit("anything")

    assert controller.unread is True


def test_an_expanded_panel_never_sets_the_ring(tmp_path: Path) -> None:
    """The reply is on screen. There is nothing unread about it."""
    controller, _panel, orb = a_controller(tmp_path, speak_replies=False)
    controller.expand()

    controller.submit("anything")

    assert controller.unread is False
    assert orb.unread_shown is False


def test_expanding_clears_the_ring(tmp_path: Path) -> None:
    controller, _panel, orb = a_controller(tmp_path, speak_replies=False)
    controller.submit("anything")
    assert controller.unread is True

    controller.expand()

    assert controller.unread is False
    assert orb.unread_shown is False


def test_the_ring_does_not_time_out(tmp_path: Path) -> None:
    """Nothing clears it but opening the panel. Checked by driving everything
    else that happens afterwards -- states, levels, another reply -- and
    finding it still set."""
    controller, _panel, orb = a_controller(tmp_path, speak_replies=False)
    controller.submit("first")

    for _ in range(50):
        controller.refresh_meter()
    controller._enter(BubbleState.IDLE)
    controller.note_key_seen()
    controller.submit("second")

    assert controller.unread is True
    assert orb.unread_shown is True


def test_a_failed_reply_keeps_the_error_colour_rather_than_going_amber(
    tmp_path: Path,
) -> None:
    """Amber would replace a louder signal with a quieter one: the orb is
    already red, and red says more than "unread" does."""
    controller, _panel, orb = a_controller(
        tmp_path, bridge=Bridge(Reply("that did not work", failed=True))
    )

    controller.submit("anything")

    assert controller.state is BubbleState.ERROR
    assert controller.unread is False
    assert orb.states[-1] == ("error", False)


def test_the_ring_survives_until_the_panel_opens_even_across_a_restart(
    tmp_path: Path,
) -> None:
    """Deliberately not persisted: a reply read in a previous session is not
    unread, and a ring restored from disk would be a lie about a reply the
    panel no longer holds."""
    controller, _panel, _orb = a_controller(tmp_path, speak_replies=False)
    controller.submit("anything")
    assert controller.unread is True
    controller.stop()

    again, _panel2, orb2 = a_controller(tmp_path, speak_replies=False)

    assert again.unread is False
    assert orb2.unread_shown is False
