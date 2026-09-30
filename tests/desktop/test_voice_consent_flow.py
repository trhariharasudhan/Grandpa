"""Staging a keystroke, and the three things that must hold before it is sent.

The witness answers "is this still the screen you approved?". This file covers
the rest of the consent model:

* **the turn window** -- redeemable only on the turn immediately after staging.
  Counted, not timed: a turn has no fixed duration, so seconds are either too few
  for a slow model call or too many to mean "the screen you were just looking
  at". The store's existing TTL stays the single wall-clock backstop.
* **one re-ask** -- a mismatch discards, re-stages against the new reading and
  says so, once. A second mismatch refuses aloud and drops it, because a window
  that changes every turn would otherwise become an endless prompt, and that is
  how "yes" becomes a reflex.
* **the spoken read-back** -- with no screen it is the confirmation interface, so
  the wording is asserted verbatim.

Every capture is stubbed (tests/witness_support), so nothing here depends on
which window happens to be in front of whoever runs the suite.
"""

from __future__ import annotations

import pytest
from tests.witness_support import make_witness, stub_capture

from grandpa import deferred_actions, pc_control
from grandpa.desktop.kernel import approvals

pytestmark = pytest.mark.core

ACTION = "keyboard_type"
PARAMETERS = {"text": "hello"}


@pytest.fixture
def recorder(monkeypatch, tmp_path):
    """Actuators replaced, so a successful redemption is recorded, not typed."""
    from tests.security.input_recorder import install

    import grandpa.desktop.control.automation as automation

    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    monkeypatch.setattr(automation, "_last_action_at", 0.0)
    return install(monkeypatch)


@pytest.fixture
def mapped(monkeypatch):
    """A parsed shape that maps to a synthetic action.

    No real phrase maps to one, which is why this branch was unreachable before
    the witness. Every test of it needs a stand-in.
    """
    import grandpa.natural_actions as natural_actions

    monkeypatch.setitem(
        natural_actions.MIGRATED, ("automation", "probe"), (ACTION, PARAMETERS)
    )
    return natural_actions


def _stage(mapped):
    return mapped.run_parsed("automation", "probe", deferred_origin="voice")


def _pending() -> list[dict]:
    with pc_control._connect_approval_db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT action_id, action_type, status, witness_json, "
                "staged_turn_seq, reask_count FROM pc_control_approvals "
                "WHERE status = 'pending'"
            ).fetchall()
        ]


def _typed(recorder) -> list[str]:
    return [name for name in recorder.actuated if name.startswith("pyautogui.")]


# --- item 2: the turn window ------------------------------------------------------


@pytest.mark.real_actions(
    reason="drives the real AutomationControlService so the approved keystroke "
    "reaches an actuator; input_recorder has replaced pyautogui, so it is "
    "recorded rather than typed"
)
def test_the_next_turn_redeems(recorder, monkeypatch, mapped) -> None:
    """Stage on turn N, yes on turn N+1, keystroke sent."""
    stub_capture(monkeypatch, [make_witness(), make_witness()])
    staged = _stage(mapped)
    assert staged.pending_action is not None

    approvals.bump_turn("voice")  # the staging turn ends
    result = deferred_actions.approve(origin="voice")

    assert result.status == "handled", result
    assert _typed(recorder), "the approved keystroke was not sent"
    assert _pending() == [], "the row was not consumed"


def test_the_turn_after_does_not_redeem(recorder, monkeypatch, mapped) -> None:
    """A yes two turns late is about something the user has moved on from.

    Dropped rather than left pending: a row that survives is a row some later
    "yes" can drain.
    """
    stub_capture(monkeypatch, [make_witness()])
    _stage(mapped)

    approvals.bump_turn("voice")
    approvals.bump_turn("voice")
    result = deferred_actions.approve(origin="voice")

    assert result.status == "blocked", result
    assert "too late" in result.tts_text
    assert _typed(recorder) == []
    assert _pending() == [], "a stale row was left for a later yes to find"


def test_the_same_turn_does_not_redeem(recorder, monkeypatch, mapped) -> None:
    """current == staged is not staged + 1. The ask and the yes are two turns."""
    stub_capture(monkeypatch, [make_witness()])
    _stage(mapped)

    result = deferred_actions.approve(origin="voice")

    assert result.status == "blocked", result
    assert _typed(recorder) == []


