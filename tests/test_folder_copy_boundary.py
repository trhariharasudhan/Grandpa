"""``create_folder`` and ``copy`` reach the disk through the boundary too.

Four file mutations already route through ``run_local_action`` when a caller
supplies a mutation runner: ``create_file``, ``delete``, ``move``, ``rename``.
Two did not. ``_create`` returned as soon as it had called ``mkdir``, before
reaching ``_route``, and ``_move_or_copy`` gated routing behind ``if move:`` --
so the copy branch fell through to ``shutil.copy2``.

The consequence was narrow but real: on the voice path, which is the caller
that supplies a runner, creating a folder or copying a file ran during an
emergency stop, ignored dry run, produced no audit record and carried no
provenance. Every other file mutation on that same path honoured all four.

Neither action needed a new action type or a new tier. ``file_copy`` already
exists at MEDIUM, and the boundary's ``file_create`` executor already accepts
``kind="folder"`` -- so this is routing, not policy. Nothing here changes what
the tiers are, only which code path reaches the disk.

Callers that supply no runner are untouched, exactly as the other four are:
routing is opt-in and this slice does not change who opts in.

Nothing real is executed: the runner is a recorder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from grandpa import pc_control
from grandpa.files.executor import BOUNDARY_ROUTED_ACTIONS, FileExecutor
from grandpa.files.parser import FileParser
from grandpa.files.safety import FileSafetyPolicy


class RecordingRunner:
    """Stands in for ``run_local_action``, recording instead of acting."""

    def __init__(self, status: str = "completed") -> None:
        self.payloads: list[dict[str, Any]] = []
        self.status = status

    def __call__(self, payload: dict[str, Any]):
        self.payloads.append(dict(payload))
        return pc_control.LocalActionResponse(
            ok=self.status == "completed",
            action_id=None,
            status=self.status,  # type: ignore[arg-type]
            message="recorded",
            approval_required=self.status == "approval_required",
            risk_level="MEDIUM",
            evidence={},
        )


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("hello", encoding="utf-8")
    (root / "existing").mkdir()
    return root


def _executor(workspace: Path, runner=None, **kwargs) -> FileExecutor:
    return FileExecutor(
        roots=(workspace,),
        safety=FileSafetyPolicy(),
        mutation_runner=runner,
        **kwargs,
    )


def _run(executor: FileExecutor, command: str, *, confirm=None):
    action = FileParser().parse(command)
    assert action is not None, command
    return executor.execute(action, confirm=confirm)


ROUTED = [
    ("create folder alpha", "file_create", "create_folder"),
    ("copy note.txt to duplicate.txt", "file_copy", "copy"),
]


# ---------------------------------------------------------------------------
# A, B -- both actions now reach the boundary
# ---------------------------------------------------------------------------


class TestTheyEnterTheBoundary:
    def test_both_are_listed_as_boundary_routed(self):
        assert {"create_folder", "copy"} <= set(BOUNDARY_ROUTED_ACTIONS)

    @pytest.mark.parametrize(("command", "action_type", "_action"), ROUTED)
    def test_the_mutation_goes_through_the_runner(
        self, command, action_type, _action, workspace
    ):
        runner = RecordingRunner()

        _run(_executor(workspace, runner), command)

        assert [p["action_type"] for p in runner.payloads] == [action_type]

    def test_creating_a_folder_asks_the_boundary_for_a_folder(self, workspace):
        """No new action type: the boundary's ``file_create`` already accepts
        a folder kind."""
        runner = RecordingRunner()

        _run(_executor(workspace, runner), "create folder alpha")

        assert runner.payloads[0]["args"]["kind"] == "folder"

    def test_neither_touches_the_disk_when_routed(self, workspace):
        """The runner performs the mutation; the executor must not also do it."""
        runner = RecordingRunner()
        executor = _executor(workspace, runner)

        _run(executor, "create folder alpha")
        _run(executor, "copy note.txt to duplicate.txt")

        assert not (workspace / "alpha").exists()
        assert not (workspace / "duplicate.txt").exists()

    @pytest.mark.parametrize(("command", "_action_type", "_action"), ROUTED)
    def test_a_caller_without_a_runner_is_untouched(
        self, command, _action_type, _action, workspace
    ):
        """Routing is opt-in and stays that way; this slice does not change
        who opts in."""
        result = _run(_executor(workspace), command)

        assert result.status == "handled"
        assert (workspace / "alpha").exists() or (workspace / "duplicate.txt").exists()


# ---------------------------------------------------------------------------
# C -- ordinary execution still works
# ---------------------------------------------------------------------------


class TestNormalExecution:
    @pytest.mark.parametrize(("command", "_action_type", "_action"), ROUTED)
    def test_a_completed_response_reads_as_handled(
        self, command, _action_type, _action, workspace
    ):
        result = _run(_executor(workspace, RecordingRunner()), command)

        assert result.status == "handled"

    @pytest.mark.parametrize(("command", "_action_type", "_action"), ROUTED)
    def test_neither_is_staged_for_approval_by_default(
        self, command, _action_type, _action, workspace
    ):
        """MEDIUM alone does not prompt; that is unchanged policy, restated so
        a tier change would be noticed here."""
        runner = RecordingRunner()
        _run(_executor(workspace, runner), command)
        payload = runner.payloads[0]

        request = pc_control.LocalActionRequest(
            action_type=payload["action_type"], target=payload["target"]
        )
        assert pc_control._launch_needs_approval(request) is False

    def test_the_tiers_are_the_existing_ones(self):
        def tier(action_type: str) -> str:
            return pc_control.classify_risk(
                pc_control.LocalActionRequest(action_type=action_type, target="x")
            )

        assert tier("file_create") == "LOW"
        assert tier("file_copy") == "MEDIUM"


# ---------------------------------------------------------------------------
# D -- dry run
# ---------------------------------------------------------------------------


class TestDryRun:
    @pytest.mark.parametrize(("command", "_action_type", "_action"), ROUTED)
    def test_the_flag_reaches_the_boundary(
        self, command, _action_type, _action, workspace
    ):
        runner = RecordingRunner(status="dry_run")

        _run(_executor(workspace, runner, dry_run=True), command)

        assert runner.payloads[0]["dry_run"] is True

    @pytest.mark.parametrize(("command", "_action_type", "_action"), ROUTED)
    def test_nothing_is_written(self, command, _action_type, _action, workspace):
        before = sorted(p.name for p in workspace.iterdir())

        _run(
            _executor(workspace, RecordingRunner(status="dry_run"), dry_run=True),
            command,
        )

        assert sorted(p.name for p in workspace.iterdir()) == before


# ---------------------------------------------------------------------------
# E -- emergency stop
# ---------------------------------------------------------------------------


class TestEmergencyStop:
    @pytest.fixture
    def stopped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "a.jsonl"))
        monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(tmp_path / "approvals.db"))
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
        )
        monkeypatch.setattr(pc_control, "_EMERGENCY_STOP_ACTIVE", True)

        def explode(request, risk, **kwargs):
            raise AssertionError(f"{request.action_type} executed during a stop")

        monkeypatch.setattr(pc_control, "_execute", explode)
        yield
        pc_control.reset_emergency_stop()

    @pytest.mark.parametrize(("command", "_action_type", "_action"), ROUTED)
    def test_the_real_boundary_refuses_it(
        self, command, _action_type, _action, workspace, stopped
    ):
        """Through ``run_local_action`` itself, not a recorder: the stop that
        already covers delete and move now covers these two."""
        result = _run(_executor(workspace, pc_control.run_local_action), command)

        assert result.status == "blocked"

    @pytest.mark.parametrize(("command", "_action_type", "_action"), ROUTED)
    def test_nothing_reaches_the_disk(
        self, command, _action_type, _action, workspace, stopped
    ):
        before = sorted(p.name for p in workspace.iterdir())

        _run(_executor(workspace, pc_control.run_local_action), command)

        assert sorted(p.name for p in workspace.iterdir()) == before


# ---------------------------------------------------------------------------
# F, G -- approval, identity and provenance
# ---------------------------------------------------------------------------


class TestApprovalAndProvenance:
    @pytest.mark.parametrize(("command", "_action_type", "_action"), ROUTED)
    def test_a_staged_response_reads_as_needing_confirmation(
        self, command, _action_type, _action, workspace
    ):
        result = _run(
            _executor(workspace, RecordingRunner(status="approval_required")), command
        )

        assert result.status == "needs_confirmation"
        assert result.requires_confirmation is True

    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    @pytest.mark.parametrize(("command", "_action_type", "_action"), ROUTED)
    def test_provenance_reaches_the_boundary(
        self, command, _action_type, _action, origin, workspace
    ):
        runner = RecordingRunner()

        _run(_executor(workspace, runner, origin=origin), command)

        assert runner.payloads[0]["origin"] == origin

    @pytest.mark.parametrize(("command", "_action_type", "_action"), ROUTED)
    def test_the_target_reaching_the_boundary_is_the_resolved_path(
        self, command, _action_type, _action, workspace
    ):
        """What is classified and audited must be what would be written."""
        runner = RecordingRunner()

        _run(_executor(workspace, runner), command)

        assert Path(runner.payloads[0]["target"]).is_absolute()
        assert str(workspace) in runner.payloads[0]["target"]


# ---------------------------------------------------------------------------
# H, I -- file-domain safety still runs first
# ---------------------------------------------------------------------------


class TestFileDomainSafetyPreserved:
    def test_an_existing_folder_still_asks_before_routing(self, workspace):
        """The overwrite confirmation has no equivalent inside the boundary,
        so it must still run on this side of it."""
        runner = RecordingRunner()

        result = _run(_executor(workspace, runner), "create folder existing")

        assert result.status == "needs_confirmation"
        assert runner.payloads == []

    def test_an_existing_copy_destination_still_asks_before_routing(self, workspace):
        (workspace / "duplicate.txt").write_text("original", encoding="utf-8")
        runner = RecordingRunner()

        result = _run(_executor(workspace, runner), "copy note.txt to duplicate.txt")

        assert result.status == "needs_confirmation"
        assert runner.payloads == []

    def test_a_missing_source_is_refused_before_routing(self, workspace):
        runner = RecordingRunner()

        result = _run(_executor(workspace, runner), "copy absent.txt to copy.txt")

        assert result.status != "handled"
        assert runner.payloads == []

    def test_a_path_outside_the_root_is_refused_before_routing(
        self, workspace, tmp_path
    ):
        outside = tmp_path / "outside.txt"
        runner = RecordingRunner()

        _run(_executor(workspace, runner), f"copy note.txt to {outside}")

        assert not outside.exists()


# ---------------------------------------------------------------------------
# J -- the other boundary actions are unchanged
# ---------------------------------------------------------------------------


class TestExistingBoundaryActionsUnchanged:
    @pytest.mark.parametrize(
        ("command", "action_type"),
        [
            ("delete note.txt", "file_delete"),
            ("move note.txt to existing", "file_move"),
            ("rename note.txt to renamed.txt", "file_rename"),
            ("create file fresh.txt", "file_create"),
        ],
    )
    def test_it_still_routes_as_before(self, command, action_type, workspace):
        """``delete`` is confirmed before it routes -- that is its existing
        contract, not something this slice changed -- so the callback is
        supplied for every case rather than only that one."""
        runner = RecordingRunner()

        _run(_executor(workspace, runner), command, confirm=lambda *args: True)

        assert [p["action_type"] for p in runner.payloads] == [action_type]

    def test_delete_still_asks_before_it_routes(self, workspace):
        """Pinned so the confirmation above is understood as a contract rather
        than a workaround: without it, nothing is routed and nothing is
        deleted."""
        runner = RecordingRunner()

        result = _run(_executor(workspace, runner), "delete note.txt")

        assert result.status == "needs_confirmation"
        assert runner.payloads == []
        assert (workspace / "note.txt").exists()

    def test_the_routed_set_is_exactly_six(self):
        assert set(BOUNDARY_ROUTED_ACTIONS) == {
            "create_file",
            "create_folder",
            "copy",
            "delete",
            "move",
            "rename",
        }

    def test_read_only_actions_are_still_not_routed(self, workspace):
        """``search`` and ``properties`` mutate nothing, so they have no
        mutation to route."""
        runner = RecordingRunner()
        executor = _executor(workspace, runner)

        _run(executor, "search for note")
        _run(executor, "show properties of note.txt")

        assert runner.payloads == []
        assert "search" not in BOUNDARY_ROUTED_ACTIONS
        assert "properties" not in BOUNDARY_ROUTED_ACTIONS
