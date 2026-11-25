#!/usr/bin/env python3
"""Print the pytest command that covers what you changed.

It does not invent a mapping: it calls ``required_tests`` from the repo's own
commit guard (``scripts/commit_verification.py``), so the answer is exactly what
the commit-msg hook will demand. ``None`` from the guard means the full suite.

Usage (repo root):
    python .claude/skills/grandpa-testing-qa/scripts/which_tests.py            # vs HEAD (staged + unstaged + untracked)
    python .claude/skills/grandpa-testing-qa/scripts/which_tests.py --base main
    python .claude/skills/grandpa-testing-qa/scripts/which_tests.py --files src/grandpa/notes/store.py

Standard library only; it never runs the tests itself.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]


def _load_guard():
    path = REPO / "scripts" / "commit_verification.py"
    spec = importlib.util.spec_from_file_location("commit_verification", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["commit_verification"] = module
    spec.loader.exec_module(module)
    return module


def _git(*args: str) -> list[str]:
    out = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def changed_files(base: str | None) -> list[str]:
    if base:
        return _git("diff", "--name-only", f"{base}...HEAD") + _git(
            "diff", "--name-only", "HEAD"
        )
    return _git("diff", "--name-only", "HEAD") + _git(
        "ls-files", "--others", "--exclude-standard"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Map changed files to the tests the commit guard requires."
    )
    parser.add_argument(
        "--base", help="compare against this ref (e.g. main) instead of HEAD"
    )
    parser.add_argument(
        "--files", nargs="*", help="explicit file list instead of git diff"
    )
    args = parser.parse_args()

    files = sorted(
        set(args.files if args.files is not None else changed_files(args.base))
    )
    # Claude skill files are documentation for the guard's purposes.
    considered = [f for f in files if not f.startswith(".claude/")]
    if not files:
        print("No changed files.")
        return 0
    guard = _load_guard()
    required = guard.required_tests(considered, REPO)
    print("Changed files:")
    for f in files:
        print(f"  {f}")
    print()
    if required is None:
        print(
            "Required: FULL SUITE (a shared test file, a guard, or a package without its own tests changed)"
        )
        print('  uv run python -m pytest -m "not live and not cloud" -q')
        return 0
    paths = " ".join(sorted(required))
    print("Required test paths:")
    for p in sorted(required):
        print(f"  {p}")
    print()
    print(f"  uv run python -m pytest {paths} -q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
