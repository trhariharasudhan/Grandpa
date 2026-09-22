"""Voice's desktop actions go through the action layer, not around it.

Voice Operator Mode used to call ``pc_control.run_local_action`` directly. The
tiers on the two sides agreed when they were compared, so nothing was wrong
that day -- but it was the last door to a catalogued capability with its own
policy behind it, and every hole this phase has found had that shape.

Nothing actuates in these tests: reaching a real implementation raises
ActuationDenied (tests/actuation_guard.py), which is what "it got through"
looks like here, and a refusal is the absence of that.
"""

from __future__ import annotations

import pytest

from tests.actuation_guard import ActuationDenied


def _run(action: str, target: str = "", **args):
    from grandpa.voice.layer_runner import run_through_the_layer

    return run_through_the_layer(
        {"action_type": action, "target": target, "args": args}
    )


def test_the_operators_default_runner_is_the_layer() -> None:
    import grandpa.voice.operator as operator
    from grandpa.voice.layer_runner import run_through_the_layer

    assert operator.run_local_action is run_through_the_layer


def test_voice_cannot_shut_the_machine_down() -> None:
    """HIGH actions ask, and a spoken turn cannot be asked."""
    result = _run("system_shutdown")

    assert result.ok is False
    assert result.status == "approval_required"


def test_voice_cannot_close_a_window_without_being_asked() -> None:
    result = _run("close_app", "notepad")

    assert result.ok is False
    assert result.status == "approval_required"


def test_voice_cannot_type() -> None:
    """Synthetic input needs someone who can be asked; voice is not."""
    result = _run("keyboard_type", text="hello")

    assert result.ok is False
    assert result.status in {"approval_required", "blocked"}


def test_an_uncatalogued_action_is_refused_rather_than_sent_to_pc_control() -> None:
    result = _run("shell_run", "dir")

    assert result.ok is False
    assert result.status == "unsupported"
    assert "shell run" in result.message


def test_a_low_risk_action_reaches_its_implementation() -> None:
    """The route works: volume asks nothing on either side, so it gets through.

    Built from the parser, the way the operator builds it -- a hand-written
    payload would not carry what the parser puts in args, and would prove that
    the translation is wrong rather than that the route works.

    ActuationDenied is the proof it got through: it comes from the stand-in
    that replaced the real implementation, at the point the real one would run.
    """
    from grandpa.desktop.automation import DesktopParser
    from grandpa.voice.layer_runner import run_through_the_layer

    parsed = DesktopParser().parse("set volume to 30")
    assert parsed is not None and parsed.pc_action_type == "volume_set"

    with pytest.raises(ActuationDenied, match="PowerControlService.execute_volume"):
        run_through_the_layer(
            {
                "action_type": parsed.pc_action_type,
                "target": parsed.target,
                "args": dict(parsed.args or {}),
            }
        )


def test_a_dry_run_says_so_and_reaches_nothing() -> None:
    from grandpa.voice.layer_runner import run_through_the_layer

    result = run_through_the_layer(
        {
            "action_type": "volume_set",
            "target": "30",
            "args": {"level": 30},
            "dry_run": True,
        }
    )

    assert result.status == "dry_run"
    assert result.ok is True
