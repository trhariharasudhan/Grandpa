"""Refuse to finish a turn that leaves finished work where the user cannot get it.

Two shapes, because it has now failed in both:

* a commit on this branch that is on no remote;
* tracked files modified and never committed at all.

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

**The second shape, added later and for the same reason.** The commit check
asks which commits are on no remote. A tree with uncommitted modifications has
*zero* unpushed commits, so a finished, verified, uncommitted branch read as
clean and the turn ended. The user merged and got nothing -- the third time
work has failed to arrive, and the third different shape.

It is the same family as the run-integrity guard this ships beside: the commit
guard fires when a run FINISHES and so cannot see a run that was killed; this
hook fired on COMMITS and so could not see work that was never committed. In
both the absence is the thing that matters, and absence is what neither looked
for.

**Narrow on purpose, and the narrowing is the point.** This does not fire on
any dirty tree. Most turns of a multi-task job end with edits in progress, and
a hook that fires on all of them gets switched off -- the objection was already
written into this file's own tests, from the round the hook was built: "work in
progress is not the failure ... Blocking on uncommitted changes would fire on
every turn of every task."

What it fires on is work that is *finished*: a complete, full-scope, passing
pytest run exists for the tree exactly as it stands, and no commit was made
from it. That is the signature of the failure that happened -- the branch was
verified and then stranded -- and it cannot be the signature of work in
progress, because work in progress has not passed a full run.

Tracked files only, too. Untracked files are scratch probes and notes.
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


UNCOMMITTED_HINT = """Refusing to end the turn: this tree PASSED a full run and was never committed.

  branch: {branch}
{listing}

A complete, full-scope pytest run passed against the tree exactly as it stands.
That is finished work, not work in progress -- and it is sitting where the user
cannot get it.

This is the third shape of the same failure. The commit check above asks which
commits are on no remote, and a tree with uncommitted changes has none, so a
verified branch that was never committed read as clean and the turn ended. The
user merged and got nothing.

  git add -A && git commit && git push -u origin {branch}

then report the real `git ls-remote origin {branch}` output.

If you are deliberately not committing this -- an experiment you are about to
throw away -- say so to the user and finish. This blocks once and then lets the
turn through.
"""


def _verified_tree() -> bool:
    """Whether a full run has passed against the tree exactly as it stands.

    Read from the commit guard's own record, so there is one definition of
    "verified" rather than two that can drift apart. Anything that cannot be
    answered -- no scripts directory, no record, an unreadable file -- is
    False: this hook must never block on a tree it cannot judge.
    """
    try:
        import sys as _sys

        scripts = Path(__file__).resolve().parents[1]
        if str(scripts) not in _sys.path:
            _sys.path.insert(0, str(scripts))
        from commit_verification import (  # noqa: PLC0415
            evidence_for,
            read_records,
            repo_root,
            source_root,
            worktree_digest,
        )

        repo = repo_root()
        digest = worktree_digest(repo)
        passed, _failed = evidence_for(
            read_records(repo), digest, source_root(repo)
        )
        return passed is not None
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return False


def uncommitted_changes() -> tuple[str, list[str]] | None:
    """``(branch, ["M path", ...])`` for a VERIFIED but uncommitted tree.

    None unless a complete, full-scope run has passed against the tree exactly
    as it stands. Work in progress has not passed one, which is what keeps
    this off every ordinary turn.

    ``--untracked-files=no`` on purpose: untracked files are scratch probes and
    notes.
    """
    inside = _git("rev-parse", "--is-inside-work-tree")
    if inside != "true":
        return None
    listing = _git("status", "--porcelain", "--untracked-files=no")
    if listing is None or not listing:
        return None
    lines = [line for line in listing.splitlines() if line.strip()]
    if not lines:
        return None
    if not _verified_tree():
        # Mid-task. Nothing has proved this tree is finished, so there is
        # nothing to say about it not being committed.
        return None
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    return branch, lines


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
    if found is not None:
        branch, commits = found
        listing = "\n".join(f"    {line}" for line in commits)
        print(
            HINT.format(count=len(commits), branch=branch, listing=listing),
            file=sys.stderr,
        )
        # Exit status 2 is what tells Claude Code to block and show stderr.
        return 2

    # Then the work that never became a commit at all. Second, because an
    # unpushed commit is the more specific complaint and naming both at once
    # would bury it.
    pending = uncommitted_changes()
    if pending is not None:
        branch, lines = pending
        listing = "\n".join(f"    {line}" for line in lines[:12])
        if len(lines) > 12:
            listing += f"\n    ... and {len(lines) - 12} more"
        print(
            UNCOMMITTED_HINT.format(
                count=len(lines), branch=branch, listing=listing
            ),
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
