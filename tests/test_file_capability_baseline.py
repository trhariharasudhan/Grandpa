"""What ``search``, ``properties``, ``create_folder`` and ``copy`` do.

These four were implemented twice. ``FileAutomation`` sent them to a
compatibility adapter over the legacy kernel when it had built its own
executor, and to ``FileExecutor`` when one was injected -- so which
implementation served a user command was decided by a construction detail.

This file was written before that fold, from outside ``tests/kernel/``, so the
contract would survive the retirement of the suites that proved the two agreed.
It has now done its job: the kernel is archived, ``FileExecutor`` is the only
implementation, and the behavioural assertions below are unchanged from when
both paths had to satisfy them.

Two things the fold settled, recorded rather than left implicit:

*The parity comparison is gone*, because there is nothing to compare. What it
asserted -- identical status, message, path and resulting filesystem -- is now
simply what this one implementation does, and the cases it covered are still
exercised individually below.

*The one field the two disagreed on has an answer.* On a copy whose source is
missing, the kernel populated ``result.action`` and ``FileExecutor`` left it
``None``. ``FileExecutor``'s behaviour is what survives, so ``None`` it is.
That was the fold-time decision, and it is pinned below so it reads as a
decision rather than an accident.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.files.automation import FileAutomation
from grandpa.files.models import FileOperationResult

CAPABILITIES = ("search", "properties", "create_folder", "copy")
READ_ONLY = ("search", "properties")


@pytest.fixture
def workspace(tmp_path):
    """A small tree both implementations are pointed at."""
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("hello", encoding="utf-8")
    (root / "report.txt").write_text("quarterly", encoding="utf-8")
    (root / "existing").mkdir()
    return root


def _automation(root: Path) -> FileAutomation:
    """The only construction there is now."""
    return FileAutomation(roots=(root,))


BUILDERS = {"executor": _automation}


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _observable(result: FileOperationResult, root: Path) -> tuple:
    """The part of a result a caller can see and depend on.

    Paths are made relative to their own root -- in the ``path`` field and
    inside the message, which quotes absolute paths back to the user. The two
    implementations are exercised against separate trees, so comparing raw
    strings would compare temporary directory names rather than behaviour.
    """
    path = result.path
    if path is not None:
        candidate = Path(path)
        path = (
            str(candidate.relative_to(root))
            if str(candidate).startswith(str(root))
            else str(candidate)
        )
    message = (result.message or "").replace(str(root), "<root>")
    return (result.status, message, path)


# ---------------------------------------------------------------------------
# 1 -- normal success
# ---------------------------------------------------------------------------


class TestNormalSuccess:
    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_search_finds_matching_files(self, path_name, workspace):
        result = BUILDERS[path_name](workspace).handle("search for note")

        assert result.status == "handled"
        assert "note.txt" in (result.message or "")

    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_properties_describes_a_file(self, path_name, workspace):
        result = BUILDERS[path_name](workspace).handle("show properties of note.txt")

        assert result.status == "handled"
        assert "note.txt" in (result.message or "")

    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_create_folder_creates_it(self, path_name, workspace):
        result = BUILDERS[path_name](workspace).handle("create folder alpha")

        assert result.status == "handled"
        assert (workspace / "alpha").is_dir()

    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_copy_creates_the_destination(self, path_name, workspace):
        result = BUILDERS[path_name](workspace).handle("copy note.txt to duplicate.txt")

        assert result.status == "handled"
        assert (workspace / "duplicate.txt").read_text(encoding="utf-8") == "hello"


# ---------------------------------------------------------------------------
# 2 -- the destination already exists
# ---------------------------------------------------------------------------


class TestExistingDestination:
    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_creating_an_existing_folder_asks_rather_than_failing(
        self, path_name, workspace
    ):
        """Both paths treat this as a question, not an error -- and neither
        silently succeeds."""
        result = BUILDERS[path_name](workspace).handle("create folder existing")

        assert result.status == "needs_confirmation"
        assert "already exists" in (result.message or "").lower()

    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_copying_onto_an_existing_file_asks_first(self, path_name, workspace):
        automation = BUILDERS[path_name](workspace)
        automation.handle("copy note.txt to duplicate.txt")

        result = automation.handle("copy note.txt to duplicate.txt")

        assert result.status == "needs_confirmation"
        assert "already exists" in (result.message or "").lower()

    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_the_refusal_leaves_the_destination_untouched(self, path_name, workspace):
        (workspace / "duplicate.txt").write_text("original", encoding="utf-8")

        BUILDERS[path_name](workspace).handle("copy note.txt to duplicate.txt")

        assert (workspace / "duplicate.txt").read_text(encoding="utf-8") == "original"


# ---------------------------------------------------------------------------
# 3 -- filesystem effects
# ---------------------------------------------------------------------------


class TestFilesystemEffects:
    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_copy_preserves_the_source(self, path_name, workspace):
        BUILDERS[path_name](workspace).handle("copy note.txt to duplicate.txt")

        assert (workspace / "note.txt").read_text(encoding="utf-8") == "hello"

    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_copy_adds_exactly_one_entry(self, path_name, workspace):
        before = set(_tree(workspace))

        BUILDERS[path_name](workspace).handle("copy note.txt to duplicate.txt")

        assert set(_tree(workspace)) - before == {"duplicate.txt"}

    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_create_folder_adds_exactly_one_entry(self, path_name, workspace):
        before = set(_tree(workspace))

        BUILDERS[path_name](workspace).handle("create folder alpha")

        assert set(_tree(workspace)) - before == {"alpha"}


# ---------------------------------------------------------------------------
# 5 -- read-only operations really are read-only
# ---------------------------------------------------------------------------


class TestReadOnlyOperations:
    @pytest.mark.parametrize("path_name", BUILDERS)
    @pytest.mark.parametrize(
        "command", ["search for note", "show properties of note.txt"]
    )
    def test_it_does_not_change_the_tree(self, path_name, command, workspace):
        before = _tree(workspace)

        BUILDERS[path_name](workspace).handle(command)

        assert _tree(workspace) == before

    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_it_does_not_change_file_contents(self, path_name, workspace):
        before = {
            path.name: path.read_text(encoding="utf-8")
            for path in workspace.iterdir()
            if path.is_file()
        }

        automation = BUILDERS[path_name](workspace)
        automation.handle("search for note")
        automation.handle("show properties of note.txt")

        after = {
            path.name: path.read_text(encoding="utf-8")
            for path in workspace.iterdir()
            if path.is_file()
        }
        assert after == before


# ---------------------------------------------------------------------------
# 4 -- safety behaviour the two paths share
# ---------------------------------------------------------------------------


class TestSharedSafetyBehaviour:
    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_a_missing_source_is_reported_not_created(self, path_name, workspace):
        result = BUILDERS[path_name](workspace).handle("copy absent.txt to copy.txt")

        assert result.status != "handled"
        assert not (workspace / "copy.txt").exists()

    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_properties_of_a_missing_path_is_reported(self, path_name, workspace):
        result = BUILDERS[path_name](workspace).handle("show properties of absent.txt")

        assert result.status != "handled"

    @pytest.mark.parametrize("path_name", BUILDERS)
    def test_nothing_escapes_the_configured_root(self, path_name, workspace, tmp_path):
        """Both paths are given the same roots and neither reaches outside."""
        outside = tmp_path / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        before = outside.read_text(encoding="utf-8")

        BUILDERS[path_name](workspace).handle(f"copy note.txt to {outside}")

        assert outside.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# 6 -- the two implementations agree
# ---------------------------------------------------------------------------


class TestTheFoldSettledTheDivergence:
    """The single field the two implementations disagreed on."""

    def test_a_copy_with_a_missing_source_leaves_the_action_unset(self, workspace):
        """``FileExecutor``'s answer, which is now the only answer.

        The kernel set ``result.action`` here and ``FileExecutor`` does not.
        Status, message and path were identical either way and no caller reads
        ``action`` off an error result, so nothing observable changed when the
        kernel went -- but the value did change, and this records which one
        won."""
        result = _automation(workspace).handle("copy absent.txt to duplicate.txt")

        assert result.status == "error"
        assert result.action is None


# ---------------------------------------------------------------------------
# What this file deliberately does not claim
# ---------------------------------------------------------------------------


class TestScope:
    def test_the_mutating_two_now_enter_the_action_boundary(self):
        """This previously asserted the opposite, and said so: "when it happens
        this fails, which is the intended reminder to update the claim rather
        than discover it". It happened, so the claim is updated.

        ``create_folder`` and ``copy`` mutate the filesystem and now route
        through the boundary when a runner is supplied; ``search`` and
        ``properties`` mutate nothing, so they have no mutation to route and
        remain outside it.
        """
        from grandpa.files.executor import BOUNDARY_ROUTED_ACTIONS

        assert set(BOUNDARY_ROUTED_ACTIONS) == {
            "create_file",
            "create_folder",
            "copy",
            "delete",
            "move",
            "rename",
        }
        for capability in READ_ONLY:
            assert capability not in BOUNDARY_ROUTED_ACTIONS

    def test_there_is_only_one_implementation_now(self):
        """The construction detail that used to select between two is gone."""
        import importlib

        assert not hasattr(FileAutomation(), "_read_only_kernel")
        for module in ("grandpa.kernel", "grandpa.files.kernel_adapter"):
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(module)

    def test_the_read_only_capabilities_are_named(self):
        assert set(READ_ONLY) == {"search", "properties"}
        assert set(CAPABILITIES) - set(READ_ONLY) == {"create_folder", "copy"}
