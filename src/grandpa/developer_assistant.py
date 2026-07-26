"""Safe developer workflow helpers for Grandpa."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path("D:/Grandpa")
BLOCKED_COMMAND_PATTERNS = re.compile(r"\b(rm|del|format|shutdown|restart|reg\s+delete|git\s+reset\s+--hard)\b", re.I)
ALLOWLIST_PREFIXES = (
    ("git", "status"),
    ("git", "diff"),
    ("git", "log"),
    ("git", "branch"),
    ("uv", "run"),
    ("npm", "run", "build"),
    ("docker", "version"),
    ("docker", "info"),
)


@dataclass(frozen=True)
class DeveloperResult:
    status: str
    message: str
    data: dict[str, Any]


def classify_command(command: str) -> dict[str, Any]:
    clean = command.strip()
    parts = clean.split()
    if not parts:
        return {"risk": "LOW", "allowed": False, "approval_required": False, "reason": "empty command"}
    if BLOCKED_COMMAND_PATTERNS.search(clean):
        return {"risk": "BLOCKED", "allowed": False, "approval_required": False, "reason": "destructive command pattern"}
    if any(tuple(parts[: len(prefix)]) == prefix for prefix in ALLOWLIST_PREFIXES):
        return {"risk": "LOW", "allowed": True, "approval_required": False, "reason": "developer allowlist"}
    return {"risk": "MEDIUM", "allowed": False, "approval_required": True, "reason": "command needs explicit approval"}


def terminal_plan(command: str, *, dry_run: bool = True) -> DeveloperResult:
    policy = classify_command(command)
    if policy["risk"] == "BLOCKED":
        return DeveloperResult("blocked", "I blocked this developer command for safety.", {"command": command, "policy": policy})
    if dry_run or policy["approval_required"]:
        return DeveloperResult(
            "requires_confirmation" if policy["approval_required"] else "handled",
            "Prepared developer command dry-run.",
            {"command": command, "policy": policy, "dry_run": True},
        )
    return DeveloperResult("requires_confirmation", "Execution requires explicit approval.", {"command": command, "policy": policy})


def git_summary(repo: Path | str = REPO_ROOT) -> DeveloperResult:
    repo = Path(repo)
    if not (repo / ".git").exists():
        return DeveloperResult("unsupported", "This folder is not a Git repository.", {"repo": str(repo)})
    try:
        status = subprocess.run(["git", "status", "--short"], cwd=repo, capture_output=True, text=True, timeout=10, check=False)
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True, timeout=10, check=False)
    except Exception as exc:
        return DeveloperResult("error", f"Git diagnostics failed: {exc}", {"repo": str(repo)})
    lines = [line for line in status.stdout.splitlines() if line.strip()]
    suggestions = _commit_suggestions(lines)
    return DeveloperResult(
        "handled",
        f"Git branch {branch.stdout.strip() or 'unknown'} has {len(lines)} changed item(s).",
        {"branch": branch.stdout.strip(), "changed": lines, "commit_suggestions": suggestions},
    )


def project_diagnostics(repo: Path | str = REPO_ROOT) -> DeveloperResult:
    repo = Path(repo)
    checks = {
        "pyproject": (repo / "pyproject.toml").exists(),
        "uv_lock": (repo / "uv.lock").exists(),
        "python_package": (repo / "src" / "grandpa").is_dir(),
        "dockerfile": (repo / "deploy" / "docker" / "Dockerfile").exists(),
        "tests": (repo / "tests").exists(),
        "env_example": any(repo.glob("*.env.example")),
    }
    missing = [key for key, ok in checks.items() if not ok]
    return DeveloperResult(
        "handled",
        f"Project diagnostics complete: {len(checks) - len(missing)}/{len(checks)} checks ready.",
        {"checks": checks, "missing": missing, "repo": str(repo)},
    )


def docker_diagnostics() -> DeveloperResult:
    try:
        version = subprocess.run(["docker", "version", "--format", "{{json .}}"], capture_output=True, text=True, timeout=8, check=False)
    except Exception as exc:
        return DeveloperResult("unsupported", "Docker command is not available.", {"error": str(exc)})
    ok = version.returncode == 0
    data: dict[str, Any] = {"command_available": True, "daemon_reachable": ok}
    if ok:
        try:
            data["version"] = json.loads(version.stdout)
        except json.JSONDecodeError:
            data["version_text"] = version.stdout[:500]
    else:
        data["error"] = version.stderr[:500]
    return DeveloperResult("handled" if ok else "warning", "Docker diagnostics complete.", data)


def api_test_plan(method: str, url: str, *, body: str = "") -> DeveloperResult:
    return DeveloperResult(
        "handled",
        f"Prepared local API test plan for {method.upper()} {url}.",
        {"method": method.upper(), "url": url, "body_preview": body[:300], "dry_run": True, "approval_required": False},
    )


def analyze_log_text(text: str) -> DeveloperResult:
    error_lines = [line for line in text.splitlines() if re.search(r"\b(error|failed|exception|traceback)\b", line, re.I)]
    warning_lines = [line for line in text.splitlines() if re.search(r"\b(warn|warning|deprecated)\b", line, re.I)]
    return DeveloperResult(
        "handled",
        f"Log analysis found {len(error_lines)} error line(s) and {len(warning_lines)} warning line(s).",
        {"errors": error_lines[:20], "warnings": warning_lines[:20]},
    )


def diagnostics() -> dict[str, Any]:
    git = git_summary()
    project = project_diagnostics()
    docker = docker_diagnostics()
    return {
        "status": "ready",
        "git": git.data,
        "project": project.data,
        "docker": docker.data,
        "allowlist_prefixes": [" ".join(prefix) for prefix in ALLOWLIST_PREFIXES],
        "templates": ["bug investigation", "api smoke test", "docker diagnosis", "release checklist"],
        "safety": {"dangerous_shell_blocked": True, "risky_execution_requires_approval": True, "dry_run_default": True},
    }


def _commit_suggestions(lines: list[str]) -> list[str]:
    labels = []
    joined = "\n".join(lines).lower()
    if "test" in joined:
        labels.append("test: update validation coverage")
    if "src/grandpa/cli" in joined:
        labels.append("cli: refine Grandpa interface")
    if "src/grandpa" in joined:
        labels.append("feat: update Grandpa assistant capabilities")
    return labels or ["chore: update project files"]


__all__ = [
    "DeveloperResult",
    "api_test_plan",
    "analyze_log_text",
    "classify_command",
    "diagnostics",
    "docker_diagnostics",
    "git_summary",
    "project_diagnostics",
    "terminal_plan",
]
