"""Text-first Jarvis intent routing for safe local actions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.jarvis.context_resolver import SafeContextResolver


@dataclass(frozen=True)
class JarvisIntentResult:
    status: str
    message: str
    payload: dict[str, Any] | None = None
    project_path: Path | None = None
    application: str | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class ProjectOpenIntent:
    project_name: str
    app_name: str
    confidence: float


APP_ALIASES = {
    "code": "vscode",
    "vs code": "vscode",
    "vscode": "vscode",
    "visual studio code": "vscode",
}


def route_jarvis_command(
    text: str,
    *,
    resolver: SafeContextResolver | None = None,
    dry_run: bool = False,
) -> JarvisIntentResult:
    command = _normalise(text)
    if not command:
        return JarvisIntentResult("unsupported", "I need a command to route.")
    if _looks_like_shell_execution(command):
        return JarvisIntentResult("blocked", "I blocked this command for safety.")

    resolver = resolver or SafeContextResolver()
    project_open = _parse_open_project(command)
    if project_open is None:
        return JarvisIntentResult(
            "unsupported",
            "I don't know how to route that Jarvis command yet.",
            confidence=0.0,
        )

    if project_open.confidence < 0.55:
        return JarvisIntentResult(
            "unsupported",
            "I don't know how to route that Jarvis command yet.",
            confidence=project_open.confidence,
        )

    application = APP_ALIASES.get(project_open.app_name)
    if application is None:
        return JarvisIntentResult(
            "unsupported",
            f"I don't know how to open projects in {project_open.app_name}.",
            confidence=project_open.confidence,
        )

    project = resolver.resolve_project(project_open.project_name)
    if project is None:
        return JarvisIntentResult(
            "unsupported",
            f"I could not find a safe local project named {project_open.project_name}.",
            confidence=project_open.confidence,
        )

    payload = {
        "action_type": "open_app",
        "target": application,
        "args": {"project_path": str(project.path)},
        "dry_run": dry_run,
    }
    return JarvisIntentResult(
        "routed",
        f"Resolved {project.name} for {application}.",
        payload=payload,
        project_path=project.path,
        application=application,
        confidence=project_open.confidence,
    )


def _parse_open_project(command: str) -> ProjectOpenIntent | None:
    patterns = (
        r"open (?:my )?(.+?) project in (.+)",
        r"open (?:my )?(.+?) repo in (.+)",
        r"open (?:my )?(.+?) repository in (.+)",
        r"open (?:my )?(.+?) folder in (.+)",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, command)
        if match:
            app_name = _normalise_app_name(match.group(2).strip())
            if app_name is None:
                return None
            return ProjectOpenIntent(_clean_project_name(match.group(1)), app_name, 0.95)
    return _parse_noisy_open_project(command)


def _parse_noisy_open_project(command: str) -> ProjectOpenIntent | None:
    if "open" not in command.split():
        return None

    confidence = 0.25
    if _has_project_hint(command):
        confidence += 0.2
    else:
        return None

    app_name = _normalise_app_name(command)
    if app_name is not None:
        confidence += 0.25
    else:
        return None

    project_name = "Grandpa" if _has_grandpa_hint(command) else ""
    if project_name:
        confidence += 0.15
    elif _looks_like_projecting_stt(command):
        project_name = "Grandpa"
        confidence += 0.08
    else:
        return None

    return ProjectOpenIntent(project_name, app_name, min(confidence, 0.85))


def _clean_project_name(value: str) -> str:
    cleaned = value.strip()
    if cleaned.endswith(" project"):
        cleaned = cleaned[: -len(" project")]
    return cleaned.strip()


def _normalise_app_name(value: str) -> str | None:
    text = _normalise(value)
    if text in APP_ALIASES:
        return APP_ALIASES[text]
    if "visual studio code" in text or "vs code" in text or "vscode" in text:
        return "vscode"
    if "this will be your goal" in text and ("open" in text or _has_project_hint(text)):
        return "vscode"
    if "code" in text and ("studio" in text or "editor" in text or _has_project_hint(text)):
        return "vscode"
    return None


def _has_project_hint(command: str) -> bool:
    return bool(re.search(r"\b(project|projecting|repo|repository|folder)\b", command))


def _has_grandpa_hint(command: str) -> bool:
    return bool(re.search(r"\bgrandpa\b", command))


def _looks_like_projecting_stt(command: str) -> bool:
    return "projecting" in command and "this will be your goal" in command


def _normalise(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"[?!.\s]+$", "", value)
    return re.sub(r"\s+", " ", value)


def _looks_like_shell_execution(command: str) -> bool:
    return bool(
        re.search(
            r"\b(cmd|powershell|terminal|shell|run command|execute|script|\.ps1|\.bat|\.cmd)\b",
            command,
        )
    )
