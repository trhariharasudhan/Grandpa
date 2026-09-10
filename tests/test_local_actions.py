from __future__ import annotations

import pytest

import grandpa.local_actions as local_actions
from grandpa.local_action_approvals import LocalActionApprovalStore
from grandpa.local_actions import BLOCKED_MESSAGE, handle_local_action

pytestmark = pytest.mark.core


@pytest.fixture(autouse=True)
def _approval_store_fixture(tmp_path, monkeypatch):
    store = LocalActionApprovalStore(tmp_path / "approvals.db")
    monkeypatch.setattr(local_actions, "LocalActionApprovalStore", lambda: store)
    return store


def test_safe_auto_run_command_is_allowed_without_execution():
    result = handle_local_action("open notepad", execute=False)

    assert result.status == "handled"
    assert result.permission == "allowed"


def test_safe_app_command_is_recognized_without_execution():
    result = handle_local_action("open notepad", execute=False)

    assert result.status == "handled"
    assert result.kind == "app"
    assert result.target == "notepad"
    assert result.message == "Opening Notepad."


def test_safe_url_command_is_recognized_without_execution():
    result = handle_local_action("open youtube", execute=False)

    assert result.status == "handled"
    assert result.kind == "url"
    assert result.target == "https://www.youtube.com"


def test_dangerous_command_is_blocked():
    result = handle_local_action("delete all files")

    assert result.status == "blocked"
    assert result.kind == "blocked"
    assert result.message == BLOCKED_MESSAGE


def test_unsupported_command_falls_back_to_assistant():
    result = handle_local_action("What is Python?")

    assert result.status == "no_match"
    assert result.should_fallback


def test_windows_launcher_action_is_unsupported_off_windows(monkeypatch):
    monkeypatch.setattr(local_actions.sys, "platform", "linux")

    result = handle_local_action("open calculator")

    assert result.status == "unsupported"
    assert result.kind == "app"
    assert "not supported" in result.message


def test_google_search_command_is_allowlisted_without_execution():
    result = handle_local_action("Search Google for FastAPI", execute=False)

    assert result.status == "handled"
    assert result.kind == "browser"
    assert result.target == "https://www.google.com/search?q=fastapi"


def test_youtube_search_command_is_allowlisted_without_execution():
    result = handle_local_action(
        "open youtube and search for python tutorials",
        execute=False,
    )

    assert result.status == "handled"
    assert result.kind == "browser"
    assert result.target.endswith("search_query=python+tutorials")


def test_browser_context_question_is_recognized_without_execution():
    result = handle_local_action("what page am I on?", execute=False)

    assert result.status == "handled"
    assert result.kind == "browser"
    assert result.target == "context|active"


def test_browser_dom_summary_is_recognized_without_execution():
    result = handle_local_action("summarize this webpage", execute=False)

    assert result.status == "handled"
    assert result.kind == "browser"
    assert result.target == "summary|visible"


def test_browser_links_command_is_recognized_without_execution():
    result = handle_local_action("show links on this page", execute=False)

    assert result.status == "handled"
    assert result.kind == "browser"
    assert result.target == "links|visible"


def test_browser_buttons_command_is_recognized_without_execution():
    result = handle_local_action("what buttons are visible?", execute=False)

    assert result.status == "handled"
    assert result.kind == "browser"
    assert result.target == "buttons|visible"


def test_browser_click_requires_confirmation():
    result = handle_local_action("click the first video", execute=False)

    assert result.status == "requires_confirmation"
    assert result.kind == "browser"
    assert result.permission == "requires_confirmation"
    assert result.pending_action


@pytest.mark.parametrize(
    ("command", "target", "message_part"),
    [
        (
            "fill search with python",
            "form_fill|search=python",
            "filling a browser field",
        ),
        ("download this file", "download|visible selection", "browser download"),
    ],
)
def test_browser_workflow_actions_require_confirmation(command, target, message_part):
    result = handle_local_action(command, execute=False)

    assert result.status == "requires_confirmation"
    assert result.kind == "browser"
    assert result.target == target
    assert result.permission == "requires_confirmation"
    assert result.pending_action
    assert message_part in result.message


