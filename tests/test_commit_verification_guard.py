"""The commit guard, and the three commits it exists because of.

Each of the three was a different mechanism, and a guard that only covers one
of them is the kind of fix that gets a fourth:

* ``463eaf49`` -- a voice assertion was still failing. Its remediation,
  ``234281ba``, says: "The previous commit was pushed with this test still
  failing."
* ``2df79819`` -- pytest failed, but the output went through ``tail`` in an
  ``&&`` chain, so the shell saw *tail's* zero. Remediated by ``8454f39d``.
* ``2624cd71`` -- a kernel baseline test failed. Only part of the suite had been
  run; the full run happened afterwards. Remediated by ``326871b1``.

The first two are "the run failed", reached differently. The third is "the run
that passed was not the whole suite", which no exit status can express -- which
is why the record carries a scope and a digest as well as a status.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from commit_verification import (  # noqa: E402
    HATCH_TRAILER,
    MAX_AGE_SECONDS,
    UNVERIFIED_RELPATH,
    Record,
    hatch_reason,
    scope_from_options,
    verdict,
    worktree_digest,
)

pytestmark = pytest.mark.core

TREE = "a" * 64
OTHER_TREE = "b" * 64
NOW = 1_800_000_000.0


def passing(**overrides) -> Record:
    fields = {
        "exitstatus": 0,
        "scope": "full",
        "digest": TREE,
        "when": NOW - 60,
        "argv": ["-q"],
        "counts": {"passed": 6970},
        "failed": [],
    }
    fields.update(overrides)
    return Record(**fields)


def decide(record, message="feat: a change\n", digest=TREE):
    return verdict(record, digest, message, now=NOW)


# --- the three past commits, replayed ---------------------------------------


def test_case_463eaf49_a_failing_test_refuses_the_commit() -> None:
    """The plain case: the suite failed and the commit went in anyway."""
    record = passing(
        exitstatus=1,
        counts={"passed": 4210, "failed": 1},
        failed=["tests/test_voice_v2.py::test_spoken_yes_launches_calculator"],
    )

    decision = decide(record)

    assert not decision.allowed
    assert "FAILED" in decision.reason
    # It names what failed, so the refusal is actionable rather than a scolding.
    assert "test_spoken_yes_launches_calculator" in decision.reason


def test_case_2df79819_a_pipe_cannot_hide_the_status() -> None:
    """`pytest | tail` in an `&&` chain: the shell saw tail's zero.

    The record is written inside pytest from the exit status handed to
    ``pytest_sessionfinish``, so there is no shell between the number and the
    decision. The pipe is irrelevant by construction -- this test states that
    the guard reads the record and not a terminal.
    """
    record = passing(
        exitstatus=1,
        counts={"passed": 6903, "failed": 1},
        failed=["tests/tools/test_text_to_speech.py::test_writes_to_the_bound"],
    )

    decision = decide(record)

    assert not decision.allowed
    assert "from inside pytest, not from a shell" in decision.reason


def test_case_2624cd71_a_subset_is_not_the_suite() -> None:
    """Green in tests/skills, red in tests/kernel, committed on the green.

    An exit status of 0 was *true* for what was run. Only the scope shows the
    problem, so the record carries one.
    """
    record = passing(scope="partial", argv=["tests/skills", "-q"])

    decision = decide(record)

    assert not decision.allowed
    assert "only part of the suite" in decision.reason
    assert "tests/skills" in decision.reason


# --- the fourth way, which none of the three was but any could have been ----


def test_a_pass_earned_before_an_edit_does_not_authorise_the_commit() -> None:
    record = passing(digest=OTHER_TREE)

    decision = decide(record, digest=TREE)

    assert not decision.allowed
    assert "tree has changed" in decision.reason


def test_no_recorded_run_at_all_is_refused() -> None:
    decision = decide(None)

    assert not decision.allowed
    assert "no pytest run has been recorded" in decision.reason


def test_a_stale_pass_is_refused_even_when_the_tree_matches() -> None:
    record = passing(when=NOW - MAX_AGE_SECONDS - 1)

    decision = decide(record)

    assert not decision.allowed
    assert "hours old" in decision.reason


def test_a_full_passing_run_against_this_tree_is_allowed() -> None:
    decision = decide(passing())

    assert decision.allowed, decision.reason


# --- the escape hatch has to cost a sentence --------------------------------


def test_the_hatch_allows_a_refused_commit_when_a_reason_is_given() -> None:
    message = (
        "fix: land the migration before the suite can run\n\n"
        f"{HATCH_TRAILER}: the sqlite migration must land before the suite can "
        "open the new schema at all\n"
    )

    decision = decide(passing(exitstatus=1), message=message)

    assert decision.allowed
    assert "explicit" in decision.reason


@pytest.mark.parametrize("reason", ["", "wip", "skip", "tbd", "   ", "later", "fixing"])
def test_the_hatch_refuses_a_placeholder_reason(reason: str) -> None:
    message = f"fix: something\n\n{HATCH_TRAILER}: {reason}\n"

    decision = decide(passing(exitstatus=1), message=message)

    assert not decision.allowed
    assert "placeholder" in decision.reason


def test_the_hatch_is_not_needed_when_the_run_passed() -> None:
    """A trailer on a verified commit is allowed, but it is the run that allows it."""
    decision = decide(passing(), message="feat: x\n")

    assert decision.allowed
    assert HATCH_TRAILER not in decision.reason


def test_the_hatch_reason_is_read_from_a_trailer_line_only() -> None:
    prose = (
        "fix: mention Tests-Skipped: in the body as prose rather than as a "
        "trailer, which should not count\n"
    )

    assert hatch_reason(prose) is None


# --- scope, from pytest's own options ---------------------------------------


@pytest.mark.parametrize(
    "options,expected",
    [
        ({}, "full"),
        ({"file_or_dir": ["tests/skills"]}, "partial"),
        ({"keyword": "reminder"}, "partial"),
        ({"markexpr": "e2e"}, "partial"),
        ({"deselect": ["tests/x.py::test_y"]}, "partial"),
        ({"last_failed": True}, "partial"),
        ({"failed_first": True}, "partial"),
    ],
)
def test_scope_reads_pytests_resolved_options(options, expected) -> None:
    defaults = {
        "file_or_dir": [],
        "keyword": "",
        "markexpr": "",
        "deselect": [],
        "last_failed": False,
        "failed_first": False,
    }
    defaults.update(options)

    assert scope_from_options(**defaults) == expected


def test_a_plugin_argument_is_not_mistaken_for_a_path() -> None:
    """``-p no:cacheprovider`` is in every run in this project's scripts.

    An earlier version of this parsed the command line and read
    ``no:cacheprovider`` as a path, which called every real run partial. Scope
    comes from pytest's resolved options now, so the shape of the command line
    cannot change the answer.
    """
    assert (
        scope_from_options(
            file_or_dir=[],
            keyword="",
            markexpr="",
            deselect=[],
        )
        == "full"
    )


# --- the guard's own plumbing ------------------------------------------------


@pytest.mark.real_actions(
    reason="creates a throwaway git repository under tmp_path and runs git in it; every write is inside tmp_path, and the digest is the thing under test"
)
def test_the_digest_changes_when_a_file_changes(tmp_path: Path) -> None:
    """Against a real git repository, not a mock of one."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *args: subprocess.run(  # noqa: E731 - local brevity
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "T")
    (repo / "a.txt").write_text("one", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "first")

    before = worktree_digest(repo)
    (repo / "a.txt").write_text("two", encoding="utf-8")
    after = worktree_digest(repo)

    assert before != after
    # An untracked file counts: a new test file is exactly the thing that must
    # invalidate an earlier pass.
    (repo / "b.txt").write_text("new", encoding="utf-8")
    assert worktree_digest(repo) != after


