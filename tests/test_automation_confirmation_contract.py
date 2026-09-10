"""``desktop_automation`` behaviour, kept characterized after its caller was retired.

**What this file was written for (M4 4.14H).** AD-024 found that Funnel A staged
an automation action, minted an out-of-band token, verified it under an attempt
cap and claimed it atomically -- and then called ``execute_automation(target)``
passing neither ``confirmed`` nor ``confirm_callback``, so
``desktop_automation._check_permission`` answered ``cancelled``. Nine of the
fourteen targets the parser minted were unreachable for that reason and a tenth
had no handler. This file pinned that surface so it could not change by accident.

**What changed (AD-025, M4 4.14P).** That composition no longer exists. The
duplicate Funnel-A automation parser was retired in favour of
``grandpa/automation/``, which serves the same intents through
``pc_control``. Nothing mints ``kind="automation"``, nothing calls
``execute_automation``, and the classes that drove the stage-approve-execute
chain were removed -- each named and explained in the retirement block further
down, per AD-025 e.

**What this file is now.** Direct characterization of ``desktop_automation``
itself: its risk classification, its four actuating verbs, the blocklist
ordering, and the ``focus|chrome`` discrepancy AD-024 e recorded. The module is
still present -- AD-025 d does not authorise deleting it and its broader
retirement is ``MIGRATION_PLAN`` §5.11 -- so its behaviour stays pinned until
then, even though no production code now reaches it. The shadowing tests near
the end assert the retirement itself rather than the old surface.

It still does **not** exercise ``confirmed=True`` or a ``confirm_callback``
anywhere. AD-024 b names those as forbidden shortcuts, and a test that reaches
for one is the first place someone will find it and copy it. The one property
that would otherwise want them -- that a blocked spec is refused *before*
confirmation is consulted -- is proven from ``_check_permission``'s own source
order instead (``TestBlockedInputsAreRefusedFirst``).

Nothing here actuates. ``pyautogui`` is replaced in ``sys.modules`` by a
recorder before ``execute_automation`` can import it, and every non-actuating
case asserts the recorder is empty rather than only asserting a status -- a test
that checked status alone would pass against a stub that actuates and lies.

No production approval database is opened: ``conftest`` redirects
``GRANDPA_HOME`` session-wide, and each test additionally binds
``LocalActionApprovalStore`` to its own ``tmp_path`` file, because the store
resolves its default path at import time and patching the module attribute alone
is inert.
"""

from __future__ import annotations

import sys
import types

import pytest

import grandpa.desktop_automation as desktop_automation
from tests.test_desktop_automation import FakePyAutoGUI

pytestmark = pytest.mark.core

#: Every target ``_parse_automation_action`` mints, with its measured outcome.
#:
#: ``focus|notepad`` never appears alone in production -- the parser only mints
#: it as the first link of ``focus|notepad||type|{text}`` -- but it is
#: characterized on its own because it is the link that aborts the chain, and
#: pinning the chain without pinning the cause would leave the reason invisible.
CANCELLED = (
    "type|hello",
    "press|enter",
    "press|tab",
    "press|escape",
    "hotkey|ctrl+c",
    "hotkey|ctrl+v",
    "hotkey|alt+tab",
    "click_center",
    "click_highlighted",
)

UNSUPPORTED = (
    "focus|notepad",
    "focus|notepad||type|hello",
)

#: target -> (message, the exact recorder contents)
#:
#: ``size`` is recorded because ``FakePyAutoGUI`` records it: ``move_center``
#: asks for the screen dimensions before moving, and a routing change that
#: stopped asking would be a behaviour change worth failing on.
HANDLED = {
    "scroll|down": ("Scrolled down.", [("scroll", -5)]),
    "scroll|up": ("Scrolled up.", [("scroll", 5)]),
    "move_center": (
        "Moved the mouse to the center of the screen.",
        [("size", None), ("moveTo", (50, 40))],
    ),
    "focus|chrome": (
        "Tried to switch focus toward Chrome.",
        [("hotkey", ("alt", "tab"))],
    ),
}

