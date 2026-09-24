"""Install the commit guard's hooks, for this worktree only.

Git resolves ``core.hooksPath`` from the *shared* repository config, so a plain
install would arm the guard in the main checkout and in every other worktree at
once -- including any session working in one right now. That is somebody else's
machine state.

So this uses git's per-worktree config: ``extensions.worktreeConfig`` plus
``core.hooksPath`` written with ``--worktree``, which confines the setting to the
worktree it is run from. ``--check`` reports without changing anything, and
``--uninstall`` puts it back.

Run with ``--shared`` to install the old way, for every worktree at once. That
is the right choice for a single-checkout clone and the wrong one for a machine
with several sessions on it, so it is not the default.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

HOOKS = ("commit-msg", "post-commit")


def git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def repo_root() -> Path:
    return Path(git("rev-parse", "--show-toplevel"))


def committed_hooks_dir(repo: Path) -> Path:
    return repo / "scripts" / "git-hooks"


def configured_hooks_path(repo: Path) -> str | None:
    proc = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    value = proc.stdout.strip()
    return value or None


def status(repo: Path) -> tuple[bool, str]:
    """Whether the guard is armed here, and a sentence saying so."""
    configured = configured_hooks_path(repo)
    wanted = committed_hooks_dir(repo)
    if configured is None:
        return False, (
            "core.hooksPath is not set, so git is using .git/hooks and the "
            "commit guard is NOT armed."
        )
    resolved = (
        (repo / configured).resolve()
        if not Path(configured).is_absolute()
        else Path(configured).resolve()
    )
    if resolved != wanted.resolve():
        return False, f"core.hooksPath is {configured!r}, not the committed {wanted}."
    missing = [name for name in HOOKS if not (wanted / name).exists()]
    if missing:
        return False, f"core.hooksPath points here but these are missing: {missing}"
    return True, f"the commit guard is armed: core.hooksPath -> {configured}"


def install(repo: Path, *, shared: bool) -> None:
    relative = committed_hooks_dir(repo).relative_to(repo).as_posix()
    if shared:
        git("config", "core.hooksPath", relative, cwd=repo)
        print(
            f"Installed for EVERY worktree of {repo}: core.hooksPath = {relative}\n"
            f"  Undo with: git config --unset core.hooksPath"
        )
        return
    git("config", "extensions.worktreeConfig", "true", cwd=repo)
    git("config", "--worktree", "core.hooksPath", relative, cwd=repo)
    print(
        f"Installed for this worktree only: core.hooksPath = {relative}\n"
        f"  Undo with: git config --worktree --unset core.hooksPath\n"
        f"  (extensions.worktreeConfig was set to true; it only makes\n"
        f"   --worktree settings possible and changes nothing on its own.)"
    )


def uninstall(repo: Path) -> None:
    for args in (
        ("config", "--worktree", "--unset", "core.hooksPath"),
        ("config", "--unset", "core.hooksPath"),
    ):
        subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    print("core.hooksPath unset. The commit guard is no longer armed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report, change nothing")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument(
        "--shared",
        action="store_true",
        help="install for every worktree of this repository, not just this one",
    )
    args = parser.parse_args()
    repo = repo_root()
    if args.check:
        armed, sentence = status(repo)
        print(sentence)
        return 0 if armed else 1
    if args.uninstall:
        uninstall(repo)
        return 0
    install(repo, shared=args.shared)
    armed, sentence = status(repo)
    print(sentence)
    return 0 if armed else 1


if __name__ == "__main__":
    raise SystemExit(main())
