"""V1-T4: the commit guard asks for the touched packages' tests plus a fast
action-layer smoke, and leaves the full suite to CI.

What did NOT change is replayed here too: the run must be of exactly this
tree, finished, unfiltered and passing; a failing run of this tree refuses
whatever its scope; and harness or dependency changes still need everything.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from commit_verification import (  # noqa: E402
    SMOKE_PATH,
    Record,
    covers,
    path_only_selection,
    required_tests,
    verdict,
)

pytestmark = pytest.mark.core

TREE = "a" * 64
NOW = 1_800_000_000.0
SRC = "/repo/src"


def run(
    paths: list[str], *, exitstatus: int = 0, scope: str = "partial", **kw
) -> Record:
    fields = {
        "exitstatus": exitstatus,
        "scope": scope,
        "digest": TREE,
        "when": NOW - 60,
        "argv": ["-q", *paths],
        "paths": paths,
        "source": SRC,
    }
    fields.update(kw)
    return Record(**fields)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for d in ("tests/action_layer", "tests/memory", "tests/voice", "tests/scripts"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "tests" / "test_reminders.py").write_text("", encoding="utf-8")
    return tmp_path


# --- what a commit requires -------------------------------------------------


def test_package_change_needs_its_tests_and_the_smoke(repo):
    need = required_tests(["src/grandpa/memory/store.py"], repo)
    assert need == frozenset({"tests/memory", SMOKE_PATH})


def test_docs_only_change_needs_only_the_smoke(repo):
    assert required_tests(["docs/ROADMAP.md", "README.md"], repo) == {SMOKE_PATH}


def test_top_level_module_maps_to_its_test_files(repo):
    need = required_tests(["src/grandpa/reminders.py"], repo)
    assert need == frozenset({"tests/test_reminders.py", SMOKE_PATH})


def test_test_file_change_needs_that_file(repo):
    need = required_tests(["tests/voice/test_vad.py"], repo)
    assert need == frozenset({"tests/voice/test_vad.py", SMOKE_PATH})


def test_package_conftest_needs_its_directory(repo):
    need = required_tests(["tests/voice/conftest.py"], repo)
    assert need == frozenset({"tests/voice", SMOKE_PATH})


def test_other_top_level_dirs_map_to_tests_of_the_same_name(repo):
    need = required_tests(["scripts/validate_daily_use.py"], repo)
    assert need == frozenset({"tests/scripts", SMOKE_PATH})


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "uv.lock",
        "src/grandpa/__init__.py",
        "scripts/commit_verification.py",
        "tests/conftest.py",
        "tests/actuation_guard.py",
        "tests/verification_plugin.py",
        "tests/fixtures/sample.json",
        "src/grandpa/kernel/baseline.py",  # no tests/kernel in this repo fixture
        "src/grandpa/nothing_tests_this.py",
    ],
)
def test_harness_dependency_or_untested_changes_need_the_full_suite(repo, path):
    assert required_tests([path, "docs/x.md"], repo) is None


# --- what a run covers ------------------------------------------------------


def test_covers_directories_and_files_under_them():
    need = frozenset({"tests/memory", SMOKE_PATH})
    assert covers(["tests/memory", "tests/action_layer"], need)
    assert covers(["tests"], need)
    assert not covers(["tests/memory"], need)  # smoke missing
    assert not covers(["tests/memory/test_store.py", SMOKE_PATH], need)
    assert not covers([], need)


def test_filtered_runs_record_no_paths(tmp_path):
    common = {
        "file_or_dir": ["tests/memory"],
        "invocation_dir": tmp_path,
        "repo": tmp_path,
    }
    assert path_only_selection(**common, keyword="", markexpr="", deselect=[]) == [
        "tests/memory"
    ]
    assert (
        path_only_selection(**common, keyword="store", markexpr="", deselect=[]) == []
    )
    assert path_only_selection(**common, keyword="", markexpr="core", deselect=[]) == []
    assert path_only_selection(**common, keyword="", markexpr="", deselect=["x"]) == []
    assert (
        path_only_selection(
            **common, keyword="", markexpr="", deselect=[], last_failed=True
        )
        == []
    )


def test_node_ids_do_not_count_as_a_path(tmp_path):
    got = path_only_selection(
        file_or_dir=["tests/memory/test_a.py::test_one", "tests/action_layer"],
        keyword="",
        markexpr="",
        deselect=[],
        invocation_dir=tmp_path,
        repo=tmp_path,
    )
    assert got == ["tests/action_layer"]


# --- the verdict ------------------------------------------------------------


def test_scoped_pass_allows_the_commit():
    need = frozenset({"tests/memory", SMOKE_PATH})
    decision = verdict(
        [run(["tests/memory", SMOKE_PATH])],
        TREE,
        "feat: x",
        now=NOW,
        source=SRC,
        required=need,
    )
    assert decision.allowed, decision.reason
    assert "CI" in decision.reason


def test_scoped_pass_without_the_smoke_is_refused():
    need = frozenset({"tests/memory", SMOKE_PATH})
    decision = verdict(
        [run(["tests/memory"])], TREE, "feat: x", now=NOW, source=SRC, required=need
    )
    assert not decision.allowed
    assert "tests/action_layer" in decision.reason


def test_the_2624cd71_case_still_refuses():
    """A subset passed; the failure was in a directory not run."""
    need = frozenset({"tests/kernel", SMOKE_PATH})
    decision = verdict(
        [run(["tests/memory", SMOKE_PATH])],
        TREE,
        "feat: x",
        now=NOW,
        source=SRC,
        required=need,
    )
    assert not decision.allowed


def test_harness_change_still_needs_a_full_run():
    decision = verdict(
        [run(["tests/memory", SMOKE_PATH])],
        TREE,
        "feat: x",
        now=NOW,
        source=SRC,
        required=None,
    )
    assert not decision.allowed
    full = run([], scope="full")
    assert verdict([full], TREE, "feat: x", now=NOW, source=SRC, required=None).allowed


def test_a_newer_failure_of_this_tree_still_refuses():
    need = frozenset({"tests/memory", SMOKE_PATH})
    good = run(["tests/memory", SMOKE_PATH], when=NOW - 120)
    bad = run(["tests/voice"], exitstatus=1, when=NOW - 30, failed=["tests/voice/t::x"])
    decision = verdict([good, bad], TREE, "feat: x", now=NOW, source=SRC, required=need)
    assert not decision.allowed
    assert "FAILED" in decision.reason


def test_scoped_pass_of_another_tree_does_not_count():
    need = frozenset({"tests/memory", SMOKE_PATH})
    other = run(["tests/memory", SMOKE_PATH], digest="b" * 64)
    assert not verdict([other], TREE, "x", now=NOW, source=SRC, required=need).allowed


def test_scoped_pass_that_imported_another_checkout_does_not_count():
    need = frozenset({"tests/memory", SMOKE_PATH})
    elsewhere = run(["tests/memory", SMOKE_PATH], source="/other/src")
    assert not verdict(
        [elsewhere], TREE, "x", now=NOW, source=SRC, required=need
    ).allowed


def test_full_run_still_satisfies_a_scoped_requirement():
    need = frozenset({"tests/memory", SMOKE_PATH})
    full = run([], scope="full")
    assert verdict([full], TREE, "x", now=NOW, source=SRC, required=need).allowed


def test_refusal_names_the_command_to_run():
    need = frozenset({"tests/memory", SMOKE_PATH})
    decision = verdict([], TREE, "x", now=NOW, source=SRC, required=need)
    assert not decision.allowed
    assert "python -m pytest -q tests/action_layer tests/memory" in decision.reason