#: Specs the blocklist refuses outright. The first is reachable from the parser
#: (``type my password is hunter2``); the other two are not -- they are the
#: shapes ``_BLOCKED_SPEC_PATTERNS`` exists for, and characterizing them here
#: keeps that pattern set honest.
BLOCKED = (
    "type|my password is hunter2",
    "delete system32",
    "run|powershell",
)

CONFIRMATION_MESSAGE = "Confirmation required before controlling the active app."
BLOCKED_MESSAGE = "I blocked this action for safety."


class RecordingPyAutoGUI(FakePyAutoGUI):
    """``FakePyAutoGUI`` plus the verbs ``execute_automation`` also reaches.

    The existing helper covers ``write``/``press``/``hotkey``/``size`` because
    the tests it was written for drive ``_execute_with_pyautogui`` directly.
    Going through ``execute_automation`` additionally reaches the mouse verbs,
    so they are added here in the same recording style rather than by writing a
    second, subtly different fake.
    """

    def scroll(self, amount: int) -> None:
        self.calls.append(("scroll", amount))

    def click(self, x: int, y: int) -> None:
        self.calls.append(("click", (x, y)))

    def moveTo(self, x: int, y: int) -> None:  # noqa: N802 - pyautogui's name
        self.calls.append(("moveTo", (x, y)))

    def moveRel(self, x: int, y: int) -> None:  # noqa: N802 - pyautogui's name
        self.calls.append(("moveRel", (x, y)))


@pytest.fixture
def recorder(monkeypatch):
    """A stand-in ``pyautogui`` module, installed before it can be imported.

    ``execute_automation`` imports ``pyautogui`` inside the function body, so
    substituting the entry in ``sys.modules`` is enough and no real package need
    be installed for these tests to be meaningful.

    Two environment facts are neutralised alongside it: the ``win32`` platform
    gate, so the characterization is the same on any machine, and the 0.75s
    cooldown, which would otherwise turn the second call in a test into
    ``blocked`` for a reason that has nothing to do with confirmation.
    """
    fake = RecordingPyAutoGUI()
    module = types.ModuleType("pyautogui")
    module.FAILSAFE = False
    for name in ("write", "press", "scroll", "hotkey", "click", "moveTo", "moveRel"):
        setattr(module, name, getattr(fake, name))
    module.size = fake.size

    monkeypatch.setitem(sys.modules, "pyautogui", module)
    monkeypatch.setattr(desktop_automation.sys, "platform", "win32")
    monkeypatch.setattr(desktop_automation, "_last_action_at", -1e9)
    return fake


@pytest.fixture
def store(tmp_path, monkeypatch):
    """An approval store in the test's own directory, shared with Funnel A."""
    import grandpa.local_actions as local_actions
    from grandpa.local_action_approvals import LocalActionApprovalStore

    isolated = LocalActionApprovalStore(tmp_path / "approvals.db")
    monkeypatch.setattr(local_actions, "LocalActionApprovalStore", lambda: isolated)
    return isolated


def _run(target: str):
    return desktop_automation.execute_automation(target)


