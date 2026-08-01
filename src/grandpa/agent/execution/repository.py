"""Git repository inspection interface for Agent Execution Engine V2."""

from __future__ import annotations

import subprocess
from pathlib import Path

from grandpa.agent.execution.models import RepositoryState


def inspect_repository(repo_path: str) -> RepositoryState:
    """Safely run read-only git queries to retrieve RepositoryState."""
    path = Path(repo_path).resolve()

    # Defaults
    current_branch = "unknown"
    head_commit = "unknown"
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    conflicted: list[str] = []

    if not (path / ".git").exists():
        # Check if parent contains .git to handle subfolders
        parent_git = False
        for p in path.parents:
            if (p / ".git").exists():
                parent_git = True
                break
        if not parent_git:
            return RepositoryState(
                repo_root=str(path),
                current_branch=current_branch,
                head_commit=head_commit,
                is_clean=True,
            )

    def run_git(args: list[str]) -> str:
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=str(path),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return ""

    # 1. Get branch
    branch_out = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if branch_out:
        current_branch = branch_out

    # 2. Get commit hash
    commit_out = run_git(["rev-parse", "--short", "HEAD"])
    if commit_out:
        head_commit = commit_out

    # 3. Parse status --short
    status_out = run_git(["status", "--short"])
    if status_out:
        for line in status_out.splitlines():
            if len(line) < 4:
                continue
            code = line[:2]
            filepath = line[3:].strip()

            # Remove quotes or arrow details if renamed
            if " -> " in filepath:
                filepath = filepath.split(" -> ")[-1].strip()
            filepath = filepath.strip('"')

            # Short code mapping:
            # X: index, Y: working tree
            # '??' - Untracked
            # 'A ' / 'M ' - Staged changes
            # ' M' / ' D' - Unstaged changes
            # 'UU' / 'AA' / 'DD' - Conflicted
            if code == "??":
                untracked.append(filepath)
            elif code in ("UU", "AA", "DD", "U ", " U"):
                conflicted.append(filepath)
            else:
                if code[0] in ("M", "A", "D", "R"):
                    staged.append(filepath)
                if code[1] in ("M", "D"):
                    unstaged.append(filepath)

    is_clean = len(staged) == 0 and len(unstaged) == 0 and len(untracked) == 0 and len(conflicted) == 0

    return RepositoryState(
        repo_root=str(path),
        current_branch=current_branch,
        head_commit=head_commit,
        staged_files=sorted(list(set(staged))),
        unstaged_files=sorted(list(set(unstaged))),
        untracked_files=sorted(list(set(untracked))),
        conflicted_files=sorted(list(set(conflicted))),
        is_clean=is_clean,
    )