def test_browser_high_risk_click_is_blocked():
    result = local_actions._with_permission(
        "click checkout",
        local_actions.LocalActionResult(
            status="handled",
            kind="browser",
            target="click|checkout payment button",
            message="Clicking checkout.",
            tts_text="Clicking checkout.",
        ),
    )

    assert result.status == "blocked"
    assert result.permission == "blocked"


def test_screen_question_is_recognized_without_execution():
    result = handle_local_action("What is on my screen?", execute=False)

    assert result.status == "handled"
    assert result.kind == "screen"
    assert result.target == "screen_context"


def test_screen_diagnostics_command_is_recognized_without_execution():
    result = handle_local_action("screen diagnostics", execute=False)

    assert result.status == "handled"
    assert result.kind == "screen"
    assert result.target == "screen_diagnostics"


def test_screenshot_command_is_unsupported_off_windows(monkeypatch):
    monkeypatch.setattr(local_actions.sys, "platform", "linux")

    result = handle_local_action("take a screenshot")

    assert result.status == "unsupported"
    assert result.kind == "screenshot"
    assert "not supported" in result.message


def test_purchase_browser_command_is_blocked():
    result = handle_local_action("open amazon and buy laptop")

    assert result.status == "blocked"
    assert result.message == BLOCKED_MESSAGE


# ``test_type_command_is_allowlisted_without_execution``,
# ``test_type_in_notepad_command_focuses_app_before_typing``,
# ``test_enter_command_is_allowlisted_without_execution`` and
# ``test_copy_selected_text_is_allowlisted_without_execution`` were retired by
# AD-025 (M4 4.14P). Each asserted that ``_parse_automation_action`` minted a
# ``kind="automation"`` result for ``type hello``, ``type hello in notepad``,
# ``press enter`` and ``copy selected text``. That parser is gone: the duplicate
# Funnel-A automation path was retired in favour of ``grandpa/automation/``,
# which serves the same intents through ``pc_control``.
#
# What each stopped protecting: the allowlist shape of a parser that no longer
# exists. What replaced it: ``test_the_retired_automation_commands_no_longer_
# match`` below, which pins that these commands now fall through rather than
# reaching some other actuator.


@pytest.mark.parametrize(
    "command",
    [
        "type hello",
        "type hello in notepad",
        "press enter",
        "press tab",
        "press escape",
        "copy selected text",
        "paste",
        "scroll down",
        "scroll up",
        "move mouse to center",
        "click the center of the screen",
        "click the highlighted button",
    ],
)
def test_the_retired_automation_commands_no_longer_match(command):
    """AD-025: the duplicate parser is gone and nothing else claimed them.

    Falling through is the intended outcome -- AD-026 accepted the removal of
    the three that used to actuate. What must not happen is a silent hand-off to
    a different actuator, which is what the ``kind`` assertion rules out.
    """
    result = handle_local_action(command, execute=False)

    assert result.status == "no_match", command
    assert result.kind != "automation"


def test_window_owned_commands_stay_window_owned():
    """The two shadowed commands were never automation's; they must not move."""
    for command in ("focus chrome", "close notepad"):
        result = handle_local_action(command, execute=False)
        assert result.kind == "window", command


def test_destructive_desktop_command_is_blocked():
    result = handle_local_action("delete system32")

    assert result.status == "blocked"
    assert result.message == BLOCKED_MESSAGE


def test_pending_action_can_be_denied(_approval_store_fixture):
    store = _approval_store_fixture
    pending = handle_local_action("close notepad", execute=False)
    denied = handle_local_action("cancel")

    assert pending.status == "requires_confirmation"
    assert denied.status == "cancelled"
    assert store.get_pending(pending.pending_action["id"])["status"] == "denied"


def test_expired_pending_action_is_not_approved(_approval_store_fixture):
    store = _approval_store_fixture
    pending = handle_local_action("close notepad", execute=False)
    store.expire_old(now=pending.pending_action["expires_at"] + 1)
    approved = local_actions.approve_pending_action(pending.pending_action["id"])

    assert approved.status == "unsupported"
    assert "no longer available" in approved.message


def test_unknown_url_requires_confirmation():
    result = handle_local_action("open https://example.com", execute=False)

    assert result.status == "requires_confirmation"
    assert result.kind == "url"
    assert result.permission == "requires_confirmation"