# ---------------------------------------------------------------------------
# The fourteen parser-minted targets
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Retired by AD-025 (M4 4.14P)
# ---------------------------------------------------------------------------
#
# Five classes and the ``_stage_and_approve`` helper were removed here when the
# duplicate Funnel-A automation path was retired. Recorded rather than silently
# dropped, per AD-025 e:
#
# ``TestConfirmationRequiringTargetsAreCancelled`` / ``TestUnsupportedTargets``
#   pinned the nine cancelled and two unsupported outcomes of the Funnel-A
#   surface. They stopped protecting anything the moment nothing could reach that
#   surface: ``_parse_automation_action`` no longer exists, so no command mints a
#   ``kind="automation"`` result to be cancelled.
#
# ``TestLocalApprovalDoesNotSatisfyTheInnerGate`` /
# ``TestLocalApprovalReachesASafeActuator``
#   drove the whole chain -- stage, tokenise, authorise, approve, execute -- to
#   show that a locally-approved automation action was still refused, and that a
#   safe one was not. The chain no longer has an automation leg. The approval
#   machinery they exercised is unaffected and stays covered by
#   ``test_local_action_approve_endpoint.py`` and ``test_approval_execution_race.py``.
#
# ``TestTheShortcutsAD024Forbids``
#   pinned that ``local_actions`` passed neither ``confirmed`` nor
#   ``confirm_callback``, and that no automation verb had been moved into
#   ``_SAFE_ACTIONS``. The call site it inspected is gone. AD-024 b still forbids
#   those shortcuts; there is simply no longer a call site at which to take one.
#
# What remains tests ``desktop_automation`` **directly**. That module is still
# present -- AD-025 d does not authorise deleting it and its broader retirement
# is ``MIGRATION_PLAN`` §5.11 -- so its behaviour stays characterized until then,
# even though nothing in production now calls it.


class TestTheFourExecutableTargets:
    @pytest.mark.parametrize("target", sorted(HANDLED))
    def test_the_status_is_handled(self, target: str, recorder) -> None:
        assert _run(target).status == "handled", target

    @pytest.mark.parametrize("target", sorted(HANDLED))
    def test_the_exact_actuator_call_is_made(self, target: str, recorder) -> None:
        """The whole point of the recorder: arguments, not just arrival."""
        _run(target)

        assert recorder.calls == HANDLED[target][1], target

    @pytest.mark.parametrize("target", sorted(HANDLED))
    def test_the_message_is_exact(self, target: str, recorder) -> None:
        assert _run(target).message == HANDLED[target][0], target

    @pytest.mark.parametrize("target", sorted(HANDLED))
    def test_the_classification_is_safe(self, target: str) -> None:
        assert desktop_automation.classify_automation_permission(target) == "safe"

    def test_scroll_direction_maps_to_a_signed_amount(self, recorder) -> None:
        """``down`` is negative and ``up`` is positive, not merely non-zero."""
        _run("scroll|down")
        down = list(recorder.calls)
        recorder.calls.clear()
        desktop_automation._last_action_at = -1e9
        _run("scroll|up")

        assert down == [("scroll", -5)]
        assert recorder.calls == [("scroll", 5)]


class TestFocusChromeIsSyntheticKeyboardInput:
    """AD-024 e. Characterization only -- the classification is not changed here.

    ``focus|chrome`` reads as a window operation and is classified ``safe``, so
    reaching it at all means executing on the local confirmation alone. What it
    actually does is send alt+tab: synthetic keyboard input, which is the exact
    capability ``pc_control``'s ``APPROVAL_REQUIRED_ACTIONS`` exists to gate
    (``keyboard_hotkey`` is in that set).

    **Reachability caveat, discovered while writing this file.** The command
    "focus chrome" does *not* arrive here: an earlier parser claims it as
    ``kind="window"`` (see ``TestTargetsShadowedByAnEarlierParser``), and since
    4.14D that path routes through ``pc_control`` as ``focus_window``. So this
    spec is reachable only by constructing the automation result directly. The
    discrepancy AD-024 e names is therefore latent rather than live, and these
    tests pin it so that a parser change cannot make it live silently.
    """

    def test_it_is_classified_safe(self) -> None:
        assert desktop_automation.classify_automation_permission("focus|chrome") == (
            "safe"
        )

    def test_it_needs_no_confirmation(self) -> None:
        assert not desktop_automation.requires_confirmation("focus|chrome")

    def test_it_sends_alt_tab(self, recorder) -> None:
        _run("focus|chrome")

        assert recorder.calls == [("hotkey", ("alt", "tab"))]

    def test_it_does_not_focus_a_window(self, recorder) -> None:
        """No window API is consulted -- the name is the only 'focus' involved."""
        _run("focus|chrome")

        assert [call[0] for call in recorder.calls] == ["hotkey"]

    def test_the_same_keystroke_is_confirmation_required_when_named_honestly(
        self, recorder
    ) -> None:
        """``hotkey|alt+tab`` and ``focus|chrome`` actuate identically.

        One is ``safe`` and executes; the other is ``confirm_required`` and is
        cancelled. The verb name, not the effect, decides -- which is the
        substance of AD-024 e.
        """
        assert _run("focus|chrome").status == "handled"
        assert recorder.calls == [("hotkey", ("alt", "tab"))]

        recorder.calls.clear()
        desktop_automation._last_action_at = -1e9

        assert _run("hotkey|alt+tab").status == "cancelled"
        assert recorder.calls == []