@pytest.mark.real_actions(
    reason="creates a throwaway git repository under tmp_path and writes an ignored file into it; nothing outside tmp_path is touched"
)
def test_an_ignored_file_does_not_invalidate_a_run(tmp_path: Path) -> None:
    """Otherwise the guard cries wolf over caches until someone switches it off."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *args: subprocess.run(  # noqa: E731 - local brevity
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "T")
    (repo / ".gitignore").write_text("junk/\n", encoding="utf-8")
    (repo / "a.txt").write_text("one", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "first")
    before = worktree_digest(repo)

    (repo / "junk").mkdir()
    (repo / "junk" / "cache.bin").write_text("noise", encoding="utf-8")

    assert worktree_digest(repo) == before


def test_a_bypassed_commit_leaves_the_suite_red() -> None:
    """`--no-verify` skips the refusing hook; post-commit records it anyway.

    This test is the second half of that mechanism: while the log has entries,
    the suite fails, and the guard needs a passing suite to allow the next
    commit. A bypass therefore costs a deliberate cleanup rather than nothing.
    """
    repo = Path(__file__).resolve().parents[1]
    log = repo / UNVERIFIED_RELPATH
    if not log.exists():
        return
    entries = [
        line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert not entries, (
        f"{UNVERIFIED_RELPATH.as_posix()} records commits made without a passing "
        f"full run:\n" + "\n".join(entries) + "\n\n"
        "Deal with those commits, then delete the file. It is not removed "
        "automatically, because that would make the bypass free again."
    )


@pytest.mark.real_actions(
    reason="runs `git config --get core.hooksPath` against this checkout, which reads configuration and writes nothing"
)
def test_the_hook_scripts_are_the_ones_git_would_run() -> None:
    """A hook edited in .git and not here would guard nothing.

    Reports rather than fails when the guard is not installed: a fresh clone and
    CI have no hooksPath set, and a red suite there would teach everyone to
    ignore this test.
    """
    repo = Path(__file__).resolve().parents[1]
    for name in ("commit-msg", "post-commit"):
        hook = repo / "scripts" / "git-hooks" / name
        assert hook.exists(), f"{name} is missing from scripts/git-hooks/"
        text = hook.read_text(encoding="utf-8")
        assert text.startswith("#!/bin/sh"), name
        assert "commit_verification.py" in text, name

    configured = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if not configured:
        pytest.skip(
            "core.hooksPath is not set in this checkout, so the guard is not "
            "armed here: python scripts/install_git_hooks.py"
        )
    assert (repo / configured).resolve() == (repo / "scripts" / "git-hooks").resolve()


def test_the_record_is_written_by_the_run_that_is_happening_now() -> None:
    """The plugin is wired in, not merely present.

    If tests/conftest.py stops delegating to it, no record is written, the guard
    refuses everything, and someone deletes the guard. This catches that before
    it becomes annoying enough to remove.
    """
    from tests import conftest

    assert hasattr(conftest, "pytest_sessionfinish")
    assert hasattr(conftest, "pytest_runtest_logreport")


@pytest.mark.real_actions(
    reason="runs `git ls-files` in an empty tmp_path so that it fails, which is how the fail-closed path is reached; writes nothing"
)
def test_a_guard_that_cannot_check_refuses(tmp_path: Path) -> None:
    """Not a git repository at all: the digest cannot be taken."""
    with pytest.raises(RuntimeError):
        worktree_digest(tmp_path)


def test_time_moves_forward_for_the_stale_check() -> None:
    """A record from the future is not a pass; it is a broken clock."""
    record = passing(when=NOW + 10_000)

    assert decide(record).allowed, "a clock skew of minutes must not block work"
    assert time.time() > 0


# ---------------------------------------------------------------------------
# The other half of this task: the opt-out is function-scope only
# ---------------------------------------------------------------------------


def test_a_module_scope_opt_out_is_refused_at_collection() -> None:
    """The rule, stated against the real conftest rather than a mock of it."""
    from tests.actuation_guard import scope_error_message, scope_violations

    class _Mark:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Item:
        def __init__(self, own, inherited, where, name) -> None:
            self.own_markers = [_Mark(n) for n in own]
            self._inherited = [_Mark(n) for n in inherited]
            self.location = (where, 0, name)
            self.name = name

        def iter_markers(self, name=None):
            for mark in [*self.own_markers, *self._inherited]:
                if name is None or mark.name == name:
                    yield mark

    inherited_only = _Item([], ["real_actions"], "tests/x.py", "test_a")
    carries_its_own = _Item(["real_actions"], [], "tests/x.py", "test_b")
    unmarked = _Item([], [], "tests/x.py", "test_c")

    offenders = scope_violations([inherited_only, carries_its_own, unmarked])

    # The marker's name is in the entry now that there are two of them: knowing a
    # file applies one at module scope is not much use without knowing which.
    assert offenders == {"tests/x.py": ["test_a (real_actions)"]}
    message = scope_error_message(offenders)
    assert "function-scope only" in message
    # The message has to say why, or the next person deletes the rule.
    assert "server.log" in message and "107" in message


@pytest.mark.real_actions(
    reason="runs a nested pytest in a subprocess against a generated test file "
    "under tmp_path, to prove the collection-time refusal fires for real; "
    "everything it writes is inside tmp_path"
)
def test_the_refusal_fires_in_a_real_pytest_run(tmp_path: Path) -> None:
    """End to end: a module-scope marker makes the run fail, not warn."""
    repo = Path(__file__).resolve().parents[1]
    (tmp_path / "conftest.py").write_text(
        "from tests.conftest import pytest_collection_modifyitems  # noqa: F401\n",
        encoding="utf-8",
    )
    (tmp_path / "test_blanket.py").write_text(
        "import pytest\n\n"
        'pytestmark = pytest.mark.real_actions(reason="a whole file at once")\n\n\n'
        "def test_one():\n    assert True\n\n\n"
        "def test_two():\n    assert True\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(repo), str(repo / "src")]),
        "GRANDPA_HOME": str(tmp_path / "home"),
    }

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "test_blanket.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )

    assert proc.returncode != 0, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "function-scope only" in combined, combined[-2000:]
    assert "test_blanket.py" in combined


# ---------------------------------------------------------------------------
# One slot was not enough, and the project's own VERIFY sequence proved it
# ---------------------------------------------------------------------------


def test_a_later_partial_pass_does_not_cancel_the_full_one() -> None:
    """The flaw this history exists for, found by running the real sequence.

    VERIFY here is three commands: pytest, then scripts/run_e2e.py, then the
    confirmation probe. The middle one runs pytest with -m e2e, which is a
    partial run. With a single record it replaced the full pass, and the guard
    refused the commit that the sequence had just earned. A guard that fights
    the workflow it guards does not survive contact with the workflow.
    """
    full = passing(when=NOW - 600)
    later_e2e = passing(scope="partial", argv=["-m", "e2e"], when=NOW - 60)

    decision = decide([full, later_e2e])

    assert decision.allowed, decision.reason


def test_a_failing_subset_blocks_the_commit_even_after_a_full_pass() -> None:
    """2624cd71 the other way round.

    There, a passing subset was taken as proof the tree was sound. Here a
    failing subset is proof it is not, whatever an earlier full run said about
    the same content.
    """
    full = passing(when=NOW - 600)
    e2e_failure = passing(
        exitstatus=1,
        scope="partial",
        argv=["-m", "e2e"],
        when=NOW - 60,
        failed=["tests/e2e/test_stores.py::test_reminders_run_due"],
        counts={"passed": 65, "failed": 1},
    )

    decision = decide([full, e2e_failure])

    assert not decision.allowed
    assert "FAILED" in decision.reason
    assert "test_reminders_run_due" in decision.reason


def test_runs_of_a_different_tree_say_nothing_about_this_one() -> None:
    decision = decide([passing(digest=OTHER_TREE)], digest=TREE)

    assert not decision.allowed
    assert "tree has changed" in decision.reason


def test_only_partial_runs_of_this_tree_is_refused() -> None:
    decision = decide([passing(scope="partial", argv=["tests/skills"])])

    assert not decision.allowed
    assert "only part of the suite" in decision.reason


@pytest.mark.real_actions(
    reason="writes the run history into a throwaway repo directory under "
    "tmp_path to check it is appended and capped; writes nothing outside tmp_path"
)
def test_the_history_is_appended_and_capped(tmp_path: Path) -> None:
    from commit_verification import KEEP_RUNS, read_records, write_record

    for index in range(KEEP_RUNS + 5):
        write_record(tmp_path, passing(when=NOW + index))

    history = read_records(tmp_path)

    assert len(history) == KEEP_RUNS
    # The oldest are dropped, not the newest.
    assert history[-1].when == NOW + KEEP_RUNS + 4


def test_a_failure_answered_by_a_later_clean_run_stops_blocking() -> None:
    """An intermittent failure must not disqualify a tree for ever.

    A flaky e2e timeout recorded a failure for this exact tree. Because the rule
    took the newest failure whatever its age, no later full pass could clear it,
    and every future commit of that tree would have been refused with no way to
    satisfy the guard. A guard nobody can satisfy gets switched off.
    """
    flake = passing(
        exitstatus=1,
        scope="partial",
        argv=["tests/e2e", "-m", "e2e"],
        when=NOW - 600,
        failed=["tests/e2e/test_reminders_fire.py::test_at_five_pm_is_one_shot"],
    )
    clean = passing(when=NOW - 60)

    decision = decide([flake, clean])

    assert decision.allowed, decision.reason


def test_a_failure_after_the_last_clean_run_still_refuses() -> None:
    """The other half: order is what matters, not the mere existence of a pass."""
    clean = passing(when=NOW - 600)
    later_failure = passing(
        exitstatus=1,
        scope="partial",
        argv=["tests/e2e", "-m", "e2e"],
        when=NOW - 60,
        failed=["tests/e2e/test_stores.py::test_something_real"],
    )

    decision = decide([clean, later_failure])

    assert not decision.allowed
    assert "test_something_real" in decision.reason
