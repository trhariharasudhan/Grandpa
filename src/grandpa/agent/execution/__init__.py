"""Agent Execution V2 Subpackage."""

from __future__ import annotations

from grandpa.agent.execution.analyzer import analyze_failure
from grandpa.agent.execution.approval import PatchApprovalManager
from grandpa.agent.execution.command_catalog import (
    is_command_allowed,
    run_catalog_command,
)
from grandpa.agent.execution.file_reader import read_file_safe
from grandpa.agent.execution.models import (
    DiagnosticCommand,
    DiagnosticEvidence,
    DiagnosticResult,
    ExecutionCheckpoint,
    ExecutionGoal,
    ExecutionReport,
    ExecutionSession,
    FailureAnalysis,
    FileCandidate,
    FileSnapshot,
    PatchApplicationResult,
    PatchApproval,
    PatchFileChange,
    PatchProposal,
    RecoveryAttempt,
    RepositoryState,
    ValidationPlan,
    ValidationResult,
    WorkspaceContext,
)
from grandpa.agent.execution.patch_applier import (
    apply_patch_proposal,
    rollback_applied_backups,
)
from grandpa.agent.execution.patch_builder import (
    build_patch_proposal,
    calculate_file_hash,
    format_proposal_preview,
)
from grandpa.agent.execution.recovery import execute_with_recovery
from grandpa.agent.execution.report import generate_sanitized_report
from grandpa.agent.execution.repository import inspect_repository
from grandpa.agent.execution.test_runner import run_focused_tests
from grandpa.agent.execution.verifier import verify_execution_outcome
from grandpa.agent.execution.workspace import resolve_and_verify_workspace

__all__ = [
    "resolve_and_verify_workspace",
    "inspect_repository",
    "is_command_allowed",
    "run_catalog_command",
    "read_file_safe",
    "analyze_failure",
    "calculate_file_hash",
    "build_patch_proposal",
    "format_proposal_preview",
    "PatchApprovalManager",
    "apply_patch_proposal",
    "rollback_applied_backups",
    "run_focused_tests",
    "verify_execution_outcome",
    "execute_with_recovery",
    "generate_sanitized_report",

    # Models
    "ExecutionGoal",
    "WorkspaceContext",
    "RepositoryState",
    "FileCandidate",
    "FileSnapshot",
    "DiagnosticCommand",
    "DiagnosticResult",
    "DiagnosticEvidence",
    "FailureAnalysis",
    "PatchProposal",
    "PatchFileChange",
    "PatchApproval",
    "PatchApplicationResult",
    "ValidationPlan",
    "ValidationResult",
    "ExecutionCheckpoint",
    "ExecutionSession",
    "ExecutionReport",
    "RecoveryAttempt",
]
