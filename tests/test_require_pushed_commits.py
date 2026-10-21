"""The hook that refuses to finish a turn with a commit on no remote.

Twice now, work has been reported as delivered while it sat in a local branch:
``fix/vad-contradiction`` for three rounds, and round four of the orb for
another. The ls-remote reporting rule was added after the first and did not
catch the second, because the failure was an *omission* -- the turn that made
the commit never ran the command, so there was no line to quote and nothing to
contradict the claim.

Tested at two levels, which is what the guard in ``tests/actuation_guard.py``
asks for: the decision is exercised directly with git stubbed, because the
decision is the part with the branches in it, and a few marked cases run the
hook as the harness runs it -- in a subprocess, against a real repository in a
temporary directory -- because a git question answered entirely by doubles only
proves the doubles.

As important as the blocking cases are the quiet ones. A hook that refuses too
much gets removed, and then nothing guards this at all.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

HOOK = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "hooks"
    / "require_pushed_commits.py"
)

sys.path.insert(0, str(HOOK.parent))

import require_pushed_commits as hook  # noqa: E402


def stub_git(monkeypatch, answers: dict[tuple[str, ...], str | None]) -> list[tuple]:
    """Replace the hook's git with a lookup. Returns the calls made."""
    calls: list[tuple] = []

    def fake(*args: str):
        calls.append(args)
        for prefix, answer in answers.items():
            if args[: len(prefix)] == prefix:
                return answer
        return ""

    monkeypatch.setattr(hook, "_git", fake)
    return calls


IN_A_REPO = {
    ("rev-parse", "--is-inside-work-tree"): "true",
    ("remote",): "origin",
    ("rev-parse", "--abbrev-ref", "HEAD"): "feat/thing",
}


# --- the decision ------------------------------------------------------------


def test_an_unpushed_commit_is_found(monkeypatch) -> None:
    """The exact shape: committed, verified, reported, never pushed."""
    stub_git(
        monkeypatch,
        {**IN_A_REPO, ("log",): "871da8a1 the commit nobody pushed"},
    )

    found = hook.unpushed_commits()

    assert found == ("feat/thing", ["871da8a1 the commit nobody pushed"])


def test_every_unpushed_commit_is_counted(monkeypatch) -> None:
    stub_git(
        monkeypatch,
        {**IN_A_REPO, ("log",): "aaa one\nbbb two\nccc three"},
    )

    branch, commits = hook.unpushed_commits()

    assert branch == "feat/thing"
    assert len(commits) == 3


def test_nothing_is_reported_when_everything_is_pushed(monkeypatch) -> None:
    stub_git(monkeypatch, {**IN_A_REPO, ("log",): ""})

    assert hook.unpushed_commits() is None


def test_nothing_is_reported_outside_a_repository(monkeypatch) -> None:
    stub_git(monkeypatch, {("rev-parse", "--is-inside-work-tree"): None})

    assert hook.unpushed_commits() is None


def test_nothing_is_reported_with_no_remote_configured(monkeypatch) -> None:
    """Nothing can be unpushed from a repository with nowhere to push."""
    stub_git(
        monkeypatch,
        {("rev-parse", "--is-inside-work-tree"): "true", ("remote",): ""},
    )

    assert hook.unpushed_commits() is None


def test_nothing_is_reported_on_a_detached_head(monkeypatch) -> None:
    """There is no branch to push and no claim being made about one."""
    stub_git(
        monkeypatch,
        {
            ("rev-parse", "--is-inside-work-tree"): "true",
            ("remote",): "origin",
            ("rev-parse", "--abbrev-ref", "HEAD"): "HEAD",
        },
    )

    assert hook.unpushed_commits() is None


def test_a_git_that_cannot_run_is_not_a_blocked_turn(monkeypatch) -> None:
    stub_git(monkeypatch, {**IN_A_REPO, ("log",): None})

    assert hook.unpushed_commits() is None


def test_the_question_is_asked_about_head_and_not_every_branch(
    monkeypatch,
) -> None:
    """**The scope that keeps it usable.** The object store is shared with the
    main checkout and every other worktree, so asking about all local branches
    would block this turn because of another session's work in progress. That
    is the wolf-crying failure the heredoc hook's own docstring warns about."""
    calls = stub_git(monkeypatch, {**IN_A_REPO, ("log",): ""})

    hook.unpushed_commits()

    log = next(args for args in calls if args[0] == "log")

    assert "HEAD" in log
    assert "--not" in log and "--remotes" in log
    assert "--branches" not in log, "it would see other sessions' branches"
    assert "--all" not in log


# --- what it says ------------------------------------------------------------


