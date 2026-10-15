"""Refuse to finish a turn that leaves a commit on this branch unpushed.

This has now cost this project twice. ``fix/vad-contradiction`` went three
rounds with the work sitting in a local branch while it was reported as
delivered, and the ``git ls-remote`` reporting rule was added afterwards. Round
four went the same way: commit one was made and never pushed, commit two was
never committed at all, and three replies described both as working on a
machine that had neither.

**Why a resolution to be careful is not the fix.** The rule was already in
place and was already being followed in form -- ls-remote output was quoted,
round after round. What failed was not the quoting but the *omission*: the turn
where a commit was made simply never ran the command, so there was no line to
quote and nothing contradicted the claim. A rule that depends on remembering to
check cannot catch the turn where checking was forgotten.

So this checks instead of asking. ``git log HEAD --not --remotes`` is the whole
question: which commits reachable from here are on no remote. In this
repository that set should always be empty at the end of a turn, because the
commit guard already refuses a commit unless a full test run passed against
exactly that tree -- every commit here is a finished unit, and a finished unit
has no reason to stay local.

**Scope, deliberately narrow.** ``HEAD``, not ``--branches``: the object store
is shared with the main checkout and every other worktree, so asking about all
local branches would block this turn because of another session's
work-in-progress. That is the wolf-crying failure the heredoc hook's own
docstring warns about, and a hook that cries wolf gets deleted.

**It blocks once, not forever.** If the stop hook is already active -- Claude
Code sets ``stop_hook_active`` when a previous block is being retried -- this
returns 0. A push that is genuinely refused, as a push straight to ``main``
rightly is, must not trap the turn in a loop; it must be reportable. One
unmissable interruption, then the floor is yours.

Considered and rejected: scanning the final message for a quoted ls-remote line
and verifying it against the remote. It is a real check and it would catch a
*false* claim, but the failure here was an absent claim -- there was no line to
check. Verifying what was said cannot catch what was not said.
"""

from __future__ import annotations

import json
import subprocess
import sys

HINT = """Refusing to end the turn: {count} commit(s) on this branch are on no remote.

  branch: {branch}
{listing}

This is the failure that cost fix/vad-contradiction three rounds and round four
another one: work reported as delivered while it sat in a local branch. The
ls-remote rule did not catch it, because the turn that made the commit never ran
the command.

Push it:

  git push -u origin {branch}

then report the real `git ls-remote origin {branch}` output.

If the push is genuinely refused -- straight to main, for instance -- say so to
the user and finish. This blocks once and then lets the turn through.
"""


def _git(*args: str) -> str | None:
    """Run git and return stdout, or None if it could not be run at all."""
    try:
        done = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def unpushed_commits() -> tuple[str, list[str]] | None:
    """``(branch, ["sha subject", ...])`` for commits on no remote, or None.

    None means there is nothing to say: not a repository, no remotes, a
    detached HEAD, or everything is pushed.
    """
    inside = _git("rev-parse", "--is-inside-work-tree")
    if inside != "true":
        return None
    if not _git("remote"):
        # No remote configured. Nothing can be unpushed.
        return None
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        # Detached. There is no branch to push and no claim to make about one.
        return None
    listing = _git("log", "--oneline", "--no-decorate", "HEAD", "--not", "--remotes")
    if listing is None or not listing:
        return None
    return branch, [line for line in listing.splitlines() if line.strip()]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return 0
    if payload.get("stop_hook_active"):
        # Already blocked once for this stop. Blocking again would trap the
        # turn, and an unpushable commit has to be reportable.
        return 0
    found = unpushed_commits()
    if found is None:
        return 0
    branch, commits = found
    listing = "\n".join(f"    {line}" for line in commits)
    print(
        HINT.format(count=len(commits), branch=branch, listing=listing),
        file=sys.stderr,
    )
    # Exit status 2 is what tells Claude Code to block and show stderr.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
