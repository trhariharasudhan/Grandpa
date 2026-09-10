"""What a delete actually does now that the file surface is composed.

The composition slice routed six file mutations through ``run_local_action``.
Five of them are LOW or MEDIUM and execute inline, so nothing about them is
surprising. ``file_delete`` is HIGH, and HIGH is the tier that stages for
approval -- which makes it the one action whose user-visible behaviour could
have moved. This file pins where it actually landed.

**Two gates, not one, and the file-domain gate comes first.**
``FileExecutor._delete`` refuses without a confirmation callback *before* it
routes anything. No production entry surface passes one: the shared handler
calls ``.handle(text)`` and so does the voice operator. So a spoken or typed
delete still stops at the file layer with ``needs_confirmation``, reaches no
boundary, and writes no approval record -- exactly as before composition. That
is asserted here, because it is the half a reader is most likely to get wrong.

The boundary gate is reached only once a caller confirms. Then the delete is
classified HIGH, staged, and the file is left alone until somebody approves
with the out-of-band code. That path is characterised end to end below,
including the four ways it can fail to delete.

**Nothing here is new machinery.** The token, the digest binding, the
single-owner claim, the expiry, the emergency stop and the audit record all
predate this slice and are exercised, not re-implemented. The approval store is
redirected to ``tmp_path`` through the existing ``GRANDPA_PC_CONTROL_DB``
environment variable, the same way every other approval suite isolates it; no
test here writes to the real database.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from grandpa import pc_control
from grandpa.composition import build_file_automation


@pytest.fixture(autouse=True)
def isolated_approval_store(tmp_path, monkeypatch):
    """Redirect every store this module can touch into ``tmp_path``.

    The approval database is the one that matters: a HIGH action stages a row,
    and staging it in the developer's real ``pc_control_approvals.db`` would
    leave a pending delete behind on their machine.
    """
    monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(tmp_path / "approvals.db"))
    monkeypatch.setenv(
        "GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "local_actions.jsonl")
    )
    monkeypatch.setenv(
        "GRANDPA_PC_CONTROL_RETENTION_CONFIG", str(tmp_path / "retention.json")
    )
    pc_control.reset_emergency_stop()
    yield
    pc_control.reset_emergency_stop()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """The only root the file layer will look in, for both root sources."""
    import grandpa.file_assistant as file_assistant
    import grandpa.files.executor as file_executor

    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    (root / "note.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(file_executor, "safe_roots", lambda: (root,))
    monkeypatch.setattr(file_assistant, "_safe_roots", lambda: [root])
    return root


def _rows() -> list[sqlite3.Row]:
    """Every approval record, or none.

    A missing table is the strongest form of "nothing was staged": the store is
    created lazily on first use, so an absent one means no code path even
    opened it.
    """
    if not pc_control.get_approval_db_path().exists():
        return []
    with sqlite3.connect(pc_control.get_approval_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute("SELECT * FROM pc_control_approvals").fetchall()
        except sqlite3.OperationalError:
            return []


def _only_row() -> sqlite3.Row:
    rows = _rows()
    assert len(rows) == 1, [dict(row) for row in rows]
    return rows[0]


def _stage_delete(workspace: Path):
    """Confirm the delete at the file layer so it reaches the boundary."""
    return build_file_automation().handle("delete note.txt", confirm=lambda *a: True)


# ---------------------------------------------------------------------------
# The trace, one hop at a time
# ---------------------------------------------------------------------------


class TestTheDeleteReachesTheBoundaryAsHigh:
    def test_the_file_exists_before_anything_runs(self, workspace):
        assert (workspace / "note.txt").exists()

    def test_the_request_arrives_as_file_delete(self, workspace, monkeypatch):
        seen: list[dict] = []
        real = pc_control.run_local_action

        def spy(payload):
            seen.append(dict(payload))
            return real(payload)

        monkeypatch.setattr(pc_control, "run_local_action", spy)

        _stage_delete(workspace)

        assert [p["action_type"] for p in seen] == ["file_delete"]
        assert Path(seen[0]["target"]).resolve() == (workspace / "note.txt").resolve()

    def test_the_risk_is_high(self):
        request = pc_control._coerce_request(
            {"action_type": "file_delete", "target": "x"}
        )

        assert pc_control.classify_risk(request) == "HIGH"

    def test_the_boundary_does_not_delete_it_immediately(self, workspace):
        _stage_delete(workspace)

        assert (workspace / "note.txt").exists()

    def test_the_result_asks_for_confirmation(self, workspace):
        result = _stage_delete(workspace)

        assert result.status == "needs_confirmation"
        assert result.requires_confirmation


# ---------------------------------------------------------------------------
# Approval creation, through the existing store
# ---------------------------------------------------------------------------


class TestApprovalCreation:
    def test_exactly_one_pending_record_is_created(self, workspace):
        _stage_delete(workspace)
        row = _only_row()

        assert row["status"] == "pending"
        assert row["action_type"] == "file_delete"
        assert row["risk_level"] == "HIGH"
        assert row["decision"] == "pending"

    def test_the_record_carries_a_token_and_a_binding(self, workspace):
        """Both predate this slice. Their presence is what makes the pending
        row approvable at all, and neither is re-implemented here."""
        _stage_delete(workspace)
        row = _only_row()

        assert row["approval_token"]
        assert row["action_digest"]

    def test_the_record_is_written_to_the_isolated_store(self, tmp_path):
        assert pc_control.get_approval_db_path() == tmp_path / "approvals.db"

    @pytest.mark.parametrize("origin", ["direct", "voice"])
    def test_the_provenance_of_the_asker_is_recorded(self, origin, workspace):
        build_file_automation(origin=origin).handle(
            "delete note.txt", confirm=lambda *a: True
        )

        assert _only_row()["origin"] == origin

    def test_the_file_is_still_there(self, workspace):
        _stage_delete(workspace)

        assert (workspace / "note.txt").read_text(encoding="utf-8") == "hello"


# ---------------------------------------------------------------------------
# Approval continuation
# ---------------------------------------------------------------------------


class TestApprovalContinuation:
    def test_a_valid_approval_deletes_the_file(self, workspace):
        """The code is read from the store because that is where the operator
        console reads it from; a caller holding only the response cannot."""
        _stage_delete(workspace)
        row = _only_row()

        response = pc_control.approve_local_action(
            row["action_id"], row["approval_token"]
        )

        assert response.ok
        assert response.status == "completed"
        assert not (workspace / "note.txt").exists()

    def test_the_wrong_code_does_not_delete_it(self, workspace):
        _stage_delete(workspace)
        row = _only_row()

        response = pc_control.approve_local_action(row["action_id"], "NOPE")

        assert response.error == "invalid_approval_token"
        assert (workspace / "note.txt").exists()

    def test_an_empty_code_does_not_delete_it(self, workspace):
        """An ``action_id`` alone is not an authorisation."""
        _stage_delete(workspace)
        row = _only_row()

        response = pc_control.approve_local_action(row["action_id"])

        assert response.error == "invalid_approval_token"
        assert (workspace / "note.txt").exists()

    def test_an_expired_approval_does_not_delete_it(self, workspace):
        _stage_delete(workspace)
        row = _only_row()
        with sqlite3.connect(pc_control.get_approval_db_path()) as conn:
            conn.execute(
                "UPDATE pc_control_approvals SET expires_at = ? WHERE action_id = ?",
                (0.0, row["action_id"]),
            )

        response = pc_control.approve_local_action(
            row["action_id"], row["approval_token"]
        )

        assert not response.ok
        assert (workspace / "note.txt").exists()

    def test_an_unknown_action_id_deletes_nothing(self, workspace):
        _stage_delete(workspace)

        response = pc_control.approve_local_action("0" * 32, "ANYTHING")

        assert not response.ok
        assert (workspace / "note.txt").exists()

    def test_the_same_approval_cannot_run_twice(self, workspace):
        """The single-owner claim, exercised rather than re-implemented."""
        _stage_delete(workspace)
        row = _only_row()
        pc_control.approve_local_action(row["action_id"], row["approval_token"])

        second = pc_control.approve_local_action(
            row["action_id"], row["approval_token"]
        )

        assert not second.ok

    def test_a_rejected_delete_never_runs(self, workspace):
        _stage_delete(workspace)
        row = _only_row()

        pc_control.reject_local_action(row["action_id"])

        assert (workspace / "note.txt").exists()
        assert _only_row()["status"] == "rejected"


# ---------------------------------------------------------------------------
# The two gates that must still stop it
# ---------------------------------------------------------------------------


class TestEmergencyStopAndDryRun:
    def test_a_stop_before_the_request_leaves_the_file_alone(self, workspace):
        pc_control.emergency_stop()

        _stage_delete(workspace)

        assert (workspace / "note.txt").exists()

    def test_a_stop_after_staging_prevents_the_approved_delete(self, workspace):
        """Staging is ordered before the stop gate, so a row can exist while a
        stop is in force. What must not happen is the deletion."""
        _stage_delete(workspace)
        row = _only_row()
        pc_control.emergency_stop()

        response = pc_control.approve_local_action(
            row["action_id"], row["approval_token"]
        )

        assert not response.ok
        assert (workspace / "note.txt").exists()

    def test_a_dry_run_deletes_nothing_and_stages_nothing(self, workspace):
        result = build_file_automation(dry_run=True).handle(
            "delete note.txt", confirm=lambda *a: True
        )

        assert result.status == "handled"
        assert (workspace / "note.txt").exists()
        assert _rows() == []


# ---------------------------------------------------------------------------
# What the user actually sees, on the four production surfaces
# ---------------------------------------------------------------------------


class TestTheUserVisibleSurface:
    def test_the_shared_handler_asks_before_it_routes(self, workspace, tmp_path):
        """The correction worth stating plainly: no production surface passes a
        confirmation callback, so the file-domain gate answers first and the
        boundary is never reached. Composition did not change what a delete
        does here."""
        from grandpa.file_assistant import FileAssistantStore, handle_file_command

        result = handle_file_command(
            "delete note.txt", store=FileAssistantStore(tmp_path / "s.db")
        )

        assert result.status == "needs_confirmation"
        assert result.permission == "requires_confirmation"
        assert (workspace / "note.txt").exists()
        assert _rows() == []

    def test_no_production_surface_passes_a_confirmation_callback(self):
        """If one ever does, the delete behaviour above changes, and this is
        the test that will say so.

        Scoped to the ``handle`` calls rather than the whole file, so unrelated
        code elsewhere in these modules cannot trip it."""
        root = Path(__file__).resolve().parents[1] / "src" / "grandpa"
        for module in ("file_assistant.py", "voice/operator.py"):
            tree = ast.parse((root / module).read_text(encoding="utf-8"))
            confirmed = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "handle"
                and any(keyword.arg == "confirm" for keyword in node.keywords)
            ]

            assert confirmed == [], module

    def test_the_voice_operator_asks_too(self, workspace, monkeypatch):
        from grandpa.voice.operator import process_voice_operator_turn

        monkeypatch.setattr(
            "grandpa.planner.routing.handle_executive_goal", lambda *a, **k: None
        )
        result = process_voice_operator_turn("delete note.txt")

        assert result.requires_confirmation
        assert (workspace / "note.txt").exists()
        assert _rows() == []


# ---------------------------------------------------------------------------
# No second implementation of any of this
# ---------------------------------------------------------------------------


class TestNoSecondApprovalImplementation:
    def test_the_gates_still_live_only_in_pc_control(self):
        import inspect

        approve = inspect.getsource(pc_control._approve_local_action_impl)

        assert "compare_digest" in approve
        assert "if not _mark_pending_decision" in approve
        assert "_EMERGENCY_STOP_ACTIVE" in approve

    def test_neither_composition_nor_the_file_layer_stages_anything(self):
        root = Path(__file__).resolve().parents[1] / "src" / "grandpa"
        for path in list((root / "composition").glob("*.py")) + list(
            (root / "files").rglob("*.py")
        ):
            source = path.read_text(encoding="utf-8")
            for forbidden in (
                "_create_pending",
                "approve_local_action",
                "_mark_pending_decision",
                "compare_digest",
                "approval_token",
            ):
                assert forbidden not in source, f"{path.name}: {forbidden}"
