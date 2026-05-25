from __future__ import annotations

import pytest

import grandpa.local_actions as local_actions
from grandpa.local_action_approvals import LocalActionApprovalStore
from grandpa.local_actions import BLOCKED_MESSAGE, handle_local_action


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


def test_screen_question_is_recognized_without_execution():
    result = handle_local_action("What is on my screen?", execute=False)

    assert result.status == "handled"
    assert result.kind == "screen"
    assert result.target == "screen_context"


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


def test_type_command_is_allowlisted_without_execution():
    result = handle_local_action("type hello", execute=False)

    assert result.status == "requires_confirmation"
    assert result.permission == "requires_confirmation"
    assert result.kind == "automation"
    assert result.target == "type|hello"
    assert result.pending_action


def test_enter_command_is_allowlisted_without_execution():
    result = handle_local_action("press enter", execute=False)

    assert result.status == "requires_confirmation"
    assert result.kind == "automation"
    assert result.target == "press|enter"


def test_copy_selected_text_is_allowlisted_without_execution():
    result = handle_local_action("copy selected text", execute=False)

    assert result.status == "requires_confirmation"
    assert result.kind == "automation"
    assert result.target == "hotkey|ctrl+c"


def test_destructive_desktop_command_is_blocked():
    result = handle_local_action("delete system32")

    assert result.status == "blocked"
    assert result.message == BLOCKED_MESSAGE


def test_pending_action_can_be_denied(_approval_store_fixture):
    store = _approval_store_fixture
    pending = handle_local_action("type hello", execute=False)
    denied = handle_local_action("cancel")

    assert pending.status == "requires_confirmation"
    assert denied.status == "cancelled"
    assert store.get_pending(pending.pending_action["id"])["status"] == "denied"


def test_expired_pending_action_is_not_approved(_approval_store_fixture):
    store = _approval_store_fixture
    pending = handle_local_action("type hello", execute=False)
    store.expire_old(now=pending.pending_action["expires_at"] + 1)
    approved = local_actions.approve_pending_action(pending.pending_action["id"])

    assert approved.status == "unsupported"
    assert "no longer available" in approved.message


def test_unknown_url_requires_confirmation():
    result = handle_local_action("open https://example.com", execute=False)

    assert result.status == "requires_confirmation"
    assert result.kind == "url"
    assert result.permission == "requires_confirmation"
