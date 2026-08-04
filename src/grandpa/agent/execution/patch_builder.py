"""Structured patch proposal builder for Agent Execution Engine V2."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from grandpa.agent.execution.models import (
    FailureAnalysis,
    PatchFileChange,
    PatchProposal,
)


def calculate_file_hash(file_path: str) -> str:
    """Calculate SHA-256 hash of a file's content in a deterministic format."""
    p = Path(file_path).resolve()
    if not p.exists() or not p.is_file():
        return ""
    try:
        content = p.read_bytes()
        # Normalized line endings to ignore CRLF variations in hash checks
        normalized = content.replace(b"\r\n", b"\n")
        return hashlib.sha256(normalized).hexdigest()
    except Exception:
        return ""


def build_patch_proposal(
    goal: str,
    analysis: FailureAnalysis,
    changes: list[dict[str, str]],  # List of dicts with {"path": ..., "diff": ...}
    workspace_root: str,
) -> PatchProposal:
    """Construct a structured PatchProposal matching affected files, original hashes, and diagnostic evidence."""
    if not analysis.evidence_ids:
        raise ValueError(
            "Cannot build PatchProposal: analysis has no diagnostic evidence."
        )

    if not changes:
        raise ValueError("Cannot build PatchProposal: no changes proposed.")

    proposal_id = str(uuid.uuid4())[:8]
    affected_files = []
    file_changes = []
    inspected_file_hashes = {}
    source_excerpts = {}
    changed_line_ranges = {}

    for c in changes:
        diff_text = c["diff"]

        # 1. Reject empty patches
        if not diff_text or not diff_text.strip():
            raise ValueError("Cannot build PatchProposal: proposed patch is empty.")

        # 2. Reject comment-only and placeholder changes
        if "verified patch change" in diff_text:
            raise ValueError(
                "Cannot build PatchProposal: proposed patch contains no real changes (empty, comment-only, or placeholder)."
            )

        added_lines = [
            line[1:].strip()
            for line in diff_text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        has_real_adds = any(line and not line.startswith("#") for line in added_lines)
        has_deletions = any(
            line.startswith("-") and not line.startswith("---")
            for line in diff_text.splitlines()
        )

        if not has_real_adds and not has_deletions:
            raise ValueError(
                "Cannot build PatchProposal: proposed patch contains no real changes (empty, comment-only, or placeholder)."
            )

        full_path = str(Path(c["path"]).resolve())
        orig_hash = calculate_file_hash(full_path)
        inspected_file_hashes[full_path] = orig_hash

        try:
            content = Path(full_path).read_text(encoding="utf-8")
            source_excerpts[full_path] = content[:500]
        except Exception:
            source_excerpts[full_path] = ""

        # Extract line range from hunk header
        line_range = (1, 1)
        for line in diff_text.splitlines():
            if line.startswith("@@"):
                match = re.search(r"@@ -(\d+),?(\d+)? \+(\d+),?(\d+)? @@", line)
                if match:
                    line_range = (
                        int(match.group(3)),
                        int(match.group(3)) + int(match.group(4) or 1),
                    )
                    break
        changed_line_ranges[full_path] = line_range

        file_changes.append(
            PatchFileChange(
                path=full_path,
                original_hash=orig_hash,
                diff_text=diff_text,
            )
        )
        affected_files.append(str(Path(c["path"]).relative_to(Path(workspace_root))))

    # Validation commands standard
    validation = [
        ["python", "-m", "compileall", "-q", "src", "tests", "scripts"],
        ["uv", "run", "ruff", "check", "src", "tests"],
    ]
    if analysis.failing_file:
        validation.append(["uv", "run", "pytest", analysis.failing_file])
    else:
        validation.append(["git", "diff", "--check"])

    return PatchProposal(
        proposal_id=proposal_id,
        goal=goal,
        root_cause=analysis.root_cause,
        affected_files=affected_files,
        exact_change_summary=f"Resolved issue in {', '.join(affected_files)}: {analysis.message}",
        file_changes=file_changes,
        risk_classification="LOW",
        expected_result="Diagnostics complete, tests pass successfully.",
        validation_commands=validation,
        rollback_strategy="Restore file snapshot backups (.bak) created before modification.",
        approval_status="pending",
        analysis_id=analysis.analysis_id,
        evidence_ids=analysis.evidence_ids,
        inspected_file_hashes=inspected_file_hashes,
        source_excerpts=source_excerpts,
        changed_line_ranges=changed_line_ranges,
    )


def format_proposal_preview(proposal: PatchProposal) -> str:
    """Format patch proposal to strict view layout."""
    lines = []
    lines.append(f"Proposal ID: {proposal.proposal_id}")
    lines.append(f"Goal       : {proposal.goal}")
    lines.append(f"Root Cause : {proposal.root_cause}")
    lines.append("Files      :")
    for f in proposal.affected_files:
        lines.append(f"  - {f}")
    lines.append(f"Changes    : {proposal.exact_change_summary}")
    lines.append(f"Risk       : {proposal.risk_classification}")
    lines.append("Validation :")
    for cmd in proposal.validation_commands:
        lines.append(f"  - {' '.join(cmd)}")
    lines.append(f"Status     : {proposal.approval_status.upper()}")

    lines.append("\nProposed Diff Preview:")
    for change in proposal.file_changes:
        lines.append(f"--- {change.path}")
        lines.append(change.diff_text)

    return "\n".join(lines)