def test_a_stalled_loop_is_caught_by_the_existing_ttl(
    recorder, monkeypatch, mapped
) -> None:
    """The wall-clock backstop, for a loop that never completes another turn.

    The turn counter cannot expire a row on its own: if the loop stalls, the turn
    never advances and ``current == staged + 1`` stays false forever -- but a
    crash-and-restart could leave the counter where the row expects it. The TTL
    already in the store covers that, and it is the only wall-clock value: no
    second expiry was added.
    """
    stub_capture(monkeypatch, [make_witness()])
    _stage(mapped)
    approvals.bump_turn("voice")

    # Age the row past the store's one TTL.
    with pc_control._connect_approval_db() as conn:
        conn.execute(
            "UPDATE pc_control_approvals SET expires_at = ? WHERE status = 'pending'",
            (0.0,),
        )
        conn.commit()

    result = deferred_actions.approve(origin="voice")

    assert result.status == "unsupported", result
    assert "no pending" in result.message.lower()
    assert _typed(recorder) == []


def test_there_is_still_exactly_one_expiry_value() -> None:
    """One store, one expiry policy. The turn check is a precondition, not a TTL."""
    assert pc_control.PENDING_TTL_SECONDS == 300
    source = pc_control.__file__.replace(".pyc", ".py") if pc_control.__file__ else ""
    text = open(source, encoding="utf-8").read() if source else ""
    # No second TTL constant crept in beside it.
    assert text.count("PENDING_TTL_SECONDS = ") == 1
    assert "TTL_SECONDS_2" not in text
    assert "WITNESS_TTL" not in text


def test_a_turn_bump_is_per_origin(monkeypatch) -> None:
    """Voice's turns are voice's. Another origin's activity must not expire them."""
    approvals.bump_turn("voice")
    approvals.bump_turn("chat")
    approvals.bump_turn("chat")

    assert approvals.current_turn("voice") == 1
    assert approvals.current_turn("chat") == 2


# --- item 3: one re-ask ------------------------------------------------------------


def test_a_mismatch_re_asks_against_the_new_window(
    recorder, monkeypatch, mapped
) -> None:
    stub_capture(
        monkeypatch,
        [make_witness(), make_witness(exe_path=r"c:\chrome.exe", title="Tab - Chrome")],
    )
    _stage(mapped)
    approvals.bump_turn("voice")

    result = deferred_actions.approve(origin="voice")

    assert result.status == "requires_confirmation", result
    assert _typed(recorder) == [], "a mismatched action typed something"
    rows = _pending()
    assert len(rows) == 1, rows
    assert rows[0]["reask_count"] == 1
    assert rows[0]["witness_json"], "the re-staged row has no witness"


@pytest.mark.real_actions(
    reason="drives the real AutomationControlService for the re-approved "
    "keystroke; input_recorder has replaced pyautogui, so it is recorded"
)
def test_the_re_asked_action_can_then_be_approved(
    recorder, monkeypatch, mapped
) -> None:
    """The re-ask is a real offer, not a dead end."""
    chrome = make_witness(exe_path=r"c:\chrome.exe", title="Tab - Chrome")
    stub_capture(monkeypatch, [make_witness(), chrome, chrome])
    _stage(mapped)
    approvals.bump_turn("voice")
    deferred_actions.approve(origin="voice")  # mismatch -> re-ask

    approvals.bump_turn("voice")
    result = deferred_actions.approve(origin="voice")

    assert result.status == "handled", result
    assert _typed(recorder), "the re-approved keystroke was not sent"


def test_a_second_mismatch_refuses_and_drops_it(recorder, monkeypatch, mapped) -> None:
    """The property that stops "yes" becoming a reflex.

    A window changing every turn must not produce an endless prompt. One re-ask,
    then it stops asking and the user has to say it again deliberately.
    """
    stub_capture(
        monkeypatch,
        [
            make_witness(),
            make_witness(exe_path=r"c:\chrome.exe", title="Tab - Chrome"),
            make_witness(exe_path=r"c:\cmd.exe", title="Command Prompt"),
        ],
    )
    _stage(mapped)
    approvals.bump_turn("voice")
    first = deferred_actions.approve(origin="voice")
    assert first.status == "requires_confirmation"

    approvals.bump_turn("voice")
    second = deferred_actions.approve(origin="voice")

    assert second.status == "blocked", second
    assert "stopped asking" in second.tts_text
    assert _typed(recorder) == []
    assert _pending() == [], "a third prompt is still waiting"


def test_the_loop_cannot_repeat(recorder, monkeypatch, mapped) -> None:
    """Driven to exhaustion: no sequence of yeses produces a third prompt."""
    stub_capture(
        monkeypatch,
        [
            make_witness(),
            make_witness(exe_path=r"c:\a.exe"),
            make_witness(exe_path=r"c:\b.exe"),
        ],
    )
    _stage(mapped)

    prompts = 0
    for _ in range(6):
        approvals.bump_turn("voice")
        result = deferred_actions.approve(origin="voice")
        if result.status == "requires_confirmation":
            prompts += 1

    assert prompts == 1, f"the re-ask repeated {prompts} times"
    assert _typed(recorder) == []
    assert _pending() == []