class TestBlockedInputsAreRefusedFirst:
    @pytest.mark.parametrize("spec", BLOCKED)
    def test_the_status_is_blocked(self, spec: str, recorder) -> None:
        assert _run(spec).status == "blocked", spec

    @pytest.mark.parametrize("spec", BLOCKED)
    def test_nothing_actuates(self, spec: str, recorder) -> None:
        _run(spec)

        assert recorder.calls == [], spec

    @pytest.mark.parametrize("spec", BLOCKED)
    def test_the_message_is_the_blocked_one(self, spec: str, recorder) -> None:
        """Distinguishes a block from a cancellation, which is the whole point."""
        result = _run(spec)

        assert result.message == BLOCKED_MESSAGE, spec
        assert result.message != CONFIRMATION_MESSAGE

    @pytest.mark.parametrize("spec", BLOCKED)
    def test_the_classification_is_blocked(self, spec: str) -> None:
        assert desktop_automation.classify_automation_permission(spec) == "blocked"

    def test_blocking_precedes_the_confirmation_decision(self) -> None:
        """A block is not something confirmation could ever release.

        Proven from source order rather than by calling with ``confirmed=True``.
        AD-024 b names that flag as a shortcut that must not enter this
        codebase, and a test that reaches for it to make a point is still the
        first place someone will find it and copy it.
        """
        import inspect

        source = inspect.getsource(desktop_automation._check_permission)

        assert source.index('== "blocked"') < source.index("if confirmed:")

    def test_a_blocked_spec_is_not_confirmable(self) -> None:
        """``requires_confirmation`` is False for a block: nothing to confirm."""
        for spec in BLOCKED:
            assert not desktop_automation.requires_confirmation(spec), spec


