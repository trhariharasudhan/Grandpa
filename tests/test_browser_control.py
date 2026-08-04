from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.browser_control import (
    BrowserContextStore,
    execute_browser_action,
    extract_dom_snapshot,
    get_visible_browser_context,
)
from grandpa.server.routes import router


@pytest.fixture(autouse=True)
def _isolated_browser_db(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_BROWSER_DB", str(tmp_path / "browser_context.db"))


def test_dom_extraction_redacts_password_inputs():
    html = """
    <html><body>
      <h1>Python Tutorials</h1>
      <a href="/watch?v=1">First video</a>
      <button>Play</button>
      <input type="password" name="secret">
      <input type="text" placeholder="Search">
    </body></html>
    """

    context = extract_dom_snapshot(html, title="YouTube", url="https://youtube.com")

    assert context.supported is True
    assert context.headings == ("Python Tutorials",)
    assert context.links[0]["text"] == "First video"
    assert context.buttons == ("Play",)
    assert context.inputs == ({"label": "Search", "type": "text"},)


def test_visible_context_uses_explicit_local_dom_payload(monkeypatch):
    payload = {
        "title": "Example Page",
        "url": "https://example.test",
        "headings": ["Welcome"],
        "visible_text": "Welcome. This page explains safe browser context.",
    }
    monkeypatch.setattr("grandpa.browser_control.sys.platform", "win32")
    monkeypatch.setattr(
        "grandpa.browser_control._active_window_title",
        lambda: "Example Page - Google Chrome",
    )
    monkeypatch.setenv("GRANDPA_BROWSER_CONTEXT_JSON", json.dumps(payload))

    context = get_visible_browser_context()

    assert context.supported is True
    assert context.browser == "Chrome"
    assert context.title == "Example Page"
    assert context.url == "https://example.test"
    assert context.headings == ("Welcome",)


def test_visible_context_requires_visible_browser(monkeypatch):
    monkeypatch.setattr("grandpa.browser_control.sys.platform", "win32")
    monkeypatch.setattr(
        "grandpa.browser_control._active_window_title", lambda: "Notes - Notepad"
    )

    context = get_visible_browser_context()

    assert context.supported is False
    assert "Chrome or Edge" in context.message


def test_summary_requires_dom_text(monkeypatch):
    monkeypatch.setattr("grandpa.browser_control.sys.platform", "win32")
    monkeypatch.setattr(
        "grandpa.browser_control._active_window_title",
        lambda: "Example - Google Chrome",
    )
    monkeypatch.delenv("GRANDPA_BROWSER_CONTEXT_JSON", raising=False)

    result = execute_browser_action("summary", "visible")

    assert result.status == "unsupported"
    assert "readable page text" in result.message


def test_summary_uses_visible_text(monkeypatch):
    monkeypatch.setattr("grandpa.browser_control.sys.platform", "win32")
    monkeypatch.setattr(
        "grandpa.browser_control._active_window_title",
        lambda: "Example - Google Chrome",
    )
    monkeypatch.setenv(
        "GRANDPA_BROWSER_CONTEXT_JSON",
        json.dumps({"visible_text": "One. Two. Three. Four.", "title": "Example"}),
    )

    result = execute_browser_action("summary", "visible")

    assert result.status == "handled"
    assert "One. Two. Three." in result.message


def test_click_requires_confirmation():
    result = execute_browser_action("click", "first video")

    assert result.status == "requires_confirmation"
    assert result.risk_level == "MEDIUM"


def test_unsafe_browser_action_is_blocked():
    result = execute_browser_action("click", "checkout payment button")

    assert result.status == "blocked"
    assert result.risk_level == "BLOCKED"


def test_browser_context_store_records_recent_activity(tmp_path):
    store = BrowserContextStore(tmp_path / "browser.db")

    store.record("search", title="Search", url="https://example.test", query="python")

    recent = store.recent()
    assert recent[0]["action"] == "search"
    assert recent[0]["query"] == "python"


def test_safe_form_fill_requires_confirmation(monkeypatch):
    monkeypatch.setattr("grandpa.browser_control.sys.platform", "win32")
    monkeypatch.setattr(
        "grandpa.browser_control._active_window_title", lambda: "Search - Google Chrome"
    )

    result = execute_browser_action("form_fill", "search=python")

    assert result.status == "requires_confirmation"
    assert result.risk_level == "MEDIUM"


def test_sensitive_form_fill_blocked():
    result = execute_browser_action("form_fill", "password=hunter2")

    assert result.status == "blocked"
    assert result.risk_level == "BLOCKED"


def test_download_requires_confirmation():
    result = execute_browser_action("download", "visible link")

    assert result.status == "requires_confirmation"
    assert result.risk_level == "MEDIUM"


def test_browser_diagnostics_reports_visible_context(monkeypatch):
    monkeypatch.setattr("grandpa.browser_control.sys.platform", "win32")
    monkeypatch.setattr(
        "grandpa.browser_control._active_window_title", lambda: "Docs - Google Chrome"
    )
    monkeypatch.setenv(
        "GRANDPA_BROWSER_CONTEXT_JSON",
        json.dumps(
            {
                "title": "Docs",
                "url": "https://example.test",
                "headings": ["Overview"],
                "buttons": ["Continue"],
                "links": [{"text": "Setup", "href": "https://example.test/setup"}],
            }
        ),
    )

    result = execute_browser_action("diagnostics", "browser")
    details = json.loads(result.target)

    assert result.status == "handled"
    assert details["context_available"] is True
    assert details["capture_source"] == "visible_context"
    assert details["counts"]["headings"] == 1


def test_visible_context_redacts_sensitive_values(monkeypatch):
    monkeypatch.setattr("grandpa.browser_control.sys.platform", "win32")
    monkeypatch.setattr(
        "grandpa.browser_control._active_window_title",
        lambda: "Checkout - Google Chrome",
    )
    monkeypatch.setenv(
        "GRANDPA_BROWSER_CONTEXT_JSON",
        json.dumps(
            {
                "title": "Checkout",
                "url": "https://example.test",
                "inputs": [
                    {"type": "password", "label": "Password"},
                    {"type": "text", "label": "credit card number"},
                    {"type": "text", "label": "Search"},
                ],
                "visible_text": "api_key=abcd1234abcd1234 credit card 4111 1111 1111 1111 safe text",
            }
        ),
    )
    context = get_visible_browser_context()

    assert context.inputs == ({"label": "Search", "type": "text"},)
    assert "abcd1234" not in context.visible_text
    assert "4111" not in context.visible_text
    assert "[redacted]" in context.visible_text


def test_summary_uses_explicit_visible_context(monkeypatch):
    monkeypatch.setattr("grandpa.browser_control.sys.platform", "win32")
    monkeypatch.setattr(
        "grandpa.browser_control._active_window_title",
        lambda: "Grandpa Docs - Google Chrome",
    )
    monkeypatch.setenv(
        "GRANDPA_BROWSER_CONTEXT_JSON",
        json.dumps(
            {
                "title": "Grandpa Docs",
                "url": "https://example.test",
                "visible_text": "Grandpa is a local assistant. It reads visible page context. It stays private.",
            }
        ),
    )

    result = execute_browser_action("summary", "visible")

    assert result.status == "handled"
    assert "Grandpa is a local assistant" in result.message


def test_links_and_buttons_use_visible_context(monkeypatch):
    monkeypatch.setattr("grandpa.browser_control.sys.platform", "win32")
    monkeypatch.setattr(
        "grandpa.browser_control._active_window_title",
        lambda: "Grandpa Docs - Google Chrome",
    )
    monkeypatch.setenv(
        "GRANDPA_BROWSER_CONTEXT_JSON",
        json.dumps(
            {
                "title": "Grandpa Docs",
                "url": "https://example.test",
                "links": [{"text": "Setup", "href": "https://example.test/setup"}],
                "buttons": ["Continue"],
            }
        ),
    )

    links = execute_browser_action("links", "visible")
    buttons = execute_browser_action("buttons", "visible")

    assert links.status == "handled"
    assert "Setup" in links.message
    assert buttons.status == "handled"
    assert "Continue" in buttons.message


def test_missing_visible_context_fallback(monkeypatch):
    monkeypatch.setattr("grandpa.browser_control.sys.platform", "linux")

    result = execute_browser_action("summary", "visible")

    assert result.status == "unsupported"
    assert "available only on windows" in result.message.lower()


def test_browser_context_route_uses_local_visible_context(monkeypatch):
    monkeypatch.setattr("grandpa.browser_control.sys.platform", "win32")
    monkeypatch.setattr(
        "grandpa.browser_control._active_window_title",
        lambda: "Route Page - Microsoft Edge",
    )
    monkeypatch.setenv(
        "GRANDPA_BROWSER_CONTEXT_JSON",
        json.dumps(
            {
                "title": "Route Page",
                "url": "https://example.test",
                "headings": ["Route Heading"],
                "visible_text": "Route page text.",
            }
        ),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/v1/browser/context")

    assert response.status_code == 200
    assert response.json()["context"]["title"] == "Route Page"