def test_the_message_names_the_branch_and_the_push_command(monkeypatch) -> None:
    """So the fix is in the message rather than something to look up."""
    stub_git(monkeypatch, {**IN_A_REPO, ("log",): "871da8a1 work"})
    monkeypatch.setattr(
        "sys.stdin", _Stdin(json.dumps({"stop_hook_active": False}))
    )

    captured = _capture_stderr(monkeypatch)
    code = hook.main()

    assert code == 2
    message = "".join(captured)
    assert "feat/thing" in message
    assert "git push -u origin feat/thing" in message
    assert "871da8a1 work" in message
    assert "1 commit(s)" in message


def test_a_retry_is_let_through(monkeypatch) -> None:
    """A push that is genuinely refused -- straight to main, for instance --
    must be reportable rather than trapping the turn in a loop. One unmissable
    interruption, then the floor is the user's."""
    stub_git(monkeypatch, {**IN_A_REPO, ("log",): "871da8a1 unpushable"})
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps({"stop_hook_active": True})))

    assert hook.main() == 0


def test_malformed_input_never_breaks_the_session(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", _Stdin("not json at all"))

    assert hook.main() == 0


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


def _capture_stderr(monkeypatch) -> list[str]:
    written: list[str] = []

    class Sink:
        def write(self, text: str) -> int:
            written.append(text)
            return len(text)

        def flush(self) -> None:
            return None

    monkeypatch.setattr("sys.stderr", Sink())
    return written


# --- and against a real repository, as the harness runs it -------------------


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def a_pushed_repo(tmp_path: Path) -> Path:
    """A repository whose branch is fully pushed to a real bare remote."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(
        ["git", "init", "-q", "--bare", str(remote)], check=True, capture_output=True
    )
    repo = tmp_path / "work"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "a.txt").write_text("one", encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-qm", "first")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "main")
    return repo


def run_hook(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=repo,
        input=json.dumps({"stop_hook_active": False}),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.real_actions(
    reason="runs the hook as the harness runs it -- a subprocess reading JSON on "
    "stdin -- against a real git repository built in tmp_path. A git question "
    "answered entirely by doubles only proves the doubles. Nothing outside "
    "tmp_path is touched: the remote is a bare repo in the same directory."
)
def test_it_blocks_a_real_unpushed_commit(tmp_path: Path) -> None:
    repo = a_pushed_repo(tmp_path)
    (repo / "b.txt").write_text("two", encoding="utf-8")
    git(repo, "add", "b.txt")
    git(repo, "commit", "-qm", "the commit nobody pushed")

    result = run_hook(repo)

    assert result.returncode == 2, result.stderr
    assert "on no remote" in result.stderr
    assert "the commit nobody pushed" in result.stderr
    assert "git push -u origin main" in result.stderr


@pytest.mark.real_actions(
    reason="the other half of the same check, in the same tmp_path repository: "
    "a fully pushed branch must not block, or the hook fires on every turn and "
    "gets deleted."
)
def test_it_is_quiet_about_a_real_pushed_branch(tmp_path: Path) -> None:
    assert run_hook(a_pushed_repo(tmp_path)).returncode == 0


@pytest.mark.real_actions(
    reason="proves the scope against real git: another branch left unpushed in "
    "the same tmp_path repository must not block, because the object store is "
    "shared between this project's worktrees."
)
def test_it_ignores_a_real_unpushed_branch_that_is_not_head(tmp_path: Path) -> None:
    repo = a_pushed_repo(tmp_path)
    git(repo, "checkout", "-q", "-b", "somebody-elses-wip")
    (repo / "e.txt").write_text("theirs", encoding="utf-8")
    git(repo, "add", "e.txt")
    git(repo, "commit", "-qm", "their unpushed work")
    git(repo, "checkout", "-q", "main")

    assert run_hook(repo).returncode == 0


@pytest.mark.real_actions(
    reason="work in progress is not the failure, checked against real git in "
    "tmp_path. Blocking on uncommitted changes would fire on every turn of "
    "every task."
)
def test_it_is_quiet_about_real_uncommitted_changes(tmp_path: Path) -> None:
    repo = a_pushed_repo(tmp_path)
    (repo / "a.txt").write_text("edited but not committed", encoding="utf-8")

    assert run_hook(repo).returncode == 0


# --- and it is actually registered -------------------------------------------


def settings() -> dict:
    return json.loads(
        (Path(__file__).resolve().parents[1] / ".claude" / "settings.json").read_text(
            encoding="utf-8"
        )
    )


def test_the_hook_is_wired_to_the_stop_event() -> None:
    """A hook nobody runs is a comment. This is the assertion that would have
    failed if it had been written and never registered -- which is the same
    class of mistake as a commit that was made and never pushed."""
    stop_hooks = settings().get("hooks", {}).get("Stop") or []
    commands = [
        entry_hook.get("command", "")
        for entry in stop_hooks
        for entry_hook in entry.get("hooks", [])
    ]

    assert any("require_pushed_commits.py" in command for command in commands), (
        f"the Stop hooks are {commands}"
    )


def test_the_other_hooks_are_still_registered() -> None:
    """Adding one must not displace the two that already guard this project."""
    everything = json.dumps(settings())

    assert "block_escaped_heredoc.py" in everything
    assert "require_sandboxed_probe.py" in everything


# --- work that was finished and never committed --------------------------------
#
# The commit check asks which commits are on no remote. A tree with uncommitted
# modifications has zero of those, so a finished, verified, uncommitted branch
# read as clean and the turn ended. The user merged and got nothing. Third
# time, third shape.
#
# Narrowed to VERIFIED trees, because the objection above is right: blocking on
# any dirty tree would fire on every turn of every task. A tree that has passed
# a full run is not work in progress.


@pytest.mark.real_actions(
    reason="builds a real git repository in tmp_path and asks git about it. A "
    "git question answered entirely by doubles only proves the doubles. "
    "Nothing outside tmp_path is touched."
)
def test_work_in_progress_is_still_not_reported(tmp_path, monkeypatch) -> None:
    """The decision from the round this hook was built, kept.

    Nothing has proved this tree is finished, so there is nothing to say about
    it not being committed.
    """
    repo = a_pushed_repo(tmp_path)
    (repo / "a.txt").write_text("edited, mid-task", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(hook, "_verified_tree", lambda: False)

    assert hook.uncommitted_changes() is None


@pytest.mark.real_actions(
    reason="builds a real git repository in tmp_path and asks git about it. A "
    "git question answered entirely by doubles only proves the doubles. "
    "Nothing outside tmp_path is touched."
)
def test_a_verified_tree_that_was_never_committed_is_reported(
    tmp_path, monkeypatch
) -> None:
    """The failure that happened: finished, verified, stranded."""
    repo = a_pushed_repo(tmp_path)
    (repo / "a.txt").write_text("finished and verified", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(hook, "_verified_tree", lambda: True)

    found = hook.uncommitted_changes()

    assert found is not None
    _branch, lines = found
    assert any("a.txt" in line for line in lines)


@pytest.mark.real_actions(
    reason="builds a real git repository in tmp_path and asks git about it. A "
    "git question answered entirely by doubles only proves the doubles. "
    "Nothing outside tmp_path is touched."
)
def test_a_clean_tree_reports_nothing(tmp_path, monkeypatch) -> None:
    repo = a_pushed_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(hook, "_verified_tree", lambda: True)

    assert hook.uncommitted_changes() is None


@pytest.mark.real_actions(
    reason="builds a real git repository in tmp_path and asks git about it. A "
    "git question answered entirely by doubles only proves the doubles. "
    "Nothing outside tmp_path is touched."
)
def test_untracked_files_do_not_count(tmp_path, monkeypatch) -> None:
    """Scratch probes, build output and notes."""
    repo = a_pushed_repo(tmp_path)
    (repo / "scratch_probe.py").write_text("# notes", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(hook, "_verified_tree", lambda: True)

    assert hook.uncommitted_changes() is None


@pytest.mark.real_actions(
    reason="builds a real git repository in tmp_path and asks git about it. A "
    "git question answered entirely by doubles only proves the doubles. "
    "Nothing outside tmp_path is touched."
)
def test_staged_changes_count_too(tmp_path, monkeypatch) -> None:
    """Staged but uncommitted is still work the user cannot get."""
    repo = a_pushed_repo(tmp_path)
    (repo / "a.txt").write_text("changed", encoding="utf-8")
    git(repo, "add", "a.txt")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(hook, "_verified_tree", lambda: True)

    assert hook.uncommitted_changes() is not None


@pytest.mark.real_actions(
    reason="builds a real git repository in tmp_path and asks git about it. A "
    "git question answered entirely by doubles only proves the doubles. "
    "Nothing outside tmp_path is touched."
)
def test_a_tree_it_cannot_judge_is_never_blocked_on(tmp_path, monkeypatch) -> None:
    """No record, no scripts directory, an unreadable file -- all False.

    A hook that blocks on a tree it cannot judge is a hook that blocks work
    for no reason anybody can act on.
    """
    repo = a_pushed_repo(tmp_path)
    (repo / "a.txt").write_text("changed", encoding="utf-8")
    monkeypatch.chdir(repo)

    # The real _verified_tree, against a repository with no record at all.
    assert hook._verified_tree() is False
    assert hook.uncommitted_changes() is None


def test_the_message_says_it_passed_rather_than_merely_changed() -> None:
    """The distinction is the whole reason this fires at all, so the text has
    to carry it -- otherwise it reads as the wolf-crying rule it is not."""
    assert "PASSED a full run" in hook.UNCOMMITTED_HINT
    assert "work in progress" in hook.UNCOMMITTED_HINT
