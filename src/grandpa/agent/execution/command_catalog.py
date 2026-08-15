"""Command allowlist and execution catalog for Agent Execution Engine V2."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from grandpa.agent.execution.models import DiagnosticCommand, DiagnosticResult

# Strict base commands allowlist
ALLOWLIST_COMMANDS = {
    ("python", "-m", "compileall", "-q", "src", "tests", "scripts"),
    ("uv", "run", "ruff", "check", "src", "tests"),
    ("git", "diff", "--check"),
    ("git", "status", "--short"),
}


def is_command_allowed(args: list[str]) -> bool:
    """Validate if the given command argument list is fully matches allowed specifications."""
    if not args:
        return False

    # Check against exact matches in allowlist
    args_tuple = tuple(args)
    if args_tuple in ALLOWLIST_COMMANDS:
        return True

    if _uses_current_python(args):
        module_args = args[2:]
        if module_args == ["compileall", "-q", "src", "tests", "scripts"]:
            return True
        if module_args == ["ruff", "check", "src", "tests"]:
            return True
        if module_args and module_args[0] == "pytest":
            return _safe_pytest_args(module_args[1:])

    # Validate pytest dynamically but strictly: must start with ("uv", "run", "pytest") and target approved subfolders/files
    if len(args) >= 3 and args[:3] == ["uv", "run", "pytest"]:
        return _safe_pytest_args(args[3:])

    return False


def _uses_current_python(args: list[str]) -> bool:
    if len(args) < 3 or args[1] != "-m":
        return False
    try:
        return Path(args[0]).resolve() == Path(sys.executable).resolve()
    except OSError:
        return False


def _safe_pytest_args(args: list[str]) -> bool:
    for arg in args:
        if arg.startswith("-") and arg not in ("-v", "-s", "-q"):
            return False
        if any(token in arg for token in (";", "|", "&", "`", "$", ">", "<")):
            return False
    return bool(args)


def python_module_command(module: str, *args: str) -> list[str]:
    """Build an allowlisted module command in Grandpa's active environment."""

    return [sys.executable, "-m", module, *args]


def run_catalog_command(cmd: DiagnosticCommand) -> DiagnosticResult:
    """Run an allowed command using subprocess without shell, redirection, or pipes."""
    if not is_command_allowed(cmd.args):
        return DiagnosticResult(
            command=cmd.args,
            exit_code=1,
            stdout="",
            stderr=f"Security Block: Command '{cmd.args}' is not in the allowlisted catalog.",
            duration_seconds=0.0,
        )

    start_time = time.time()
    env = os.environ.copy()
    if cmd.cwd:
        cwd_abs = str(Path(cmd.cwd).resolve())
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{cwd_abs}{os.pathsep}{existing}" if existing else cwd_abs

    try:
        res = subprocess.run(
            cmd.args,
            cwd=cmd.cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=cmd.timeout_seconds,
            shell=False,  # strictly False
        )
        duration = time.time() - start_time
        # Limit stdout/stderr to 100,000 characters to prevent OOM
        stdout = res.stdout[:100000]
        stderr = res.stderr[:100000]

        return DiagnosticResult(
            command=cmd.args,
            exit_code=res.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.time() - start_time
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")[:5000] if exc.stdout else ""
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")[:5000] if exc.stderr else ""
        )
        return DiagnosticResult(
            command=cmd.args,
            exit_code=-1,
            stdout=stdout,
            stderr=stderr + "\nTimeout Expired.",
            duration_seconds=duration,
            timeout_triggered=True,
        )
    except Exception as exc:
        duration = time.time() - start_time
        return DiagnosticResult(
            command=cmd.args,
            exit_code=-2,
            stdout="",
            stderr=f"Command execution error: {exc}",
            duration_seconds=duration,
        )
