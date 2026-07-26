"""Safe execution of registry-owned project workflows."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.projects.errors import (
    ProjectCommandTimeoutError,
    UnsafeProjectCommandError,
)
from grandpa.projects.models import Project, ProjectCommand, WorkflowResult
from grandpa.projects.process_manager import ProjectProcess, ProjectProcessStore

logger = logging.getLogger(__name__)
DEFAULT_PROJECT_LOG_DIR = DEFAULT_CONFIG_DIR / "project-logs"
BLOCKED_EXECUTABLES = {
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "sh",
    "bash",
}
SECRET_PATTERN = re.compile(
    r"(?i)(authorization\s*[:=]|api[_-]?key\s*[:=]|password\s*[:=]|token\s*[:=]|cookie\s*[:=])\s*([^\s,;]+)"
)
CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
OTP_PATTERN = re.compile(r"(?i)(\b(?:otp|one[- ]time code)\s*[:=]?\s*)\d{4,8}\b")


def redact_secrets(text: str) -> str:
    text = SECRET_PATTERN.sub(lambda match: f"{match.group(1)} [REDACTED]", text)
    text = OTP_PATTERN.sub(r"\1[REDACTED]", text)
    return CARD_PATTERN.sub("[REDACTED CARD]", text)


def validate_command(command: ProjectCommand) -> None:
    if not command.args:
        raise UnsafeProjectCommandError(
            "The registered workflow has no command arguments."
        )
    executable = Path(command.args[0]).name.casefold()
    if executable in BLOCKED_EXECUTABLES or Path(executable).suffix in {
        ".bat",
        ".cmd",
        ".ps1",
        ".sh",
    }:
        raise UnsafeProjectCommandError(
            "Shell-based project workflows are not allowed."
        )
    if any(
        "\x00" in argument or "\n" in argument or "\r" in argument
        for argument in command.args
    ):
        raise UnsafeProjectCommandError(
            "The registered workflow contains unsafe command arguments."
        )


class ProjectRunner:
    def __init__(
        self,
        *,
        log_dir: Path = DEFAULT_PROJECT_LOG_DIR,
        process_store: ProjectProcessStore | None = None,
    ) -> None:
        self.log_dir = Path(log_dir)
        self.process_store = process_store or ProjectProcessStore()

    def run(
        self, project: Project, workflow: str, command: ProjectCommand
    ) -> WorkflowResult:
        validate_command(command)
        root = Path(project.root_path).resolve(strict=True)
        args = list(command.args)
        if Path(args[0]).name.casefold() in {"python", "python.exe"}:
            args[0] = sys.executable
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = (
            self.log_dir / f"{project.id}-{workflow.replace(':', '-')}-{stamp}.log"
        )
        logger.info(
            "Starting project workflow %s:%s; log=%s", project.id, workflow, log_path
        )

        if command.long_running:
            log_handle = log_path.open("a", encoding="utf-8")
            try:
                process = subprocess.Popen(  # noqa: S603
                    args,
                    cwd=str(root),
                    shell=False,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                )
            finally:
                log_handle.close()
            state = ProjectProcess(
                project_id=project.id,
                pid=process.pid,
                command=tuple(args),
                working_directory=str(root),
                started_at=datetime.now(timezone.utc).isoformat(),
                log_path=str(log_path),
                executable=args[0],
            )
            self.process_store.put(state)
            return WorkflowResult(
                "started",
                f"{project.name} {workflow} started.",
                log_path=str(log_path),
                pid=process.pid,
            )

        try:
            completed = subprocess.run(  # noqa: S603
                args,
                cwd=str(root),
                shell=False,
                capture_output=True,
                text=True,
                timeout=command.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = redact_secrets(
                ((exc.stdout or "") + (exc.stderr or ""))
                if isinstance(exc.stdout, str)
                else ""
            )
            log_path.write_text(output, encoding="utf-8")
            logger.warning("Project workflow timed out: %s:%s", project.id, workflow)
            raise ProjectCommandTimeoutError(
                f"The {workflow} command exceeded {command.timeout_seconds} seconds and was stopped. Log: {log_path}"
            ) from exc
        except KeyboardInterrupt:
            logger.info("Project workflow cancelled: %s:%s", project.id, workflow)
            return WorkflowResult(
                "cancelled",
                f"{project.name} {workflow} was cancelled.",
                log_path=str(log_path),
            )

        output = redact_secrets((completed.stdout or "") + (completed.stderr or ""))
        log_path.write_text(output, encoding="utf-8")
        status = "completed" if completed.returncode == 0 else "failed"
        summary = _summarize_output(output)
        message = f"{project.name} {workflow} {'passed' if completed.returncode == 0 else 'failed'}."
        if summary:
            message += f" {summary}"
        message += f" Exit code: {completed.returncode}. Log: {log_path}"
        logger.info(
            "Finished project workflow %s:%s exit=%s",
            project.id,
            workflow,
            completed.returncode,
        )
        return WorkflowResult(
            status, message, completed.returncode, output[-12000:], str(log_path)
        )


def _summarize_output(output: str) -> str:
    matches = re.findall(r"(?im)^.*?\b(\d+\s+passed(?:,\s*\d+\s+failed)?)\b.*$", output)
    return matches[-1] if matches else ""


__all__ = [
    "DEFAULT_PROJECT_LOG_DIR",
    "ProjectRunner",
    "redact_secrets",
    "validate_command",
]
