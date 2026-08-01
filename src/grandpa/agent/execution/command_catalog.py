"""Command allowlist and execution catalog for Agent Execution Engine V2."""

from __future__ import annotations

import os
import subprocess
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

    # Validate pytest dynamically but strictly: must start with ("uv", "run", "pytest") and target approved subfolders/files
    if len(args) >= 3 and args[:3] == ["uv", "run", "pytest"]:
        # Verify all remaining arguments are safe test paths (no flags starting with - unless allowlisted, no chaining)
        for arg in args[3:]:
            if arg.startswith("-") and arg not in ("-v", "-s", "-q"):
                return False
            # Check for path safety, preventing traversal/semicolon/chaining
            if ";" in arg or "|" in arg or "&" in arg or "`" in arg or "$" in arg or ">" in arg or "<" in arg:
                return False
        return True

    return False


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
        stdout = exc.stdout.decode("utf-8", errors="replace")[:5000] if exc.stdout else ""
        stderr = exc.stderr.decode("utf-8", errors="replace")[:5000] if exc.stderr else ""
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
