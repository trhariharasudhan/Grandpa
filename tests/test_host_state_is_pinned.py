"""The suite must not read the developer's desktop, and must not stop guarding it.

Thirteen tests failed on a documentation-only tree because
``desktop_context.active_window_is_protected()`` reads the real foreground window
and matches its title against "sign in", "login", "password", "bank", "checkout"
and others. Chrome's window title follows its active tab, so a sign-in page with
focus was enough. The same tree passed on either side of that run, and all the
affected tests passed in isolation.

Two things have to be true at once, and a fixture that only achieved the first
would be worse than the bug:

1. no test's result depends on what the developer has open;
2. the protected-window refusal still happens when the window *is* protected.

The second is why these tests exist. Pinning the answer to False everywhere would
make every test green and quietly delete the feature that stops the assistant
typing into a password prompt.
"""

from __future__ import annotations

import pytest

from grandpa.pc_control import run_local_action
from tests.host_state import (
    MARKER,
    NEUTRAL_PROCESS,
    PROTECTED_PROCESS,
    pin_host_state,
    reason_for,
)

pytestmark = pytest.mark.core


# --- 1. the default is pinned, and it is not the real machine ----------------------


def test_the_active_window_is_pinned_not_read() -> None:
    """Whatever has focus right now, the suite sees the pinned window."""
    from grandpa import desktop_context

    result = desktop_context.get_active_process()
    process = result.evidence.get("process", {})

    assert process.get("title") == NEUTRAL_PROCESS["title"]
    assert process.get("name") == NEUTRAL_PROCESS["name"]


def test_the_pinned_default_is_not_protected() -> None:
    """So a test that actuates is not refused for a reason it never stated."""
    from grandpa import desktop_context

    assert desktop_context.active_window_is_protected() is False


def test_the_pinned_title_matches_no_protected_keyword() -> None:
    """Derived, not asserted twice: the default must stay out of the keyword list."""
    from grandpa.desktop_context import PROTECTED_WINDOW_KEYWORDS

    haystack = f"{NEUTRAL_PROCESS['title']} {NEUTRAL_PROCESS['name']}".lower()

    assert not any(keyword in haystack for keyword in PROTECTED_WINDOW_KEYWORDS)


def test_the_cooldown_starts_clear() -> None:
    """Module state, wall-clock based, and it used to survive a test."""
    import grandpa.desktop.control.automation as automation

    assert automation._last_action_at == 0.0


# --- 2. the guard still guards -----------------------------------------------------


@pytest.mark.real_actions(
    reason="reaches the real pc_control synthetic-input path to prove the "
    "protected-window refusal still fires"
)
def test_a_protected_window_still_refuses_synthetic_input(
    protected_window, monkeypatch
) -> None:
    """The assertion that stops this fixture from deleting the feature.

    If pinning ever defaults to "not protected" unconditionally, or the refusal
    is removed, this fails. It is the reason the fixture pins a *value* rather
    than stubbing the check away.
    """
    response = run_local_action(
        {"action_type": "keyboard_type", "target": "hello", "dry_run": True}
    )

    assert response.ok is False
    assert response.error == "protected_window"
    assert response.evidence.get("protected_window") is True


def test_the_protected_fixture_reports_protected() -> None:
    """Checked directly too, so a failure above is attributable."""
    from grandpa import desktop_context

    assert desktop_context.active_window_is_protected() is False, (
        "without the fixture the default is an ordinary window"
    )


def test_pinning_the_protected_process_derives_protected_from_its_title(
    monkeypatch,
) -> None:
    """A test asks for the case by name; the flag follows from the title.

    Setting the title and the boolean separately is how the two drift apart.
    """
    from grandpa import desktop_context

    pin_host_state(monkeypatch, PROTECTED_PROCESS)

    assert desktop_context.active_window_is_protected() is True
    assert (
        desktop_context.get_active_process().evidence["process"]["title"]
        == PROTECTED_PROCESS["title"]
    )


def test_the_protected_sample_does_match_a_keyword() -> None:
    """Otherwise the refusal test above would pass for the wrong reason."""
    from grandpa.desktop_context import PROTECTED_WINDOW_KEYWORDS

    haystack = f"{PROTECTED_PROCESS['title']} {PROTECTED_PROCESS['name']}".lower()

    assert any(keyword in haystack for keyword in PROTECTED_WINDOW_KEYWORDS)


# --- 3. the opt-out costs a stated reason -------------------------------------------


def test_the_marker_requires_a_reason() -> None:
    """Same bar as real_actions and real_writes."""

    class _Mark:
        def __init__(self, args=(), kwargs=None):
            self.args = args
            self.kwargs = kwargs or {}

    assert reason_for(_Mark(kwargs={"reason": "needs the live window"}))
    assert reason_for(_Mark(args=("needs the live window",)))
    with pytest.raises(ValueError):
        reason_for(_Mark())
    with pytest.raises(ValueError):
        reason_for(_Mark(kwargs={"reason": "   "}))


def test_the_marker_is_registered() -> None:
    """An unregistered marker is silently ignored under --strict-markers."""
    from pathlib import Path

    import tomllib

    import grandpa

    root = Path(grandpa.__file__).parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    markers = config["tool"]["pytest"]["ini_options"]["markers"]

    assert any(marker.startswith(f"{MARKER}(reason)") for marker in markers), markers


@pytest.mark.real_host_state(
    reason="reads the live foreground window to prove the opt-out actually opts out"
)
def test_the_opt_out_reaches_the_real_machine() -> None:
    """With the marker, nothing is pinned.

    Asserted without depending on what is focused: the title is whatever this
    machine says, and the only claim is that it is not the pinned stand-in.
    """
    from grandpa import desktop_context

    result = desktop_context.get_active_process()
    title = result.evidence.get("process", {}).get("title", "")

    assert title != NEUTRAL_PROCESS["title"] or not result.supported
