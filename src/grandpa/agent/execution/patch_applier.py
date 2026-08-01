"""Bounded and safe patch application engine for Agent Execution Engine V2."""

from __future__ import annotations

import shutil
from pathlib import Path

from grandpa.agent.execution.models import PatchApplicationResult, PatchProposal
from grandpa.agent.execution.patch_builder import calculate_file_hash
from grandpa.tools.apply_patch import ApplyPatchTool


def apply_patch_proposal(proposal: PatchProposal, workspace_root: str) -> PatchApplicationResult:
    """Safely apply each file change in the approved PatchProposal, creating backups and supporting rollbacks."""
    # 1. Double check file freshness before applying any change
    for change in proposal.file_changes:
        cur_hash = calculate_file_hash(change.path)
        if cur_hash != change.original_hash:
            return PatchApplicationResult(
                proposal_id=proposal.proposal_id,
                success=False,
                error_message=f"Stale proposal check failed: File '{change.path}' was modified after proposal generation.",
            )

    applied_changes = []
    backups = []
    failed = False
    err_msg = None

    tool = ApplyPatchTool()

    # 2. Iterate and apply
    for change in proposal.file_changes:
        try:
            # We explicitly enforce backup creation
            res = tool.execute(patch=change.diff_text, path=change.path, backup=True)
            if not res.success:
                failed = True
                err_msg = f"Failed to apply patch hunk to '{change.path}': {res.content}"
                break

            applied_changes.append(change.path)
            meta = res.metadata or {}
            if meta.get("backup_path"):
                backups.append((change.path, meta["backup_path"]))
        except Exception as exc:
            failed = True
            err_msg = f"Exception occurred applying patch to '{change.path}': {exc}"
            break

    # 3. Handle rollback on partial failure
    if failed:
        rollback_applied_backups(backups)
        return PatchApplicationResult(
            proposal_id=proposal.proposal_id,
            success=False,
            error_message=err_msg,
        )

    return PatchApplicationResult(
        proposal_id=proposal.proposal_id,
        success=True,
        applied_changes=applied_changes,
        backups_created=[b[1] for b in backups],
    )


def rollback_applied_backups(backups: list[tuple[str, str]]) -> None:
    """Restore pre-existing backups, ensuring only engine-applied changes are reverted."""
    for orig_path, backup_path in backups:
        try:
            o_path = Path(orig_path)
            b_path = Path(backup_path)
            if b_path.exists():
                shutil.copy2(str(b_path), str(o_path))
                # Delete backup file after successful restore
                b_path.unlink(missing_ok=True)
        except Exception:
            pass


def remove_backups(backups: list[str]) -> None:
    """Delete diagnostic .bak files upon success."""
    for b in backups:
        try:
            Path(b).unlink(missing_ok=True)
        except Exception:
            pass
