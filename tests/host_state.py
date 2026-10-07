"""Live host state, pinned, so a test states what it needs.

Thirteen tests failed on a documentation-only tree because
``desktop_context.active_window_is_protected()`` reads the *real* foreground
window and matches its title against ``PROTECTED_WINDOW_KEYWORDS`` -- "sign in",
"login", "password", "bank", "checkout" and others. Chrome's window title follows
its active tab, so having a sign-in page focused while the suite runs is enough
to turn them red. The same tree passed on either side of that run.

The feature is correct and must keep working: an assistant that types into a
password prompt is the failure this prevents. What is wrong is tests inheriting
the answer from whatever the developer has open.

So the default is pinned here, and a test that cares about the protected case
says so -- the same shape as ``_nothing_actuates`` and its ``real_actions``
marker. The opt-out is ``@pytest.mark.real_host_state(reason=...)``, for a test
that genuinely needs to look at this machine.
"""

from __future__ import annotations

from typing import Any

MARKER = "real_host_state"

#: An ordinary window. Nothing in the title matches a protected keyword, and the
#: process is one the automation layer has no opinion about.
NEUTRAL_PROCESS: dict[str, Any] = {
    "title": "Untitled - Notepad",
    "name": "notepad.exe",
    "pid": 4242,
    "exe": r"C:\Windows\System32\notepad.exe",
}

#: The case the live failures hit. Available so a test can ask for it by name
#: rather than inventing a string and hoping it matches the keyword list.
PROTECTED_PROCESS: dict[str, Any] = {
    "title": "Sign in - Google Accounts - Google Chrome",
    "name": "chrome.exe",
    "pid": 4243,
    "exe": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
}


def reason_for(mark) -> str:
    """The marker needs a reason, like the other two guards' markers do."""
    reason = ""
    if mark.args:
        reason = str(mark.args[0])
    reason = str(mark.kwargs.get("reason", reason) or "").strip()
    if not reason:
        raise ValueError(
            f"@pytest.mark.{MARKER} needs a reason: what live host state does "
            f"this test need to read, and why can it not be stated?"
        )
    return reason


def pin_host_state(monkeypatch, process: dict[str, Any] | None = None) -> None:
    """Make every reader of the active window answer from *process*.

    Both consumers -- ``desktop.control.automation`` and ``pc_control`` -- import
    ``active_window_is_protected`` lazily inside the function that calls it, so
    patching the attribute on ``grandpa.desktop_context`` reaches both.
    ``get_active_process`` is pinned as well, because it is the source the
    protected check reads and other callers use it directly.
    """
    import grandpa.desktop_context as desktop_context

    chosen = dict(NEUTRAL_PROCESS if process is None else process)

    def fake_get_active_process(*_args, **_kwargs):
        from grandpa.desktop_context import DesktopContextResult

        return DesktopContextResult(
            True,
            "Pinned by tests/host_state.py.",
            {"process": dict(chosen)},
        )

    monkeypatch.setattr(
        desktop_context, "get_active_process", fake_get_active_process, raising=False
    )

    # Derived from the pinned process rather than hardcoded, so a test that pins
    # PROTECTED_PROCESS gets a True here without having to set both.
    haystack = f"{chosen.get('title', '')} {chosen.get('name', '')}".lower()
    protected = any(
        keyword in haystack for keyword in desktop_context.PROTECTED_WINDOW_KEYWORDS
    )
    monkeypatch.setattr(
        desktop_context,
        "active_window_is_protected",
        lambda: protected,
        raising=False,
    )


def reset_action_cooldown(monkeypatch) -> None:
    """Clear the module-level cooldown timestamp between tests.

    ``AutomationControlService`` refuses an action within
    ``_ACTION_COOLDOWN_SECONDS`` (0.35) of the last successful one, and the
    timestamp is module state that outlives a test. On a fast run a preceding
    test's action can still be inside that window.

    The timestamp is reset; ``_cooldown_remaining`` is deliberately *not*
    stubbed, because tests/security/test_synthetic_input_guards.py asserts the
    cooldown's own behaviour -- that a refusal does not start it and a completed
    action does. Stubbing the function would make those pass for the wrong
    reason.
    """
    import grandpa.desktop.control.automation as automation

    monkeypatch.setattr(automation, "_last_action_at", 0.0, raising=False)


__all__ = [
    "MARKER",
    "NEUTRAL_PROCESS",
    "PROTECTED_PROCESS",
    "pin_host_state",
    "reason_for",
    "reset_action_cooldown",
]
