"""The default-deny fixture covers every catalogued implementation.

The fixture in tests/conftest.py is only as good as its list, and a list that
quietly stops covering something is how a test reaches a real machine. So this
checks the list against the catalogue itself, under the fixture, every run: if
an implementation is not replaced, this fails and names it.

That makes an action added later safe by construction. Whoever adds it writes a
catalogue entry -- that is what makes it an action at all -- and the entry is
where this test reads its work from.
"""

from __future__ import annotations

import pytest

from tests.actuation_guard import (
    MARKER,
    ActuationDenied,
    catalogued_targets,
    is_denied,
    primitive_targets,
    reason_for,
)


def test_every_catalogued_implementation_is_replaced() -> None:
    live = {
        label
        for label, (owner, attribute) in catalogued_targets().items()
        if not is_denied(owner, attribute)
    }

    assert live == set(), (
        "these catalogued implementations are live in a test: "
        f"{sorted(live)}. Nothing actuates by default -- see tests/actuation_guard.py."
    )


def test_every_primitive_is_replaced() -> None:
    live = {
        label
        for owner, attribute, label in primitive_targets()
        if not is_denied(owner, attribute)
    }

    assert live == set(), f"these primitives are live in a test: {sorted(live)}"


def test_the_lists_are_not_empty() -> None:
    """An empty enumeration would make every assertion above vacuous."""
    assert len(catalogued_targets()) >= 30
    assert len(primitive_targets()) >= 40


def test_a_denied_implementation_raises_through_broad_except() -> None:
    """The denial is a BaseException, so friendly error handling cannot eat it."""
    from grandpa.desktop.control.power import PowerControlService

    with pytest.raises(ActuationDenied):
        try:
            PowerControlService().execute_system("system_lock", platform="win32")
        except Exception:  # noqa: BLE001 - the point of the test
            pytest.fail("a broad except swallowed the denial")


def test_the_opt_out_marker_requires_a_reason() -> None:
    class _Marker:
        def __init__(self, args=(), kwargs=None) -> None:
            self.args = args
            self.kwargs = kwargs or {}

    assert reason_for(_Marker(kwargs={"reason": "drives a tmp_path store"})) == (
        "drives a tmp_path store"
    )
    assert reason_for(_Marker(args=("positional reason",))) == "positional reason"

    for empty in (_Marker(), _Marker(kwargs={"reason": "   "})):
        with pytest.raises(ValueError, match=f"{MARKER} needs a reason"):
            reason_for(empty)


@pytest.mark.real_actions(reason="checks that the marker really restores the real one")
def test_the_marker_gives_back_the_real_implementation() -> None:
    live = [
        label
        for label, (owner, attribute) in catalogued_targets().items()
        if not is_denied(owner, attribute)
    ]

    assert live, "the marker did not restore any real implementation"
