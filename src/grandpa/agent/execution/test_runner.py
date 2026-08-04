"""Focused test runner executing allowed pytest tasks for Agent Execution Engine V2."""

from __future__ import annotations

import re

from grandpa.agent.execution.command_catalog import run_catalog_command
from grandpa.agent.execution.models import DiagnosticCommand, ValidationResult


def run_focused_tests(test_path: str, workspace_root: str) -> ValidationResult:
    """Run pytest on the focused test path and parse results."""
    cmd = DiagnosticCommand(
        args=["uv", "run", "pytest", test_path],
        timeout_seconds=45,
        cwd=workspace_root,
    )
    res = run_catalog_command(cmd)

    # Parse pytest summary
    passed = 0
    failed = 0
    skipped = 0
    warnings = 0
    summary = "No tests ran."

    stdout = res.stdout or ""
    stderr = res.stderr or ""
    full_output = stdout + "\n" + stderr

    # Look for: "=== 14 passed, 1 warning in 24.95s ===" or similar
    summary_match = re.search(
        r"===\s+(?:(\d+)\s+failed)?(?:,\s+)?(?:(\d+)\s+passed)?(?:,\s+)?(?:(\d+)\s+skipped)?(?:,\s+)?(?:(\d+)\s+warning[s]?)?\s+in\s+[\d\.]+s\s+===",
        full_output,
    )
    if summary_match:
        failed = int(summary_match.group(1)) if summary_match.group(1) else 0
        passed = int(summary_match.group(2)) if summary_match.group(2) else 0
        skipped = int(summary_match.group(3)) if summary_match.group(3) else 0
        warnings = int(summary_match.group(4)) if summary_match.group(4) else 0
        summary = summary_match.group(0)
    elif "collected 0 items" in full_output:
        summary = "No tests collected or found."
    elif res.exit_code == 0 and "passed" in full_output.lower():
        summary = "Tests passed successfully (unparsed summary)."
        passed = 1
    elif res.exit_code != 0:
        summary = "Tests execution failed."
        failed = 1

    return ValidationResult(
        command=res.command,
        exit_code=res.exit_code,
        duration_seconds=res.duration_seconds,
        passed=passed,
        failed=failed,
        skipped=skipped,
        warnings=warnings,
        timeout_triggered=res.timeout_triggered,
        output_summary=summary,
    )
