"""Structured models for Agent Execution Engine V2."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionGoal:
    raw_text: str
    session_id: str
    created_at: float = field(default_factory=time.time)


@dataclass
class WorkspaceContext:
    root_path: str
    is_safe: bool = True
    active_branch: str | None = None
    reason: str | None = None


@dataclass
class RepositoryState:
    repo_root: str
    current_branch: str
    head_commit: str
    staged_files: list[str] = field(default_factory=list)
    unstaged_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    conflicted_files: list[str] = field(default_factory=list)
    is_clean: bool = True


@dataclass
class FileCandidate:
    path: str
    reason: str
    score: float = 1.0


@dataclass
class FileSnapshot:
    path: str
    content_hash: str
    last_modified: float
    content_preview: str = ""


@dataclass
class DiagnosticCommand:
    args: list[str]
    timeout_seconds: int = 30
    cwd: str | None = None


@dataclass
class DiagnosticResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timeout_triggered: bool = False


@dataclass
class DiagnosticEvidence:
    evidence_id: str
    command: list[str]
    argv: list[str]
    working_directory: str
    exit_code: int
    stdout_excerpt: str
    stderr_excerpt: str
    parser: str
    failure_type: str
    file_path: str | None = None
    line_number: int | None = None
    symbol: str | None = None
    confidence: float = 1.0


@dataclass
class FailureAnalysis:
    analysis_id: str
    failure_type: str  # syntax, import, assertion, timeout, environment, dependency, mock_mismatch, product_bug, etc.
    failing_file: str | None = None
    failing_line: int | None = None
    message: str = ""
    root_cause: str = ""
    is_confirmed: bool = False
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class PatchFileChange:
    path: str
    original_hash: str
    diff_text: str


@dataclass
class PatchProposal:
    proposal_id: str
    goal: str
    root_cause: str
    affected_files: list[str]
    exact_change_summary: str
    file_changes: list[PatchFileChange]
    risk_classification: str = "LOW"
    expected_result: str = ""
    validation_commands: list[list[str]] = field(default_factory=list)
    rollback_strategy: str = ""
    approval_status: str = "pending"  # pending, approved, rejected, applied
    created_at: float = field(default_factory=time.time)

    # Evidence & Inspected structures
    analysis_id: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    inspected_file_hashes: dict[str, str] = field(default_factory=dict)
    source_excerpts: dict[str, str] = field(default_factory=dict)
    changed_line_ranges: dict[str, tuple[int, int]] = field(default_factory=dict)


@dataclass
class PatchApproval:
    proposal_id: str
    approved_by: str
    approved_at: float = field(default_factory=time.time)


@dataclass
class PatchApplicationResult:
    proposal_id: str
    success: bool
    applied_changes: list[str] = field(default_factory=list)
    backups_created: list[str] = field(default_factory=list)
    error_message: str | None = None


@dataclass
class ValidationPlan:
    test_paths: list[str]
    commands: list[list[str]]


@dataclass
class ValidationResult:
    command: list[str]
    exit_code: int
    duration_seconds: float
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    warnings: int = 0
    timeout_triggered: bool = False
    output_summary: str = ""


@dataclass
class ExecutionCheckpoint:
    checkpoint_id: str
    session_id: str
    state_data: dict[str, Any]
    created_at: float = field(default_factory=time.time)


@dataclass
class ExecutionSession:
    session_id: str
    workspace_root: str
    active_proposal_id: str | None = None
    state: str = "idle"  # idle, diagnosing, proposing, approved, applied, validating, completed, failed
    checkpoints: list[ExecutionCheckpoint] = field(default_factory=list)


@dataclass
class RecoveryAttempt:
    attempt_number: int
    error_message: str
    action_taken: str
    success: bool = False


@dataclass
class ExecutionReport:
    goal: str
    workspace_root: str
    repository_state: RepositoryState | None = None
    diagnostics: list[DiagnosticResult] = field(default_factory=list)
    failure_analysis: FailureAnalysis | None = None
    patch_proposal: PatchProposal | None = None
    validation_results: list[ValidationResult] = field(default_factory=list)
    final_status: str = "completed"
    summary: str = ""
