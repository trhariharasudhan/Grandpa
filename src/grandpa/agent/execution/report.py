"""Sanitized report generation helper for Agent Execution Engine V2."""

from __future__ import annotations

from grandpa.agent.execution.models import ExecutionReport


def generate_sanitized_report(report: ExecutionReport) -> str:
    """Format and sanitize the final ExecutionReport for terminal output."""
    lines = []
    lines.append("=== AGENT EXECUTION V2 REPORT ===")
    lines.append(f"Goal          : {report.goal}")
    lines.append(f"Workspace Root: {report.workspace_root}")

    if report.repository_state:
        state = report.repository_state
        lines.append(f"Git Status    : Branch={state.current_branch}, Commit={state.head_commit}")
        lines.append(f"  Staged      : {len(state.staged_files)} file(s)")
        lines.append(f"  Unstaged    : {len(state.unstaged_files)} file(s)")
        lines.append(f"  Untracked   : {len(state.untracked_files)} file(s)")
        lines.append(f"  Conflicted  : {len(state.conflicted_files)} file(s)")

    if report.failure_analysis:
        fa = report.failure_analysis
        lines.append("Failure Analysis:")
        lines.append(f"  Type        : {fa.failure_type.upper()}")
        lines.append(f"  File        : {fa.failing_file or 'N/A'}:{fa.failing_line or 'N/A'}")
        lines.append(f"  Root Cause  : {fa.root_cause}")

    if report.patch_proposal:
        p = report.patch_proposal
        lines.append("Patch Proposal:")
        lines.append(f"  Proposal ID : {p.proposal_id}")
        lines.append(f"  Status      : {p.approval_status.upper()}")
        lines.append(f"  Affected    : {', '.join(p.affected_files)}")

    if report.validation_results:
        lines.append("Validation Results:")
        for vr in report.validation_results:
            lines.append(f"  - Command   : {' '.join(vr.command)}")
            lines.append(f"    Exit Code : {vr.exit_code}")
            lines.append(f"    Summary   : {vr.output_summary} (Passed: {vr.passed}, Failed: {vr.failed})")

    lines.append(f"Final Status  : {report.final_status.upper()}")
    if report.summary:
        lines.append(f"Summary       : {report.summary}")
    lines.append("==================================")

    return "\n".join(lines)
