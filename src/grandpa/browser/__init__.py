"""Browser domain package for Grandpa."""

from grandpa.browser.agent import (
    BrowserAgentStore,
    analyze_browser_task,
    browser_agent_diagnostics,
    download_plan,
    extract_visible_buttons,
    extract_visible_links,
    fill_form_plan,
    get_browser_task,
    list_browser_tasks,
    plan_browser_workflow,
    search_web_plan,
    summarize_current_page,
)
from grandpa.browser.automation import BrowserAutomation, handle_browser_command
from grandpa.browser.executor import BrowserExecutor
from grandpa.browser.models import BrowserAction, BrowserOperationResult
from grandpa.browser.parser import BrowserParser

__all__ = [
    "BrowserAction",
    "BrowserAutomation",
    "BrowserExecutor",
    "BrowserOperationResult",
    "BrowserParser",
    "BrowserAgentStore",
    "analyze_browser_task",
    "browser_agent_diagnostics",
    "download_plan",
    "extract_visible_buttons",
    "extract_visible_links",
    "fill_form_plan",
    "get_browser_task",
    "list_browser_tasks",
    "plan_browser_workflow",
    "search_web_plan",
    "summarize_current_page",
    "handle_browser_command",
]