def test_max_reasks_is_one() -> None:
    """Stated as a constant so the intent is not inferred from a loop bound."""
    assert deferred_actions.MAX_REASKS == 1


def test_a_failed_capture_at_redemption_refuses_without_re_asking(
    recorder, monkeypatch, mapped
) -> None:
    """Nothing to re-ask against: there is no new window to offer instead."""
    stub_capture(monkeypatch, [make_witness(), None])
    _stage(mapped)
    approvals.bump_turn("voice")

    result = deferred_actions.approve(origin="voice")

    assert result.status == "blocked", result
    assert "could not tell which window" in result.tts_text
    assert _typed(recorder) == []
    assert _pending() == []


# --- item 4: the spoken read-back --------------------------------------------------


def test_the_staging_read_back_names_the_window(monkeypatch, mapped) -> None:
    stub_capture(monkeypatch, [make_witness(title="Untitled - Notepad")])

    staged = _stage(mapped)

    assert staged.tts_text == (
        "Typing hello into Notepad, the window titled Untitled - Notepad. "
        "Say yes to send those keystrokes, or cancel."
    )


def test_the_mismatch_read_back_says_what_did_not_happen_first(
    recorder, monkeypatch, mapped
) -> None:
    stub_capture(
        monkeypatch,
        [
            make_witness(title="Untitled - Notepad"),
            make_witness(exe_path=r"c:\chrome.exe", title="New Tab - Chrome"),
        ],
    )
    _stage(mapped)
    approvals.bump_turn("voice")

    result = deferred_actions.approve(origin="voice")

    assert result.tts_text == (
        "The window changed since you asked - it is Chrome now, not Notepad. "
        "I did not type anything. Say yes to type hello into Chrome instead, "
        "or cancel."
    )
    # What did not happen comes before what is offered.
    said = result.tts_text
    assert said.index("did not type") < said.index("Say yes")


def test_the_application_is_always_named(recorder, monkeypatch, mapped) -> None:
    """Across staging, re-ask and refusal: a prompt that cannot be checked is no prompt."""
    stub_capture(
        monkeypatch,
        [
            make_witness(),
            make_witness(exe_path=r"c:\chrome.exe"),
            make_witness(exe_path=r"c:\cmd.exe"),
        ],
    )
    staged = _stage(mapped)
    assert "notepad" in staged.tts_text.casefold()

    approvals.bump_turn("voice")
    reask = deferred_actions.approve(origin="voice")
    assert "chrome" in reask.tts_text.casefold()
    assert "notepad" in reask.tts_text.casefold()

    approvals.bump_turn("voice")
    refused = deferred_actions.approve(origin="voice")
    assert "did not type anything" in refused.tts_text


def test_the_three_designed_wordings_verbatim() -> None:
    """The exact sentences the design specified, asserted as sentences.

    Driven through the read-back module directly rather than through a staging
    call, because two of the three are for actions no parsed shape maps to and
    the wording is the deliverable here.
    """
    from grandpa.desktop import consent_readback

    outlook = make_witness(exe_path=r"c:\office\OUTLOOK.EXE", title="Untitled Message")
    assert consent_readback.ask(
        "keyboard_type", {"text": "transfer approved"}, outlook
    ) == (
        "Typing transfer approved into Outlook, the window titled Untitled "
        "Message. Say yes to send those keystrokes, or cancel."
    )

    explorer = make_witness(exe_path=r"c:\windows\explorer.exe", title="Downloads")
    assert consent_readback.ask(
        "mouse_click", {"control": "Delete button", "x": 820, "y": 540}, explorer
    ) == (
        "Clicking the Delete button at 820 across and 540 down in Explorer, the "
        "window titled Downloads. Say yes to click, or cancel."
    )

    notepad = make_witness(title="Untitled - Notepad")
    chrome = make_witness(exe_path=r"c:\chrome.exe", title="New Tab - Chrome")
    assert consent_readback.reask(
        "keyboard_type", {"text": "hello"}, notepad, chrome
    ) == (
        "The window changed since you asked - it is Chrome now, not Notepad. "
        "I did not type anything. Say yes to type hello into Chrome instead, "
        "or cancel."
    )


def test_the_read_back_is_present_continuous(monkeypatch, mapped) -> None:
    """ "Typing X" is about to happen; "Shall I type X" invites a yes to a maybe."""
    stub_capture(monkeypatch, [make_witness()])

    staged = _stage(mapped)

    assert staged.tts_text.startswith("Typing ")
    for hedge in ("Shall I", "Would you like", "Do you want"):
        assert hedge not in staged.tts_text
