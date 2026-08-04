"""Agent Context Builder and Intent Classification for Grandpa Agent Runtime V1."""

from __future__ import annotations

import re
import subprocess

from grandpa.agent.models import AgentContext, AgentGoal, AgentIntent
from grandpa.memory.service import MemoryService


def classify_intent(goal_text: str) -> AgentIntent:
    """Classify the agent intent based on the goal text."""
    lower = goal_text.strip().lower()

    if any(
        w in lower for w in ("stop", "cancel", "pause", "exit", "terminate", "quit")
    ):
        if "sprint" not in lower:
            return AgentIntent.STOP_CANCEL

    if (
        re.search(r"\b(hello|hi|hey|greetings)\b", lower)
        or "good morning" in lower
        or "good afternoon" in lower
    ):
        return AgentIntent.GREETING

    if any(
        w in lower for w in ("time", "clock", "what day is it", "what's the time")
    ) or re.search(r"\bdate\b", lower):
        return AgentIntent.TIME_QUERY

    if "sprint" in lower:
        return AgentIntent.SPRINT

    if any(w in lower for w in ("project", "continue grandpa")):
        return AgentIntent.PROJECT

    if any(w in lower for w in ("roadmap", "milestone", "tasks")):
        return AgentIntent.ROADMAP

    if any(
        w in lower for w in ("remember", "forget", "recall", "preference", "session")
    ):
        return AgentIntent.MEMORY

    if any(
        w in lower
        for w in ("browser", "webpage", "website", "url", "summarize", "page")
    ):
        return AgentIntent.BROWSER

    if any(w in lower for w in ("screen", "vision", "see", "describe what is on")):
        return AgentIntent.VISION

    if any(
        w in lower
        for w in (
            "click",
            "type",
            "press",
            "move cursor",
            "keys",
            "hwnd",
            "window",
            "notepad",
            "chrome",
        )
    ):
        return AgentIntent.AUTOMATION

    if any(w in lower for w in ("plan", "decompose", "steps")):
        return AgentIntent.PLANNER

    if any(w in lower for w in ("research", "diagnose", "agent", "patch")):
        return AgentIntent.AGENT

    if any(w in lower for w in ("status", "doctor", "health", "system")):
        return AgentIntent.SYSTEM_STATUS

    if any(
        w in lower
        for w in ("how are you", "who are you", "what is your name", "tell me", "joke")
    ):
        return AgentIntent.CONVERSATIONAL

    return AgentIntent.UNKNOWN


def get_current_git_branch(repo_path: str = "D:\\Grandpa") -> str | None:
    """Safely get the verified current git branch."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def build_context(goal: AgentGoal, project_name: str = "Grandpa") -> AgentContext:
    """Load relevant memories, preferences, and project metadata to construct the AgentContext."""
    svc = MemoryService.get_instance()
    intent = classify_intent(goal.raw_text)

    # 1. Retrieve project memory
    project_mem = {}

    # Load all project memories for the given project to handle both summary and individual keys
    items = svc.list_memories(category="project", project_name=project_name, limit=100)

    # Fallback to key-prefix search
    if not items:
        all_proj_items = svc.list_memories(category="project", limit=100)
        clean_name = project_name.strip().lower().replace(" ", "_")
        items = [
            item
            for item in all_proj_items
            if (item.project_name and item.project_name.lower() == project_name.lower())
            or item.key.startswith(f"proj_{clean_name}")
        ]

    for item in items:
        k = item.key.lower()
        content = item.content
        meta = item.metadata or {}

        # Load from metadata if present
        if meta.get("project_path"):
            project_mem["project_path"] = meta["project_path"]
        if meta.get("latest_feature"):
            project_mem["latest_feature"] = meta["latest_feature"]
        if meta.get("latest_commit"):
            project_mem["latest_commit"] = meta["latest_commit"]
        if meta.get("next_task"):
            project_mem["next_task"] = meta["next_task"]
        if meta.get("last_failed_plan"):
            project_mem["last_failed_plan"] = meta["last_failed_plan"]

        # Map explicit keys or suffixes
        if k == "project_path" or k.endswith("_path") or k.endswith("_project_path"):
            project_mem["project_path"] = content
        elif (
            k == "latest_feature"
            or k.endswith("_latest_feature")
            or k.endswith("_feature")
        ):
            project_mem["latest_feature"] = content
        elif (
            k == "latest_commit"
            or k.endswith("_latest_commit")
            or k.endswith("_commit")
        ):
            project_mem["latest_commit"] = content
        elif k == "next_task" or k.endswith("_next_task"):
            project_mem["next_task"] = content
        elif k == "last_failed_plan" or k.endswith("_last_failed_plan"):
            project_mem["last_failed_plan"] = content

    # Load verified current branch
    project_path = project_mem.get("project_path") or "D:\\Grandpa"
    branch = get_current_git_branch(project_path)
    if branch:
        project_mem["current_branch"] = branch

    # 2. Load user preferences
    prefs = svc.preferences.list_all_preferences()

    # 3. Retrieve session memory
    session_items = svc.short_term.get_session_memories()
    session_mem = [{"key": m.key, "content": m.content} for m in session_items]

    return AgentContext(
        goal=goal,
        intent=intent,
        project_memory=project_mem,
        preferences=prefs,
        session_memory=session_mem,
    )
