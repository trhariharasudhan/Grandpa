"""Whether the thing being committed has actually been tested.

Three commits in this project were made on top of a failing test suite:

* ``463eaf49`` -- a voice assertion was still failing; remediated by
  ``234281ba``, whose message says "The previous commit was pushed with this
  test still failing."
* ``2df79819`` -- pytest failed, but its output was piped through ``tail`` in an
  ``&&`` chain, so the shell saw *tail's* exit code, which was 0. Remediated by
  ``8454f39d``.
* ``2624cd71`` -- a kernel baseline test failed. Only a subset of the suite had
  been run before committing, and the full run that would have shown it was
  read afterwards. Remediated by ``326871b1``.

Each was a different mechanism, and only the middle one is about pipes. What
they share is that the commit depended on a human (or an agent) correctly
reading a result. This module removes that dependency:

* pytest records its own exit status from inside the run
  (``pytest_sessionfinish``), so no pipe, ``tail``, ``&&`` chain or swallowed
  status can misreport it -- the number never passes through a shell;
* the record names the *scope* of the run, so a subset cannot stand in for the
  suite; and
* the record carries a content digest of the working tree, so a pass earned
  before an edit does not authorise a commit made after it.

The commit-msg hook calls :func:`verdict`. It refuses; it does not warn.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

RECORD_RELPATH = Path("runtime") / "verification" / "runs.json"
UNVERIFIED_RELPATH = Path("runtime") / "verification" / "unverified.log"

KEEP_RUNS = 25
"""Why a history and not one slot: this project verifies with three commands --
`pytest -q`, then `scripts/run_e2e.py`, then the confirmation probe -- and the
middle one runs `pytest -m e2e`, which is a *partial* run. With one slot it
overwrote the full pass and the guard refused the very commit that sequence was
meant to authorise. A guard that fights the workflow it guards gets deleted, so
it keeps the last few runs and looks for the evidence it needs among them."""

MAX_AGE_SECONDS = 24 * 60 * 60
"""A digest match already proves the content is identical, so age is a second
line rather than the first. It is here because the *environment* can move --
a dependency upgrade, a rebuilt extension -- while the tree does not."""

HATCH_TRAILER = "Tests-Skipped"
MIN_HATCH_REASON = 20

_PLACEHOLDER = re.compile(
    r"^(wip|tbd|todo|later|skip(ping)?|n/?a|none|test(s)?|fix(ing)?|because)\W*$",
    re.IGNORECASE,
)


@dataclass
class Record:
    """What one pytest run knows about itself."""

    exitstatus: int
    scope: str
    digest: str
    when: float
    argv: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    version: int = 1

    @classmethod
    def from_json(cls, text: str) -> "Record | None":
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                exitstatus=int(data["exitstatus"]),
                scope=str(data["scope"]),
                digest=str(data["digest"]),
                when=float(data["when"]),
                argv=list(data.get("argv") or []),
                counts=dict(data.get("counts") or {}),
                failed=list(data.get("failed") or []),
                version=int(data.get("version", 1)),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1, sort_keys=True)


# ---------------------------------------------------------------------------
# What the tree currently contains
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        input=stdin,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def worktree_digest(repo: Path) -> str:
    """A digest of every file git would let you commit, by content.

    Tracked and untracked-but-not-ignored, hashed by ``git hash-object`` so the
    digest follows git's own idea of content. Ignored files are excluded: a
    pytest cache or a build artifact changing is not a reason to re-run the
    suite, and including them would make the guard cry wolf until it was
    switched off -- which is how guards die.
    """
    listing = _git(repo, "ls-files", "-co", "--exclude-standard")
    paths = [line for line in listing.splitlines() if line]
    if not paths:
        return hashlib.sha256(b"").hexdigest()
    hashes = _git(
        repo, "hash-object", "--stdin-paths", stdin="\n".join(paths) + "\n"
    ).split()
    if len(hashes) != len(paths):
        raise RuntimeError(
            f"hashed {len(hashes)} objects for {len(paths)} paths; refusing to "
            "guess which is which"
        )
    digest = hashlib.sha256()
    for path, blob in sorted(zip(paths, hashes)):
        digest.update(path.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(blob.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def scope_from_options(
    *,
    file_or_dir: list[str] | None,
    keyword: str | None,
    markexpr: str | None,
    deselect: list[str] | None,
    last_failed: bool = False,
    failed_first: bool = False,
) -> str:
    """ "full" when this run could see every test, "partial" when it could not.

    ``2624cd71`` is the case this exists for: the suite was green in the part I
    had run, and the failure was in a directory I had not. A subset is evidence
    about a subset.

    These come from pytest's own resolved options rather than from parsing a
    command line. Parsing it here got ``-p no:cacheprovider`` wrong -- it read
    ``no:cacheprovider`` as a path to run and called every one of my own runs
    partial -- and any such parser is one new pytest option away from lying.
    """
    if file_or_dir:
        return "partial"
    if (keyword or "").strip():
        return "partial"
    if (markexpr or "").strip():
        return "partial"
    if deselect:
        return "partial"
    if last_failed or failed_first:
        return "partial"
    return "full"


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


@dataclass
class Verdict:
    allowed: bool
    reason: str

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.allowed


def hatch_reason(message: str) -> str | None:
    """The reason given on a ``Tests-Skipped:`` trailer, if it is a real one.

    The hatch has to cost something, and what it costs is a sentence that stays
    in the commit for good. A placeholder is not a reason: "wip" explains
    nothing to whoever reads the log later, which is the only thing the trailer
    is for.
    """
    for line in message.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith(HATCH_TRAILER.lower() + ":"):
            continue
        reason = stripped.split(":", 1)[1].strip()
        if len(reason) < MIN_HATCH_REASON or _PLACEHOLDER.match(reason):
            return ""
        return reason
    return None


def evidence_for(
    records: list[Record], digest: str
) -> tuple[Record | None, Record | None]:
    """The newest full pass for this tree, and the newest failure for this tree.

    A failure counts whatever its scope. A subset that fails is still proof that
    this tree is broken -- which is ``2624cd71`` read the other way round, where
    a subset that passed was taken as proof that it was not.

    The failure it returns is only one that is *newer* than the newest full pass.
    An older one has been answered: the suite has been run clean since. Without
    that, a single flaky run disqualified a tree permanently -- an intermittent
    e2e timeout did exactly this, and no amount of re-running could clear it,
    because the failure stayed the newest failure for ever. A guard nobody can
    satisfy gets switched off, so this is a correctness fix and not a softening:
    a failure after the last clean run still refuses.
    """
    same_tree = [record for record in records if record.digest == digest]
    passes = [r for r in same_tree if r.exitstatus == 0 and r.scope == "full"]
    failures = [r for r in same_tree if r.exitstatus != 0]
    newest_pass = max(passes, key=lambda r: r.when) if passes else None
    newest_failure = max(failures, key=lambda r: r.when) if failures else None
    if newest_pass is not None and newest_failure is not None:
        if newest_failure.when <= newest_pass.when:
            newest_failure = None
    return newest_pass, newest_failure


def verdict(
    records: "list[Record] | Record | None",
    current_digest: str,
    message: str,
    *,
    now: float | None = None,
) -> Verdict:
    """Allow or refuse this commit. Pure, so the past cases can be replayed."""
    now = time.time() if now is None else now
    hatch = hatch_reason(message)
    if records is None:
        history: list[Record] = []
    elif isinstance(records, Record):
        history = [records]
    else:
        history = list(records)

    passed, failed = evidence_for(history, current_digest)

    problem: str | None = None
    if failed is not None:
        names = "".join(f"\n      {name}" for name in failed.failed[:10])
        more = (
            f"\n      ... and {len(failed.failed) - 10} more"
            if len(failed.failed) > 10
            else ""
        )
        problem = (
            f"a recorded pytest run of this exact tree FAILED (exit status "
            f"{failed.exitstatus}).{names}{more}\n"
            f"  Counts: {failed.counts or 'unknown'}\n"
            f"      pytest {' '.join(failed.argv)}\n"
            "  This status came from inside pytest, not from a shell, so a pipe\n"
            "  or a tail cannot have hidden it."
        )
    elif passed is None:
        if not history:
            problem = (
                "no pytest run has been recorded for this checkout.\n"
                "  The record is written by pytest itself, so running the suite is\n"
                "  the only way to produce one."
            )
        else:
            newest = max(history, key=lambda r: r.when)
            if newest.digest != current_digest:
                problem = (
                    "the tree has changed since the last run, so that run did not\n"
                    "  test what is about to be committed.\n"
                    f"      tested:     {newest.digest[:12]}\n"
                    f"      committing: {current_digest[:12]}"
                )
            else:
                problem = (
                    "the runs recorded for this tree covered only part of the "
                    "suite,\n"
                    "  the most recent being:\n"
                    f"      pytest {' '.join(newest.argv)}\n"
                    "  A subset passing is evidence about the subset. Run the whole\n"
                    "  suite, or say why not."
                )
    elif now - passed.when > MAX_AGE_SECONDS:
        age_hours = (now - passed.when) / 3600
        problem = (
            f"the last passing run is {age_hours:.0f} hours old. The tree has not\n"
            "  changed, but the environment may have. Run it again."
        )

    if problem is None:
        return Verdict(True, "a full pytest run passed against exactly this tree.")

    if hatch is None:
        return Verdict(
            False,
            f"Refusing this commit: {problem}\n\n"
            f"  Run the suite:   python -m pytest -q\n"
            f"  Then commit again. The result is recorded by pytest, so you do\n"
            f"  not have to remember to read it.\n\n"
            f"  If this commit genuinely must go in unverified, say why in the\n"
            f"  commit message and it will be allowed:\n"
            f"      {HATCH_TRAILER}: <why, at least {MIN_HATCH_REASON} characters>\n"
            f"  That line stays in the commit, which is the point of it.",
        )
    if not hatch:
        return Verdict(
            False,
            f"Refusing this commit: {problem}\n\n"
            f"  There is a {HATCH_TRAILER}: trailer, but its reason is empty, too\n"
            f"  short (minimum {MIN_HATCH_REASON} characters) or a placeholder.\n"
            f"  The trailer is read by whoever finds this commit later.",
        )
    return Verdict(
        True,
        f"Unverified, allowed by an explicit {HATCH_TRAILER} trailer: {hatch}",
    )


# ---------------------------------------------------------------------------
# Reading and writing the record
# ---------------------------------------------------------------------------


def record_path(repo: Path) -> Path:
    return repo / RECORD_RELPATH


def read_records(repo: Path) -> list[Record]:
    """Every run still on file, oldest first. Unreadable entries are dropped."""
    try:
        raw = json.loads(record_path(repo).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    found = [Record.from_json(json.dumps(item)) for item in raw]
    return [record for record in found if record is not None]


def write_record(repo: Path, record: Record) -> Path:
    """Append this run to the history, keeping the most recent ``KEEP_RUNS``."""
    path = record_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    history = [*read_records(repo), record][-KEEP_RUNS:]
    path.write_text(
        json.dumps([asdict(item) for item in history], indent=1, sort_keys=True),
        encoding="utf-8",
    )
    return path


def repo_root(start: Path | None = None) -> Path:
    here = Path(start or os.getcwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "src").exists():
            return candidate
    return here


def audit_head(repo: Path, *, now: float | None = None) -> str | None:
    """Record HEAD if it was committed without verification. Returns the note.

    Called from ``post-commit``, which ``--no-verify`` does not skip. The commit
    exists by now, so this cannot refuse it; what it can do is leave a mark that
    makes the next commit fail until someone removes it deliberately.
    """
    try:
        message = _git(repo, "log", "-1", "--format=%B")
        head = _git(repo, "rev-parse", "HEAD").strip()
        subject = _git(repo, "log", "-1", "--format=%s").strip()
        digest = worktree_digest(repo)
    except (RuntimeError, OSError):
        return None
    decision = verdict(read_records(repo), digest, message, now=now)
    if decision.allowed:
        return None
    note = (
        f"{time.strftime('%Y-%m-%d %H:%M:%S')} {head[:12]} {subject}\n"
        f"    committed without a passing full run and without a "
        f"{HATCH_TRAILER} trailer\n"
    )
    path = repo / UNVERIFIED_RELPATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(note)
    except OSError:
        return None
    print(
        f"\ncommit guard: {head[:12]} was committed WITHOUT verification.\n"
        f"  Recorded in {UNVERIFIED_RELPATH.as_posix()}, and the suite will fail\n"
        f"  while that file has entries. Deal with it, then delete the file.\n",
        file=sys.stderr,
    )
    return note


def main(argv: list[str] | None = None) -> int:
    """The hook's entry point: ``commit_verification.py <message-file>``."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: commit_verification.py <commit-message-file>", file=sys.stderr)
        return 2
    if argv[0] == "--audit-head":
        audit_head(repo_root())
        # Never fail the commit that already happened; the mark is the point.
        return 0
    repo = repo_root()
    try:
        message = Path(argv[0]).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"commit guard: cannot read the commit message: {exc}", file=sys.stderr)
        return 1
    try:
        digest = worktree_digest(repo)
    except (RuntimeError, OSError) as exc:
        # Fail closed. A guard that lets the commit through when it cannot tell
        # is not a guard, and this is the failure mode that produced the hatch.
        print(
            f"commit guard: cannot digest the working tree ({exc}).\n"
            "Refusing, because a guard that cannot check must not approve.",
            file=sys.stderr,
        )
        return 1
    decision = verdict(read_records(repo), digest, message)
    if decision.allowed:
        print(f"commit guard: {decision.reason}")
        return 0
    print(f"\n{decision.reason}\n", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
