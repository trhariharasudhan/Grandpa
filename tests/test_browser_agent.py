from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.browser.agent import (
    BrowserAgentStore,
    browser_agent_diagnostics,
    download_plan,
    extract_visible_buttons,
    extract_visible_links,
    fill_form_plan,
    plan_browser_workflow,
    search_web_plan,
    summarize_current_page,
)
from grandpa.server.routes import router
from grandpa.skills.registry import ensure_default_skills_registered, execute_skill
from grandpa.skills.runtime import SkillExecutionContext


def _visible_context(monkeypatch) -> None:
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
                "url": "https://example.test/docs",
                "headings": ["Overview", "Install"],
                "links": [
                    {"text": "Install Guide", "href": "https://example.test/install"}
                ],
                "buttons": ["Continue"],
                "inputs": [{"type": "text", "label": "Search"}],
                "visible_text": "Grandpa is a local assistant. It reads visible page context. It keeps browser work private.",
            }
        ),
    )


def test_page_summary_from_visible_context(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_BROWSER_DB", str(tmp_path / "browser.db"))
    monkeypatch.setenv("GRANDPA_BROWSER_AGENT_DB", str(tmp_path / "agent.db"))
    _visible_context(monkeypatch)

    result = summarize_current_page()

    assert result["status"] == "completed"
    assert "Grandpa is a local assistant" in result["summary"]
    assert result["task"]["status"] == "completed"


def test_link_and_button_extraction(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_BROWSER_DB", str(tmp_path / "browser.db"))
    monkeypatch.setenv("GRANDPA_BROWSER_AGENT_DB", str(tmp_path / "agent.db"))
    _visible_context(monkeypatch)

    links = extract_visible_links()
    buttons = extract_visible_buttons()

    assert links["links"][0]["text"] == "Install Guide"
    assert buttons["buttons"] == ["Continue"]


def test_search_plan_is_low_risk(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_BROWSER_AGENT_DB", str(tmp_path / "agent.db"))

    result = search_web_plan("Python tutorials")

    assert result["status"] == "planned"
    assert result["task"]["risk_level"] == "LOW"
    assert result["task"]["approval_required"] is False


def test_form_fill_and_download_require_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_BROWSER_AGENT_DB", str(tmp_path / "agent.db"))

    form = fill_form_plan("search", "FastAPI")
    download = download_plan("visible file")

    assert form["status"] == "requires_approval"
    assert form["task"]["approval_required"] is True
    assert download["status"] == "requires_approval"
    assert download["task"]["approval_required"] is True


def test_sensitive_browser_tasks_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_BROWSER_AGENT_DB", str(tmp_path / "agent.db"))

    password = fill_form_plan("password", "secret")
    payment = plan_browser_workflow("fill payment card number")

    assert password["status"] == "blocked"
    assert password["task"]["risk_level"] == "BLOCKED"
    assert payment["status"] == "blocked"


def test_browser_agent_skills_registered_and_execute(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_BROWSER_DB", str(tmp_path / "browser.db"))
    monkeypatch.setenv("GRANDPA_BROWSER_AGENT_DB", str(tmp_path / "agent.db"))
    _visible_context(monkeypatch)
    ensure_default_skills_registered()

    summary = execute_skill(
        "browser.page_summary", {}, SkillExecutionContext(source="test")
    )
    search = execute_skill(
        "browser.search_plan",
        {"query": "FastAPI"},
        SkillExecutionContext(source="test"),
    )

    assert summary.ok is True
    assert summary.status == "completed"
    assert search.ok is True
    assert search.status == "completed"


def test_browser_agent_api_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_BROWSER_DB", str(tmp_path / "browser.db"))
    monkeypatch.setenv("GRANDPA_BROWSER_AGENT_DB", str(tmp_path / "agent.db"))
    _visible_context(monkeypatch)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    diagnostics = client.get("/v1/browser/agent/diagnostics")
    planned = client.post(
        "/v1/browser/agent/plan", json={"goal": "search Python tutorials"}
    )
    tasks = client.get("/v1/browser/agent/tasks")
    task_id = planned.json()["task"]["task_id"]
    task = client.get(f"/v1/browser/agent/tasks/{task_id}")

    assert diagnostics.status_code == 200
    assert planned.status_code == 200
    assert tasks.status_code == 200
    assert task.status_code == 200
    assert task.json()["goal"] == "search Python tutorials"


def test_store_lists_tasks(tmp_path):
    store = BrowserAgentStore(tmp_path / "agent.db")
    plan_browser_workflow("show links on this page", store=store)

    assert store.count() == 1
    assert store.list()[0]["goal"] == "show links on this page"
    assert browser_agent_diagnostics(store=store)["task_count"] == 1
