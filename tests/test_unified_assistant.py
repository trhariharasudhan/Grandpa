"""Unit tests verifying the Unified Assistant Router classification rules."""

from __future__ import annotations

from grandpa.agent.context import classify_intent
from grandpa.agent.models import AgentIntent


def test_unified_router_classification() -> None:
    # 1. Greetings
    assert classify_intent("hello") == AgentIntent.GREETING
    assert classify_intent("hi grandpa") == AgentIntent.GREETING
    assert classify_intent("good morning") == AgentIntent.GREETING

    # 2. Time/Date queries
    assert classify_intent("what time is it?") == AgentIntent.TIME_QUERY
    assert classify_intent("tell me the date") == AgentIntent.TIME_QUERY

    # 3. Stop/Cancel
    assert classify_intent("stop listening") == AgentIntent.STOP_CANCEL
    assert classify_intent("cancel active job") == AgentIntent.STOP_CANCEL
    assert classify_intent("pause task") == AgentIntent.STOP_CANCEL

    # 4. Sprint
    assert classify_intent("start next sprint") == AgentIntent.SPRINT
    assert classify_intent("pause the sprint") == AgentIntent.SPRINT
    assert classify_intent("validate the sprint") == AgentIntent.SPRINT

    # 5. Project
    assert classify_intent("continue Grandpa project") == AgentIntent.PROJECT
    assert classify_intent("show project status") == AgentIntent.PROJECT

    # 6. Roadmap
    assert classify_intent("show roadmap") == AgentIntent.ROADMAP
    assert classify_intent("plan next milestone") == AgentIntent.ROADMAP

    # 7. Memory
    assert classify_intent("remember that I prefer Chrome") == AgentIntent.MEMORY
    assert classify_intent("forget my preferred shell") == AgentIntent.MEMORY

    # 8. Browser
    assert classify_intent("summarize the page") == AgentIntent.BROWSER
    assert classify_intent("extract page sections") == AgentIntent.BROWSER

    # 9. Vision
    assert classify_intent("what is on my screen?") == AgentIntent.VISION
    assert classify_intent("describe what is on screen") == AgentIntent.VISION

    # 10. Automation
    assert classify_intent("open Notepad") == AgentIntent.AUTOMATION
    assert classify_intent("focus Notepad window") == AgentIntent.AUTOMATION
    assert classify_intent("type HelloWorld") == AgentIntent.AUTOMATION
