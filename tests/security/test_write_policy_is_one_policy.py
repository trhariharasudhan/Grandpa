"""pc_control's writes and the catalogue's agree, action by action.

Every tranche of this phase has found the same shape of bug: two routes to one
capability, each with its own idea of what to ask. The writes -- volume,
brightness, the screen lock, power, files, windows -- are reachable two ways:

  the action layer          chat's desktop route, the tool loop, natural_actions
  pc_control's own door     voice operator mode (DesktopParser -> run_local_action)
                            and the HTTP pc-control endpoints

Comparing them today, the tiers agree everywhere and neither lets through
something the other asks about. That is worth keeping true by a test rather
than by having checked once: this one fails if a tier is changed on one side,
or if an action the catalogue asks about stops being gated at pc_control's door.

Anything that actuates runs under tests.security.input_recorder. Writing this
file, a probe without it set a real machine's volume to 30% and locked its
screen, because the recorder covered only keys, mouse and launches.
"""

from __future__ import annotations

import pytest

from grandpa import pc_control
from grandpa.action_layer.catalogue import get
from tests.security.input_recorder import install


def _pc_control_tier(name: str) -> str | None:
    if name in pc_control.BLOCKED_ACTIONS:
        return "BLOCKED"
    if name in pc_control.HIGH_RISK_ACTIONS:
        return "HIGH"
    if name in pc_control.MEDIUM_RISK_ACTIONS:
        return "MEDIUM"
    if name in pc_control.LOW_RISK_ACTIONS:
        return "LOW"
    return None


def _catalogued(name: str):
    """The catalogue's entry, or None when it deliberately excludes the action."""
    try:
        return get(name)
    except KeyError:
        # EXCLUSIONS: blocked in pc_control, or a stub that never completes.
        return None


def _shared_actions() -> list[str]:
    """Actions both sides know about."""
    named = (
        pc_control.LOW_RISK_ACTIONS
        | pc_control.MEDIUM_RISK_ACTIONS
        | pc_control.HIGH_RISK_ACTIONS
    )
    return sorted(name for name in named if _catalogued(name) is not None)


@pytest.fixture
def recorder(monkeypatch, tmp_path):
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    return install(monkeypatch)


def test_the_two_sides_share_actions_to_compare() -> None:
    """Guards the enumeration: an empty list would pass everything below."""
    shared = _shared_actions()

    assert "volume_set" in shared
    assert "system_shutdown" in shared
    assert len(shared) >= 20, shared


@pytest.mark.parametrize("action", _shared_actions())
def test_both_sides_rate_a_write_the_same(action) -> None:
    spec = _catalogued(action)

    assert _pc_control_tier(action) == spec.risk.value, (
        f"{action}: pc_control says {_pc_control_tier(action)}, "
        f"the catalogue says {spec.risk.value}"
    )


@pytest.mark.parametrize("action", _shared_actions())
def test_nothing_the_layer_asks_about_runs_unasked_at_pc_controls_door(action) -> None:
    """The looser side is the one that matters, so neither may be looser."""
    spec = _catalogued(action)
    if not spec.requires_confirmation:
        return

    gated = (
        action in pc_control.APPROVAL_REQUIRED_ACTIONS
        or _pc_control_tier(action) in {"HIGH", "BLOCKED"}
        or action in pc_control.INLINE_CONSENT_ACTIONS
    )
    assert gated, (
        f"{action} needs confirmation on the layer, and pc_control would run it "
        "with nobody asked"
    )


@pytest.mark.parametrize(
    "action", ["system_shutdown", "system_restart", "system_sleep", "empty_recycle_bin"]
)
def test_a_high_risk_write_cannot_complete_from_a_spoken_phrase(
    recorder, action
) -> None:
    """Voice operator mode reaches this door; it has no approval code."""
    result = pc_control.run_local_action({"action_type": action, "target": ""})

    assert result.status == "approval_required"
    assert recorder.actuated == [], recorder.calls


def test_a_low_risk_write_completes_on_both_routes_without_asking(recorder) -> None:
    """Not a hole: both sides rate volume LOW and ask nothing. Pinned so that
    a change on one side alone shows up as a failure here."""
    from grandpa.action_layer.executor import execute
    from grandpa.action_layer.model import ActionRequest, Origin

    spec = _catalogued("volume_set")
    assert spec.requires_confirmation is False

    through_pc_control = pc_control.run_local_action(
        {"action_type": "volume_set", "target": "30"}
    )
    through_the_layer = execute(
        ActionRequest(
            "volume_set",
            {"level": 30},
            origin=Origin.USER_CHAT,
            risk=spec.risk,
            requires_confirmation=spec.requires_confirmation,
        ),
        None,
    )

    assert through_pc_control.ok is True
    assert through_the_layer.success is True
    # Recorded twice, performed never.
    assert recorder.actuated == ["power.execute_volume", "power.execute_volume"]
