"""Only voice may stage synthetic input against a focus witness.

A pre-existing defect, fixed before the thing that would have exposed it. When
the witness landed, ``run_parsed`` captured one for *any* caller that opted into
deferred consent -- ``voice``, ``chat`` and ``http`` alike. Nothing had gone wrong
yet only because no parsed phrase mapped to a synthetic action, so the branch was
unreachable. The moment one did, chat and the HTTP API would have gained the
deferred keystroke path with no change to either.

The comment at the capture site made the wrong argument out loud: voice earns
this "by having a witness, not by being voice". A capture succeeds for any caller
on a Windows desktop, so that reasoning gave the path to everyone.

The right rule is that a witness is one of three preconditions, and the other two
belong to the origin's loop rather than to the witness:

* redeemable on the next turn only -- needs a loop with turns;
* a spoken read-back naming the window -- needs a voice.

``voice`` has both, and cannot ask inline. ``chat`` *can* ask inline and does, so
the deferred path would replace stronger evidence with weaker. ``http`` has
neither turns nor a listener.

This file is deliberately about the origins that are refused, because the one
that is allowed is covered everywhere else.
"""

from __future__ import annotations

import pytest

from grandpa import pc_control
from grandpa.desktop import focus_witness
from tests.witness_support import make_witness, stub_capture

pytestmark = pytest.mark.core

ACTION = "keyboard_type"
PARAMETERS = {"text": "hello"}

#: Every origin that opts into deferred consent anywhere in the product, found by
#: grepping for deferred_origin=. If a new one appears it belongs in one list or
#: the other, and the test below says which.
DEFERRED_ORIGINS = ("voice", "chat", "http")
REFUSED_ORIGINS = ("chat", "http")


@pytest.fixture
def recorder(monkeypatch, tmp_path):
    import grandpa.desktop.control.automation as automation
    from tests.security.input_recorder import install

    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    monkeypatch.setattr(automation, "_last_action_at", 0.0)
    return install(monkeypatch)


@pytest.fixture
def mapped(monkeypatch):
    """A parsed shape mapping to keyboard_type, so the branch is reachable."""
    import grandpa.natural_actions as natural_actions

    monkeypatch.setitem(
        natural_actions.MIGRATED, ("automation", "probe"), (ACTION, PARAMETERS)
    )
    return natural_actions


def _pending() -> list[dict]:
    with pc_control._connect_approval_db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT action_type, origin, status, witness_json FROM "
                "pc_control_approvals WHERE status = 'pending'"
            ).fetchall()
        ]


def test_the_allowlist_is_exactly_voice() -> None:
    """Stated as a set, so widening it is a visible edit rather than a side effect."""
    assert focus_witness.WITNESS_ORIGINS == frozenset({"voice"})


@pytest.mark.parametrize("origin", REFUSED_ORIGINS)
def test_a_non_voice_origin_is_refused_and_stages_nothing(
    recorder, monkeypatch, mapped, origin: str
) -> None:
    """The defect, per origin. A capture is available; the origin still may not."""
    # The capture would succeed -- that is the whole point. If the allowlist were
    # gone, this reading is what chat would stage against.
    stub_capture(monkeypatch, [make_witness()])

    result = mapped.run_parsed("automation", "probe", deferred_origin=origin)

    assert result is not None, "the stand-in mapping did not take"
    assert result.status == "blocked", result
    assert result.pending_action is None, result
    assert _pending() == [], f"{origin} staged a keystroke: {_pending()}"
    assert [name for name in recorder.actuated if name.startswith("pyautogui.")] == []


@pytest.mark.parametrize("origin", REFUSED_ORIGINS)
def test_a_non_voice_origin_never_even_takes_a_reading(
    recorder, monkeypatch, mapped, origin: str
) -> None:
    """The allowlist is checked before the capture, not after.

    Reading the foreground window is a look at whatever the user has open. An
    origin that may not use the result has no business taking the reading, and
    checking afterwards would mean every HTTP request sampled the desktop.
    """
    captures: list[str] = []

    def capture(*, control_target: str = ""):
        captures.append(control_target)
        return make_witness()

    monkeypatch.setattr(focus_witness, "capture", capture)

    mapped.run_parsed("automation", "probe", deferred_origin=origin)

    assert captures == [], f"{origin} read the foreground window anyway"


def test_voice_is_allowed_so_the_test_above_is_not_vacuous(
    recorder, monkeypatch, mapped
) -> None:
    """Guards the guard: if nothing could stage, the refusals prove nothing."""
    stub_capture(monkeypatch, [make_witness()])

    result = mapped.run_parsed("automation", "probe", deferred_origin="voice")

    assert result.pending_action is not None, result
    rows = _pending()
    assert len(rows) == 1, rows
    assert rows[0]["origin"] == "voice"
    assert rows[0]["witness_json"]


def test_every_deferred_origin_is_accounted_for() -> None:
    """A new origin must be sorted into allowed or refused, not left unclassified.

    Enumerated from the product rather than from this file, so an origin added
    with deferred_origin= somewhere new shows up here as an unclassified name.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "grandpa"
    found = set()
    for path in root.rglob("*.py"):
        for match in re.finditer(
            r'deferred_origin\s*=\s*"([a-z_]+)"', path.read_text(encoding="utf-8")
        ):
            found.add(match.group(1))

    assert found, "no deferred_origin= literals found -- did the keyword move?"
    unclassified = found - set(DEFERRED_ORIGINS)
    assert not unclassified, (
        f"these origins opt into deferred consent but this test does not say "
        f"whether they may carry a witness: {sorted(unclassified)}. Add each to "
        f"REFUSED_ORIGINS, or to focus_witness.WITNESS_ORIGINS with the argument "
        f"that it has turns, a read-back, and no inline channel."
    )


def test_non_voice_origins_keep_their_non_synthetic_deferred_actions(
    recorder, monkeypatch
) -> None:
    """The allowlist is about synthetic input only.

    Chat stages folders and URLs for a later yes and must go on doing so; a
    change that quietly took that away would be a regression dressed as a
    hardening.
    """
    from grandpa.local import handle_local_action

    result = handle_local_action("open my downloads folder", deferred_origin="chat")

    assert result.status in {"requires_confirmation", "handled"}, result
    if result.status == "requires_confirmation":
        rows = _pending()
        assert rows, "chat lost its ordinary deferred consent"
        assert rows[0]["witness_json"] == "", (
            "a non-synthetic row should carry no witness"
        )