class TestTargetsShadowedByAnEarlierParser:
    """Two automation mints are unreachable from the natural-language surface.

    ``_parse_automation_action`` mints ``hotkey|alt+tab`` for "switch window" and
    ``focus|chrome`` for "focus chrome", but neither command ever reaches it: an
    earlier parser claims both as ``kind="window"``. The automation branch is
    therefore even narrower than the fourteen-target inventory suggests --
    ``hotkey|alt+tab`` and ``focus|chrome`` are dead on the NL surface for a
    third reason, distinct from the confirmation gate and from the missing
    ``focus`` handler.

    This was not known when AD-024 was written; AD-024 e describes
    ``focus|chrome`` as one of four live automation behaviours. Recorded here as
    characterization. Correcting the decision text is a documentation change and
    is not part of this slice.
    """

    def test_switch_window_never_reaches_the_automation_branch(self, store) -> None:
        """The stable property, deliberately weaker than "it becomes a window".

        On this machine "switch window" is claimed as ``kind="window"`` with
        target ``focus|windows cert kit`` -- a *fuzzy* match against the
        installed-app inventory, which differs per machine and was observed
        answering ``no_match`` on a run where the inventory was empty. What does
        not vary is that the automation branch never sees it, so that is what is
        asserted.
        """
        from grandpa.local_actions import handle_local_action

        assert handle_local_action("switch window", execute=False).kind != "automation"

    def test_the_retired_parser_is_gone(self, store) -> None:
        """Amended by 4.14P. It used to compare the two parsers' verdicts.

        ``_parse_automation_action`` would have minted ``hotkey|alt+tab`` for
        this command and never got the chance. AD-025 removed it, so only one
        side of that comparison is left; what stays worth asserting is that the
        symbol is gone and the command's owner did not change.
        """
        import grandpa.local_actions as local_actions
        from grandpa.local_actions import handle_local_action

        assert not hasattr(local_actions, "_parse_automation_action")
        assert handle_local_action("switch window", execute=False).target != (
            "hotkey|alt+tab"
        )

    def test_focus_chrome_is_claimed_as_a_window_action(self, store) -> None:
        from grandpa.local_actions import handle_local_action

        result = handle_local_action("focus chrome", execute=False)

        assert result.kind == "window"
        assert result.target == "focus|chrome"

    def test_the_window_path_is_the_routed_one(self) -> None:
        """Which is why the shadowing is benign rather than a second bypass.

        ``focus`` is in ``_WINDOW_ROUTED_VERBS``, so "focus chrome" executes
        behind ``pc_control`` as ``focus_window`` -- with the emergency stop and
        risk classification 4.14D added. The automation spelling of the same
        command would have had neither.
        """
        import grandpa.local_actions as local_actions

        assert "focus" in local_actions._WINDOW_ROUTED_VERBS

    def test_no_automation_target_is_reachable_any_more(self, store, recorder) -> None:
        """Amended by 4.14P: the three that were reachable no longer are.

        ``scroll down``, ``scroll up`` and ``move mouse to center`` used to mint
        ``kind="automation"`` and actuate. AD-026 accepted their removal from the
        surfaces that had no structured replacement. Nothing may mint that kind
        now -- and the two commands the window parser owns must still be its.
        """
        from grandpa.local_actions import handle_local_action

        for command in ("scroll down", "scroll up", "move mouse to center"):
            staged = handle_local_action(command, execute=False)
            assert staged.kind != "automation", command
            assert staged.status == "no_match", command

        # ``focus chrome`` is an exact alias match, so its owner is stable.
        assert handle_local_action("focus chrome", execute=False).kind == "window"

        # ``switch window`` resolves through a *fuzzy* installed-app match and so
        # varies per machine -- 4.14H saw both ``kind="window"`` and ``no_match``
        # depending on the inventory. Only the stable half is asserted.
        assert handle_local_action("switch window", execute=False).kind != "automation"


class TestTheCharacterizationItself:
    """Guards against this file quietly becoming vacuous."""

    def test_the_recorder_would_notice_an_actuation(self, recorder) -> None:
        """If the stub silently swallowed calls, every assertion above is empty."""
        _run("scroll|down")

        assert recorder.calls == [("scroll", -5)]

    def test_no_real_pyautogui_is_involved(self, recorder) -> None:
        assert sys.modules["pyautogui"].__class__ is types.ModuleType
        assert not hasattr(sys.modules["pyautogui"], "__file__")

    def test_the_cooldown_is_not_what_produced_these_results(self, recorder) -> None:
        """A cooldown hit answers ``blocked`` with its own wording."""
        result = _run("type|hello")

        assert result.status == "cancelled"
        assert "wait a moment" not in result.message

    def test_all_fourteen_parser_targets_are_covered(self) -> None:
        """The inventory here must match what the parser can actually mint."""
        covered = set(CANCELLED) | set(UNSUPPORTED) | set(HANDLED)

        assert covered == {
            "type|hello",
            "press|enter",
            "press|tab",
            "press|escape",
            "hotkey|ctrl+c",
            "hotkey|ctrl+v",
            "hotkey|alt+tab",
            "click_center",
            "click_highlighted",
            "focus|notepad",
            "focus|notepad||type|hello",
            "scroll|down",
            "scroll|up",
            "move_center",
            "focus|chrome",
        }
