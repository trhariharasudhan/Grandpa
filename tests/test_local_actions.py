from __future__ import annotations

import pytest

import grandpa.local_actions as local_actions
from grandpa.local_action_approvals import LocalActionApprovalStore
from grandpa.local_actions import BLOCKED_MESSAGE, handle_local_action

# ...and out of the default-deny actuation fixture (tests/actuation_guard.py).
pytestmark = [
    pytest.mark.core,
    pytest.mark.real_actions(
        reason="drives the real desktop service, with the OS-level calls under it stubbed or recorded by the test"
    ),
]


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

    # Opening a site is a browser action: parsed, then held for confirmation.
    assert result.status == "requires_confirmation"
    assert result.kind == "url"
    assert result.target == "https://www.youtube.com"
    assert "https://www.youtube.com" in result.message


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
    # Worded by the application service since "open <app>" moved onto the
    # action layer; what matters is that it says so and starts nothing.
    assert "only supported on Windows" in result.message


def test_google_search_command_is_allowlisted_without_execution():
    result = handle_local_action("Search Google for FastAPI", execute=False)

    assert result.status == "requires_confirmation"
    assert result.kind == "browser"
    assert result.target == "https://www.google.com/search?q=fastapi"


def test_youtube_search_command_is_allowlisted_without_execution():
    result = handle_local_action(
        "open youtube and search for python tutorials",
        execute=False,
    )

    assert result.status == "requires_confirmation"
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
    # A dry run describes the question; it stages nothing to answer it.
    assert result.pending_action is None


def test_the_deleted_browser_stub_phrases_are_no_longer_routes() -> None:
    """form_fill| and download| were stubs: nothing ever filled or downloaded.

    They asked for confirmation and then did nothing, which is worse than not
    offering the capability -- the person agreed to something that never
    happened. The phrases now fall through to the assistant.
    """
    for command in ("fill search with python", "download this file"):
        result = handle_local_action(command, execute=False)

        assert result.should_fallback, f"{command} still routes to a stub"


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


def test_type_command_is_allowlisted_without_execution():
    result = handle_local_action("type hello", execute=False)

    assert result.status == "requires_confirmation"
    assert result.permission == "requires_confirmation"
    assert result.kind == "automation"
    assert result.target == "type|hello"
    # A dry run describes the question; it stages nothing to answer it.
    assert result.pending_action is None
    assert "typing into the active app" in result.message
    assert "Permission:" not in result.message


def test_type_in_notepad_command_focuses_app_before_typing():
    result = handle_local_action("type hello in notepad", execute=False)

    assert result.status == "requires_confirmation"
    assert result.permission == "requires_confirmation"
    assert result.kind == "automation"
    assert result.target == "focus|notepad||type|hello"
    # A dry run describes the question; it stages nothing to answer it.
    assert result.pending_action is None
    assert "controlling the active app" in result.message


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


def _deferred_rows():
    from grandpa import pc_control

    with pc_control._connect_approval_db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT action_id, status, decision, origin FROM pc_control_approvals "
                "WHERE consent = 'deferred'"
            ).fetchall()
        ]


def test_pending_action_can_be_denied(tmp_path):
    # Not "type hello" any more: synthetic input is never staged for a later
    # yes, because a keystroke goes wherever focus is when it is sent.
    pending = handle_local_action(f"open {tmp_path}", deferred_origin="chat")
    denied = handle_local_action("cancel", deferred_origin="chat")

    assert pending.status == "requires_confirmation"
    assert denied.status == "cancelled"
    assert [(row["action_id"], row["status"]) for row in _deferred_rows()] == [
        (pending.pending_action["id"], "rejected")
    ]


def test_expired_pending_action_is_not_approved(monkeypatch, tmp_path):
    from grandpa import pc_control

    pending = handle_local_action(f"open {tmp_path}", deferred_origin="chat")
    later = pending.pending_action["expires_at"] + 1
    monkeypatch.setattr(pc_control.time, "time", lambda: later)
    approved = local_actions.approve_pending_action(origin="chat")

    assert approved.status == "unsupported"
    assert "no pending local action" in approved.message
    assert [row["status"] for row in _deferred_rows()] == ["expired"]


def test_unknown_url_requires_confirmation():
    result = handle_local_action("open https://example.com", execute=False)

    assert result.status == "requires_confirmation"
    assert result.kind == "url"
    assert result.permission == "requires_confirmation"


# --- a category is not an application -----------------------------------------
#
# A multi-word application name donates its last word as an alias, which is how
# "Google Chrome" answers to "chrome". For a category word that is wrong: on a
# real inventory "show my files" resolved to "VLC media player ... and cache
# files" with full confidence and launched it without asking, "open my desktop"
# resolved to Docker Desktop, and "show my apps" to "Documentation for Desktop
# Apps".


@pytest.mark.parametrize(
    "phrase",
    [
        "show my windows",
        "show windows",
        "show my files",
        "show my apps",
        "show my screen",
        "open my desktop",
    ],
)
def test_a_category_word_does_not_resolve_to_an_application(phrase: str) -> None:
    from grandpa.local_actions import handle_local_action

    result = handle_local_action(phrase, execute=False)

    assert result.status == "no_match", result
    assert result.kind != "app"


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("open notepad", "notepad"),
        ("open chrome", "chrome"),
        ("open calculator", "calculator"),
    ],
)
def test_real_applications_still_resolve(phrase: str, expected: str) -> None:
    from grandpa.local_actions import handle_local_action

    result = handle_local_action(phrase, execute=False)

    assert result.kind == "app"
    assert expected in (result.target or "")


def test_a_category_word_that_is_also_an_app_name_still_resolves() -> None:
    """Settings is a real application, and the guard only skips the loose rules."""
    from grandpa.local_actions import handle_local_action

    result = handle_local_action("open settings", execute=False)

    assert result.kind == "app"


@pytest.mark.parametrize(
    "phrase", ["open google.com", "open example.com", "open github.com"]
)
def test_a_domain_is_opened_as_an_address_not_guessed_as_an_app(phrase: str) -> None:
    """It used to answer "Did you mean Google Chrome?" for google.com, and
    nothing at all for example.com -- the same phrasing behaving differently
    depending on what happened to be installed."""
    from grandpa.local_actions import handle_local_action

    result = handle_local_action(phrase, execute=False)

    assert result.kind == "url"
    assert result.target.startswith("https://")
    assert result.permission == "requires_confirmation"


def test_a_bare_ip_is_not_guessed_at() -> None:
    from grandpa.local_actions import handle_local_action

    assert handle_local_action("open 192.168.1.1", execute=False).status == "no_match"


def test_generic_last_words_are_not_recorded_as_aliases() -> None:
    from grandpa.apps.resolver import generate_aliases

    assert "files" not in generate_aliases("VLC media player and cache files")
    assert "desktop" not in generate_aliases("Docker Desktop")
    assert "apps" not in generate_aliases("Documentation for Desktop Apps")
    # ... while the ones that name a product still are.
    assert "chrome" in generate_aliases("Google Chrome")
    assert "studio" in generate_aliases("Android Studio")
