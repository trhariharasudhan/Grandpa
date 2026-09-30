"""No shipped phrase maps to an action the automation service implements.

This is the fact that keeps two other guards honest, and it is invisible unless
something says it out loud.

``natural_actions.run_parsed`` will stage a synthetic-input action for a deferred
origin when a focus witness can be taken. That branch exists, is tested, and is
**unreachable from any phrase Grandpa ships**: ``request_for`` resolves a parsed
shape through ``MIGRATED``, ``_PREFIXED`` and ``_BY_KIND``, and none of them
yields an action whose implementation is the automation service. Every test of
that branch has to install a stand-in mapping to reach it.

Two consequences, both of which look like coincidences until you know this:

* ``tests/security/test_voice_confirmation.py``'s tranche guard still passes
  unchanged after voice consent landed. Not because the consent path refuses --
  it does not -- but because voice's phrases never get there. Screen Automation
  V2 answers first with ``allow_input=False``, and for the one phrase that does
  reach the layer the mapping is absent so nothing stages.
* ``tests/security/test_no_staged_input.py``'s sweep over real phrases finds no
  pending rows for the same reason.

So the day someone maps a phrase onto a synthetic action -- which is a reasonable
thing to want -- this test fails and points at the two guards whose meaning
changes at that moment. It is not here to forbid the mapping. It is here so the
mapping cannot be made by accident, and so whoever makes it reads this first.
"""

from __future__ import annotations

import pytest

from grandpa.action_layer.catalogue import AUTOMATION_IMPLEMENTATION, get
from grandpa.natural_actions import _BY_KIND, _PREFIXED, MIGRATED

pytestmark = pytest.mark.core

#: A probe target for the callables in _BY_KIND and _PREFIXED, which build a
#: mapping from the phrase's own text.
_PROBE = "probe-target"


def _action_of(mapped: object) -> str:
    """The catalogued action name a mapping yields, or "" if it yields none."""
    if mapped is None:
        return ""
    try:
        name = mapped[0]  # type: ignore[index]
    except (TypeError, IndexError, KeyError):
        return ""
    return str(name)


def _is_synthetic(action: str) -> bool:
    if not action:
        return False
    try:
        spec = get(action)
    except KeyError:
        return False
    return getattr(spec, "implementation", "") == AUTOMATION_IMPLEMENTATION


def _resolve(entry: object) -> str:
    """Resolve a mapping table value, whether it is a pair or a builder."""
    try:
        return _action_of(entry(_PROBE) if callable(entry) else entry)
    except Exception:  # noqa: BLE001 - a builder that cannot build maps nothing
        return ""


def test_the_mapping_tables_are_not_empty() -> None:
    """Guards the guard: empty tables would make the checks below vacuous."""
    assert MIGRATED, "MIGRATED is empty -- did the mapping move?"
    assert _BY_KIND, "_BY_KIND is empty"
    assert _PREFIXED, "_PREFIXED is empty"


def test_no_exact_mapping_yields_a_synthetic_action() -> None:
    offenders = {
        key: _resolve(value)
        for key, value in MIGRATED.items()
        if _is_synthetic(_resolve(value))
    }

    assert offenders == {}, _message(offenders)


def test_no_kind_or_prefix_mapping_yields_a_synthetic_action() -> None:
    offenders: dict[object, str] = {}
    for key, build in list(_BY_KIND.items()) + list(_PREFIXED.items()):
        action = _resolve(build)
        if _is_synthetic(action):
            offenders[key] = action

    assert offenders == {}, _message(offenders)


def test_the_automation_actions_exist_to_be_found() -> None:
    """The other half: the actions are catalogued, so the checks can bite.

    If _is_synthetic never returned True for anything, the two tests above would
    pass against a catalogue with no input actions in it at all.
    """
    assert _is_synthetic("keyboard_type")
    assert _is_synthetic("mouse_click")
    assert not _is_synthetic("open_folder")


def _message(offenders: dict) -> str:
    return (
        f"a shipped phrase now maps to synthetic input: {offenders}.\n"
        "That is not forbidden, but two guards change meaning the moment it is "
        "true, and both should be re-read rather than assumed:\n"
        "  * tests/security/test_voice_confirmation.py -- its tranche guard "
        "asserts voice actuates no keys or mouse by any route. Voice's phrases "
        "are refused by Screen Automation V2 today; a mapping may route around "
        "it into the witness path, which can send a keystroke on a matching "
        "witness.\n"
        "  * tests/security/test_no_staged_input.py -- its sweep over real "
        "phrases finds no pending rows today. With a mapping it will find some, "
        "and each must carry a witness.\n"
        "If the mapping is intended, update both and this file's docstring."
    )
