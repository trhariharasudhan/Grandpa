"""Deterministic Memory Intent Router and Scope Classifier for Grandpa."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

MemoryScope = Literal["session", "project", "preference", "knowledge", "ambiguous"]


class MemoryIntent(str, Enum):
    REMEMBER = "remember"
    RECALL = "recall"
    RESUME = "resume"
    FORGET = "forget"
    DO_NOT_REMEMBER = "do_not_remember"
    CLEAR = "clear"
    SHOW = "show"
    SESSION_CONTROL = "session_control"


@dataclass
class MemoryIntentResult:
    intent: MemoryIntent
    scope: MemoryScope
    target_key: str | None = None
    target_value: str | None = None
    project_name: str | None = None
    confidence: float = 1.0
    original_text: str = ""
    action_type: str | None = None
    metadata: dict[str, Any] | None = None


class MemoryIntentRouter:
    """Deterministic, rule-based parser for memory commands and intents."""

    # Preference key mapping rules
    PREFERENCE_PATTERNS = [
        (r"shell|terminal|powershell|cmd|bash|pwsh", "preferred_shell"),
        (r"browser|chrome|edge|firefox", "default_browser"),
        (r"mic|microphone", "preferred_microphone"),
        (r"language|lang", "response_language"),
    ]

    def parse(
        self, text: str, current_project: str | None = None
    ) -> MemoryIntentResult | None:
        raw = text.strip()
        tlower = raw.lower()

        if not tlower:
            return None

        # 1. Do Not Remember / Session Toggle Off
        if any(
            p in tlower
            for p in [
                "do not remember this",
                "don't remember this",
                "don't remember this conversation",
                "do not remember this conversation",
                "memory off",
                "disable memory",
            ]
        ):
            return MemoryIntentResult(
                intent=MemoryIntent.DO_NOT_REMEMBER,
                scope="session",
                confidence=1.0,
                original_text=raw,
                action_type="disable_session_memory",
            )

        # 2. Enable Memory / Session Toggle On
        if tlower in ["memory on", "enable memory"]:
            return MemoryIntentResult(
                intent=MemoryIntent.SESSION_CONTROL,
                scope="session",
                confidence=1.0,
                original_text=raw,
                action_type="enable_session_memory",
            )

        # 3. Session Clear / Forget Session
        if tlower in ["forget this session", "session clear", "clear session memory"]:
            return MemoryIntentResult(
                intent=MemoryIntent.CLEAR,
                scope="session",
                confidence=1.0,
                original_text=raw,
                action_type="clear_session",
            )

        # 4. Resume / Continue Workflow / Continue Task
        resume_match = re.search(
            r"(?:continue|resume)\s+(?:where\s+we\s+stopped|the\s+last\s+(?:grandpa\s+)?task|the\s+(?:grandpa\s+)?project|last\s+task|last\s+successful\s+workflow|last\s+failed\s+plan)",
            tlower,
        )
        if resume_match or tlower in [
            "continue",
            "resume",
            "continue last task",
            "resume last failed plan",
        ]:
            target_proj = current_project or "Grandpa"
            is_failed = "failed" in tlower
            return MemoryIntentResult(
                intent=MemoryIntent.RESUME,
                scope="project",
                project_name=target_proj,
                confidence=0.95,
                original_text=raw,
                action_type="resume_failed_plan"
                if is_failed
                else "resume_project_task",
            )

        # 5. Show Preferences / Project Status
        if any(p in tlower for p in ["show my saved preferences", "show preferences"]):
            return MemoryIntentResult(
                intent=MemoryIntent.SHOW,
                scope="preference",
                confidence=1.0,
                original_text=raw,
                action_type="show_preferences",
            )

        if any(
            p in tlower
            for p in [
                "what do you remember about",
                "show project status",
                "show last plan status",
            ]
        ):
            proj_name = (
                self._extract_project_name(tlower) or current_project or "Grandpa"
            )
            return MemoryIntentResult(
                intent=MemoryIntent.SHOW,
                scope="project",
                project_name=proj_name,
                confidence=0.9,
                original_text=raw,
                action_type="show_project_status",
            )

        # 6. Forget / Delete Memory
        forget_match = re.search(
            r"(?:forget|delete\s+memory(?:\s+for)?)\s+(.+)", tlower
        )
        if forget_match:
            target = forget_match.group(1).strip()
            # Check preference target
            if "browser" in target:
                return MemoryIntentResult(
                    intent=MemoryIntent.FORGET,
                    scope="preference",
                    target_key="default_browser",
                    confidence=1.0,
                    original_text=raw,
                    action_type="delete_preference",
                )
            if "shell" in target:
                return MemoryIntentResult(
                    intent=MemoryIntent.FORGET,
                    scope="preference",
                    target_key="preferred_shell",
                    confidence=1.0,
                    original_text=raw,
                    action_type="delete_preference",
                )
            return MemoryIntentResult(
                intent=MemoryIntent.FORGET,
                scope="knowledge",
                target_key=target,
                confidence=0.85,
                original_text=raw,
                action_type="delete_memory",
            )

        # "what was the last feature we completed?"
        if re.search(r"(?:last|latest)\s+(?:\w+\s+)?feature", tlower):
            return MemoryIntentResult(
                intent=MemoryIntent.RECALL,
                scope="project",
                target_key="latest_feature",
                project_name=current_project or "Grandpa",
                confidence=1.0,
                original_text=raw,
                action_type="recall_latest_feature",
            )

        # "what is the latest Grandpa commit?"
        if re.search(r"(?:last|latest)\s+(?:\w+\s+)?commit", tlower):
            return MemoryIntentResult(
                intent=MemoryIntent.RECALL,
                scope="project",
                target_key="latest_commit",
                project_name=current_project or "Grandpa",
                confidence=1.0,
                original_text=raw,
                action_type="recall_latest_commit",
            )

        # "what was the last failed plan?"
        if "last failed plan" in tlower or "failed plan" in tlower:
            return MemoryIntentResult(
                intent=MemoryIntent.RECALL,
                scope="project",
                target_key="last_failed_plan",
                project_name=current_project or "Grandpa",
                confidence=1.0,
                original_text=raw,
                action_type="recall_last_failed_plan",
            )

        # General Recall
        if (
            tlower.startswith("what is my preferred")
            or tlower.startswith("what's my preferred")
            or tlower.startswith("what is my default")
            or tlower.startswith("what's my default")
        ):
            pref_key = self._match_preference_key(tlower)
            return MemoryIntentResult(
                intent=MemoryIntent.RECALL,
                scope="preference",
                target_key=pref_key,
                confidence=0.95,
                original_text=raw,
                action_type="recall_preference",
            )

        # 8. Remember / Save Instructions
        rem_match = re.search(
            r"(?:remember|save)(?:\s+that|\s+my|\s+this)?\s+(.+)", tlower
        )
        if rem_match:
            body = rem_match.group(1).strip()

            # Check preference match
            # "prefer powershell", "default browser is chrome"
            if "prefer" in body or "default" in body or "preferred" in body:
                pref_key, pref_val = self._parse_preference(body)
                if pref_key and pref_val:
                    return MemoryIntentResult(
                        intent=MemoryIntent.REMEMBER,
                        scope="preference",
                        target_key=pref_key,
                        target_value=pref_val,
                        confidence=1.0,
                        original_text=raw,
                        action_type="save_preference",
                    )

            # Check project match
            # "grandpa project is at d:\grandpa", "save this as project memory"
            if "project" in body or "at d:\\" in body or "path is" in body:
                proj_name, proj_path, proj_val = self._parse_project_info(body, raw)
                return MemoryIntentResult(
                    intent=MemoryIntent.REMEMBER,
                    scope="project",
                    target_key="project_path" if proj_path else "summary",
                    target_value=proj_path or proj_val or raw,
                    project_name=proj_name or current_project or "Grandpa",
                    confidence=0.95,
                    original_text=raw,
                    action_type="save_project_info",
                )

            # Check session scope explicitly
            if "for this session" in body or "session memory" in body:
                return MemoryIntentResult(
                    intent=MemoryIntent.REMEMBER,
                    scope="session",
                    target_value=raw,
                    confidence=0.9,
                    original_text=raw,
                    action_type="save_session_memory",
                )

            # Default to knowledge memory
            return MemoryIntentResult(
                intent=MemoryIntent.REMEMBER,
                scope="knowledge",
                target_value=raw,
                confidence=0.8,
                original_text=raw,
                action_type="save_knowledge",
            )

        return None

    def _match_preference_key(self, text: str) -> str:
        for pattern, pkey in self.PREFERENCE_PATTERNS:
            if re.search(pattern, text):
                return pkey
        return "general"

    def _parse_preference(self, body: str) -> tuple[str, str]:
        if "powershell" in body or "pwsh" in body:
            return "preferred_shell", "pwsh"
        if "cmd" in body or "command prompt" in body:
            return "preferred_shell", "cmd"
        if "bash" in body:
            return "preferred_shell", "bash"

        if "chrome" in body:
            return "default_browser", "Chrome"
        if "edge" in body:
            return "default_browser", "Edge"
        if "firefox" in body:
            return "default_browser", "Firefox"

        # General "prefer X is Y"
        match = re.search(r"(\w+)\s+(?:is|to be)\s+(.+)", body)
        if match:
            k = match.group(1)
            v = match.group(2)
            pkey = self._match_preference_key(k)
            return pkey, v.strip()

        return "general", body

    def _parse_project_info(
        self, body: str, raw: str
    ) -> tuple[str | None, str | None, str | None]:
        # Path match e.g. D:\Grandpa or C:\Projects\...
        path_match = re.search(r"([a-zA-Z]:\\[^\s]+)", raw)
        proj_path = path_match.group(1) if path_match else None

        proj_name = self._extract_project_name(body)
        return proj_name, proj_path, body

    def _extract_project_name(self, text: str) -> str | None:
        if "grandpa" in text.lower():
            return "Grandpa"
        match = re.search(r"project\s+([a-zA-Z0-9_\-]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).capitalize()
        return None
