"""File operations must be judged by the filesystem, not by their own message.

``FileControlService`` reports ``completed`` whenever its call returned without
raising (``desktop/control/files.py``). That is not the same as the file being
there: a copy onto a full disk, a move whose destination was replaced, a delete
that silently left the tree behind all report success. These are the five
highest-consequence actions in the system -- ``file_delete`` is HIGH risk, the
other four MEDIUM or LOW -- and they were the ones with no read-back at all,
despite ``Path.exists()`` being about as reliable as evidence gets.

The paths come from the response evidence, not from the request. That is the
only correct source: ``file_rename`` derives its destination inside the service
from ``args["new_name"]``, so the request alone does not know where the file
went, and every path in the evidence has already been through
``resolve_path``. Missing or unreadable evidence is ``unknown``, never
``failed`` -- absence of evidence is not evidence of failure, which is the rule
the rest of this module already runs on.

Nothing here writes outside its own ``tmp_path``: the ``confined_filesystem``
fixture makes every mutating primitive the file service uses raise if a path
escapes the test's temporary directory.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from grandpa import pc_control
from grandpa.desktop.control import verification as verify_mod
from grandpa.desktop.control.verification import verify_action
from grandpa.pc_control import LocalActionRequest, LocalActionResponse

FILE_ACTIONS = ("file_create", "file_delete", "file_move", "file_copy", "file_rename")


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


@pytest.fixture
def confined_filesystem(tmp_path, monkeypatch):
    """Make it impossible for a test to touch anything outside ``tmp_path``.

    The file service mutates the disk through a small set of primitives. Each
    is wrapped so a path outside the test's own directory raises instead of
    being written, moved or deleted -- a test that loses its seam fails loudly
    rather than removing something real.
    """
    root = tmp_path.resolve()

    def _check(*paths: Any) -> None:
        for raw in paths:
            resolved = Path(str(raw)).expanduser().resolve(strict=False)
            if root not in resolved.parents and resolved != root:
                raise AssertionError(
                    f"filesystem access escaped the test directory: {resolved}"
                )

    real = {
        "move": shutil.move,
        "copy2": shutil.copy2,
        "copytree": shutil.copytree,
        "rmtree": shutil.rmtree,
        "unlink": Path.unlink,
        "rename": Path.rename,
        "mkdir": Path.mkdir,
        "write_text": Path.write_text,
    }

    monkeypatch.setattr(
        shutil, "move", lambda s, d, *a, **k: (_check(s, d), real["move"](s, d))[1]
    )
    monkeypatch.setattr(
        shutil, "copy2", lambda s, d, *a, **k: (_check(s, d), real["copy2"](s, d))[1]
    )
    monkeypatch.setattr(
        shutil,
        "copytree",
        lambda s, d, *a, **k: (_check(s, d), real["copytree"](s, d))[1],
    )
    monkeypatch.setattr(
        shutil, "rmtree", lambda p, *a, **k: (_check(p), real["rmtree"](p))[1]
    )
    monkeypatch.setattr(
        Path, "unlink", lambda self, *a, **k: (_check(self), real["unlink"](self))[1]
    )
    monkeypatch.setattr(
        Path,
        "rename",
        lambda self, t, *a, **k: (_check(self, t), real["rename"](self, t))[1],
    )
    monkeypatch.setattr(
        Path,
        "mkdir",
        lambda self, *a, **k: (_check(self), real["mkdir"](self, *a, **k))[1],
    )
    monkeypatch.setattr(
        Path,
        "write_text",
        lambda self, d, *a, **k: (_check(self), real["write_text"](self, d, *a, **k))[
            1
        ],
    )
    return root


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _request(action: str, target: str = "", **args: Any) -> LocalActionRequest:
    return LocalActionRequest(action_type=action, target=target, args=dict(args))


def _response(evidence: dict[str, Any] | None) -> LocalActionResponse:
    return LocalActionResponse(
        ok=True,
        action_id=None,
        status="completed",
        message="Done.",
        approval_required=False,
        risk_level="LOW",
        evidence={} if evidence is None else dict(evidence),
    )


def _verify(action: str, evidence: dict[str, Any] | None):
    return verify_action(_request(action), _response(evidence))


# ---------------------------------------------------------------------------
# Positive states
# ---------------------------------------------------------------------------


class TestVerifiedStates:
    def test_create_is_verified_when_the_file_is_there(self, tmp_path):
        made = tmp_path / "notes.txt"
        made.write_text("hi", encoding="utf-8")

        outcome = _verify("file_create", {"path": str(made), "kind": "file"})

        assert outcome.status == "verified"

    def test_create_is_verified_for_a_folder(self, tmp_path):
        made = tmp_path / "folder"
        made.mkdir()

        outcome = _verify("file_create", {"path": str(made), "kind": "folder"})

        assert outcome.status == "verified"

    def test_delete_is_verified_when_the_path_is_gone(self, tmp_path):
        gone = tmp_path / "gone.txt"

        outcome = _verify("file_delete", {"path": str(gone)})

        assert outcome.status == "verified"

    def test_move_is_verified_when_source_left_and_destination_arrived(self, tmp_path):
        source = tmp_path / "a.txt"
        destination = tmp_path / "b.txt"
        destination.write_text("x", encoding="utf-8")

        outcome = _verify("file_move", {"from": str(source), "to": str(destination)})

        assert outcome.status == "verified"

    def test_rename_is_verified_the_same_way_as_move(self, tmp_path):
        old = tmp_path / "old.txt"
        new = tmp_path / "new.txt"
        new.write_text("x", encoding="utf-8")

        outcome = _verify("file_rename", {"from": str(old), "to": str(new)})

        assert outcome.status == "verified"

    def test_copy_is_verified_when_both_paths_exist(self, tmp_path):
        source = tmp_path / "a.txt"
        destination = tmp_path / "b.txt"
        source.write_text("x", encoding="utf-8")
        destination.write_text("x", encoding="utf-8")

        outcome = _verify("file_copy", {"from": str(source), "to": str(destination)})

        assert outcome.status == "verified"


# ---------------------------------------------------------------------------
# Negative states -- a successful call with the wrong filesystem is a failure
# ---------------------------------------------------------------------------


class TestFailedStates:
    def test_create_that_produced_nothing_is_failed(self, tmp_path):
        outcome = _verify("file_create", {"path": str(tmp_path / "missing.txt")})

        assert outcome.status == "failed"
        assert "missing.txt" in outcome.detail or outcome.expected

    def test_delete_that_left_the_file_is_failed(self, tmp_path):
        still_there = tmp_path / "a.txt"
        still_there.write_text("x", encoding="utf-8")

        outcome = _verify("file_delete", {"path": str(still_there)})

        assert outcome.status == "failed"

    def test_move_that_left_the_source_behind_is_failed(self, tmp_path):
        source = tmp_path / "a.txt"
        destination = tmp_path / "b.txt"
        source.write_text("x", encoding="utf-8")
        destination.write_text("x", encoding="utf-8")

        outcome = _verify("file_move", {"from": str(source), "to": str(destination)})

        assert outcome.status == "failed"

    def test_move_whose_destination_never_arrived_is_failed(self, tmp_path):
        outcome = _verify(
            "file_move",
            {"from": str(tmp_path / "a.txt"), "to": str(tmp_path / "b.txt")},
        )

        assert outcome.status == "failed"

    def test_rename_that_did_not_happen_is_failed(self, tmp_path):
        old = tmp_path / "old.txt"
        old.write_text("x", encoding="utf-8")

        outcome = _verify(
            "file_rename", {"from": str(old), "to": str(tmp_path / "new.txt")}
        )

        assert outcome.status == "failed"

    def test_copy_that_produced_no_destination_is_failed(self, tmp_path):
        source = tmp_path / "a.txt"
        source.write_text("x", encoding="utf-8")

        outcome = _verify(
            "file_copy", {"from": str(source), "to": str(tmp_path / "b.txt")}
        )

        assert outcome.status == "failed"

    def test_copy_that_lost_the_source_is_failed(self, tmp_path):
        """A copy must not consume what it copied."""
        destination = tmp_path / "b.txt"
        destination.write_text("x", encoding="utf-8")

        outcome = _verify(
            "file_copy", {"from": str(tmp_path / "a.txt"), "to": str(destination)}
        )

        assert outcome.status == "failed"

    def test_the_failure_detail_names_what_was_wrong(self, tmp_path):
        still_there = tmp_path / "a.txt"
        still_there.write_text("x", encoding="utf-8")

        outcome = _verify("file_delete", {"path": str(still_there)})

        assert outcome.detail
        assert "a.txt" in outcome.detail


# ---------------------------------------------------------------------------
# Unknown -- unreadable or absent evidence is never a failure
# ---------------------------------------------------------------------------


class TestUnknownStates:
    @pytest.mark.parametrize("action", FILE_ACTIONS)
    def test_no_evidence_at_all_is_unknown(self, action):
        assert _verify(action, None).status == "unknown"

    @pytest.mark.parametrize("action", ["file_create", "file_delete"])
    def test_an_empty_path_is_unknown(self, action):
        assert _verify(action, {"path": ""}).status == "unknown"

    @pytest.mark.parametrize("action", ["file_move", "file_copy", "file_rename"])
    def test_a_missing_destination_is_unknown(self, action, tmp_path):
        assert _verify(action, {"from": str(tmp_path / "a.txt")}).status == "unknown"

    @pytest.mark.parametrize("action", ["file_move", "file_copy", "file_rename"])
    def test_a_missing_source_is_unknown(self, action, tmp_path):
        assert _verify(action, {"to": str(tmp_path / "b.txt")}).status == "unknown"

    @pytest.mark.parametrize("action", FILE_ACTIONS)
    def test_an_unreadable_filesystem_is_unknown(self, action, monkeypatch, tmp_path):
        """A reader that cannot answer must not be read as "it went wrong"."""
        monkeypatch.setattr(verify_mod, "read_path_exists", lambda path: None)

        outcome = _verify(
            action,
            {
                "path": str(tmp_path / "a.txt"),
                "from": str(tmp_path / "a.txt"),
                "to": str(tmp_path / "b.txt"),
            },
        )

        assert outcome.status == "unknown"

    @pytest.mark.parametrize("action", FILE_ACTIONS)
    def test_a_raising_reader_does_not_propagate(self, action, monkeypatch, tmp_path):
        def boom(path):
            raise OSError("device not ready")

        monkeypatch.setattr(verify_mod, "read_path_exists", boom)

        outcome = _verify(
            action,
            {
                "path": str(tmp_path / "a.txt"),
                "from": str(tmp_path / "a.txt"),
                "to": str(tmp_path / "b.txt"),
            },
        )

        assert outcome.status == "unknown"

    def test_an_empty_path_cannot_be_answered(self):
        assert verify_mod.read_path_exists("") is None

    @pytest.mark.parametrize(
        "failure", [OSError("device not ready"), ValueError("bad")]
    )
    def test_a_filesystem_that_raises_is_reported_unknown(self, failure, monkeypatch):
        """Whether a given bad path raises is platform-specific; that a raise
        becomes ``unknown`` rather than propagating is the contract."""

        def boom(self):
            raise failure

        monkeypatch.setattr(Path, "exists", boom)

        assert verify_mod.read_path_exists("anything") is None


# ---------------------------------------------------------------------------
# Through run_local_action
# ---------------------------------------------------------------------------


class TestThroughTheBoundary:
    def _audit_to(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
        )

    def test_a_real_create_is_verified_end_to_end(
        self, monkeypatch, tmp_path, confined_filesystem
    ):
        self._audit_to(monkeypatch, tmp_path)
        target = tmp_path / "made.txt"

        response = pc_control.run_local_action(
            {
                "action_type": "file_create",
                "target": str(target),
                "args": {"kind": "file", "content": "hello"},
            }
        )

        assert response.ok is True
        assert response.evidence["verification"]["status"] == "verified"
        assert target.read_text(encoding="utf-8") == "hello"

    def test_a_real_move_is_verified_end_to_end(
        self, monkeypatch, tmp_path, confined_filesystem
    ):
        self._audit_to(monkeypatch, tmp_path)
        source = tmp_path / "a.txt"
        source.write_text("x", encoding="utf-8")
        destination = tmp_path / "sub" / "b.txt"

        response = pc_control.run_local_action(
            {
                "action_type": "file_move",
                "target": str(source),
                "args": {"destination": str(destination)},
            }
        )

        assert response.evidence["verification"]["status"] == "verified"
        assert destination.exists() and not source.exists()

    def test_a_real_rename_is_verified_through_new_name(
        self, monkeypatch, tmp_path, confined_filesystem
    ):
        """The destination exists only in the evidence, never in the request."""
        self._audit_to(monkeypatch, tmp_path)
        source = tmp_path / "old.txt"
        source.write_text("x", encoding="utf-8")

        response = pc_control.run_local_action(
            {
                "action_type": "file_rename",
                "target": str(source),
                "args": {"new_name": "new.txt"},
            }
        )

        assert response.evidence["verification"]["status"] == "verified"
        assert (tmp_path / "new.txt").exists()

    def test_a_lying_executor_is_downgraded(self, monkeypatch, tmp_path):
        """The whole point: a successful message with no file is a failure."""
        self._audit_to(monkeypatch, tmp_path)
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="Created file.",
                approval_required=False,
                risk_level=risk,
                evidence={"path": str(tmp_path / "never_made.txt")},
            ),
        )

        response = pc_control.run_local_action(
            {"action_type": "file_create", "target": str(tmp_path / "never_made.txt")}
        )

        assert response.ok is False
        assert response.status == "failed"
        assert response.error == "verification_failed"

    def test_an_unverifiable_result_is_not_downgraded(self, monkeypatch, tmp_path):
        self._audit_to(monkeypatch, tmp_path)
        monkeypatch.setattr(verify_mod, "read_path_exists", lambda path: None)
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="Created file.",
                approval_required=False,
                risk_level=risk,
                evidence={"path": str(tmp_path / "x.txt")},
            ),
        )

        response = pc_control.run_local_action(
            {"action_type": "file_create", "target": str(tmp_path / "x.txt")}
        )

        assert response.ok is True
        assert response.evidence["verification"]["status"] == "unknown"

    def test_the_verification_reaches_the_audit_record(
        self, monkeypatch, tmp_path, confined_filesystem
    ):
        import json

        log = tmp_path / "audit.log"
        monkeypatch.setattr(pc_control, "get_audit_log_path", lambda: log)

        pc_control.run_local_action(
            {
                "action_type": "file_create",
                "target": str(tmp_path / "made.txt"),
                "origin": "voice",
            }
        )

        record = json.loads(
            [line for line in log.read_text(encoding="utf-8").splitlines() if line][-1]
        )
        assert record["verification"] == "verified"
        assert record["origin"] == "voice"

    def test_the_services_own_evidence_survives(
        self, monkeypatch, tmp_path, confined_filesystem
    ):
        self._audit_to(monkeypatch, tmp_path)

        response = pc_control.run_local_action(
            {"action_type": "file_create", "target": str(tmp_path / "made.txt")}
        )

        assert response.evidence["path"] == str(tmp_path / "made.txt")
        assert response.evidence["kind"] == "file"


# ---------------------------------------------------------------------------
# Policy is untouched, and no read-back happens where it must not
# ---------------------------------------------------------------------------


class ExistenceReader:
    """Counts filesystem reads so a test can prove none happened."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, path: str) -> bool | None:
        self.calls.append(path)
        return True


class TestPolicyPreserved:
    def test_a_dry_run_reads_no_files(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
        )
        reader = ExistenceReader()
        monkeypatch.setattr(verify_mod, "read_path_exists", reader)

        response = pc_control.run_local_action(
            {
                "action_type": "file_delete",
                "target": str(tmp_path / "a.txt"),
                "dry_run": True,
            }
        )

        assert response.status == "dry_run"
        assert reader.calls == [], "a dry run touched the filesystem"
        assert "verification" not in response.evidence

    def test_a_blocked_action_reads_no_files(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
        )
        reader = ExistenceReader()
        monkeypatch.setattr(verify_mod, "read_path_exists", reader)

        response = pc_control.run_local_action(
            {"action_type": "file_permanent_delete", "target": str(tmp_path / "a.txt")}
        )

        assert response.status == "blocked"
        assert reader.calls == []

    def test_a_protected_path_is_still_blocked_and_unread(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
        )
        monkeypatch.setattr(pc_control, "_is_protected_path", lambda path: True)
        reader = ExistenceReader()
        monkeypatch.setattr(verify_mod, "read_path_exists", reader)

        response = pc_control.run_local_action(
            {"action_type": "file_delete", "target": str(tmp_path / "a.txt")}
        )

        assert response.status == "blocked"
        assert response.error == "protected_path"
        assert reader.calls == []

    def test_an_approval_gated_action_reads_no_files(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
        )
        reader = ExistenceReader()
        monkeypatch.setattr(verify_mod, "read_path_exists", reader)

        response = pc_control.run_local_action(
            {
                "action_type": "file_delete",
                "target": str(tmp_path / "a.txt"),
                "require_approval": True,
            }
        )

        assert response.status == "approval_required"
        assert reader.calls == []

    def test_emergency_stop_still_stops_a_file_action(self, monkeypatch, tmp_path):
        """``file_move`` is MEDIUM, so it reaches the emergency-stop gate.

        A HIGH-risk action never does: ``pc_control.py:322`` stages it for
        approval first, which is a stricter outcome, not a weaker one.
        """
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
        )
        monkeypatch.setattr(pc_control, "_EMERGENCY_STOP_ACTIVE", True)
        reader = ExistenceReader()
        monkeypatch.setattr(verify_mod, "read_path_exists", reader)

        response = pc_control.run_local_action(
            {
                "action_type": "file_move",
                "target": str(tmp_path / "a.txt"),
                "args": {"destination": str(tmp_path / "b.txt")},
            }
        )

        assert response.error == "emergency_stop_active"
        assert reader.calls == []

    def test_a_delete_is_approval_gated_before_anything_is_read(
        self, monkeypatch, tmp_path
    ):
        """HIGH risk stages for approval on its own, with no flag needed."""
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
        )
        reader = ExistenceReader()
        monkeypatch.setattr(verify_mod, "read_path_exists", reader)

        response = pc_control.run_local_action(
            {"action_type": "file_delete", "target": str(tmp_path / "a.txt")}
        )

        assert response.status == "approval_required"
        assert response.approval_required is True
        assert reader.calls == []

    @pytest.mark.parametrize(
        ("action", "risk"),
        [
            ("file_create", "LOW"),
            ("file_move", "MEDIUM"),
            ("file_copy", "MEDIUM"),
            ("file_rename", "MEDIUM"),
            ("file_delete", "HIGH"),
        ],
    )
    def test_risk_tiers_are_unchanged(self, action, risk):
        assert pc_control.classify_risk(_request(action, "x")) == risk

    def test_permanent_delete_is_still_blocked(self):
        assert "file_permanent_delete" in pc_control.BLOCKED_ACTIONS


# ---------------------------------------------------------------------------
# The spoken surface
# ---------------------------------------------------------------------------


class TestSpokenVerification:
    def test_a_failed_file_verification_is_audible(self):
        from grandpa.voice.operator import spoken_text_for_verification

        response = _response(
            {"verification": {"status": "failed", "detail": "a.txt is still there"}}
        )

        spoken = spoken_text_for_verification(response, "Deleted item.")

        assert not spoken.startswith("Deleted item")
        assert "a.txt is still there" in spoken

    def test_an_unknown_file_verification_is_hedged(self):
        from grandpa.voice.operator import spoken_text_for_verification

        response = _response({"verification": {"status": "unknown", "detail": ""}})

        spoken = spoken_text_for_verification(response, "Deleted item.")

        assert "could not confirm" in spoken

    def test_a_verified_file_action_keeps_its_plain_message(self):
        from grandpa.voice.operator import spoken_text_for_verification

        response = _response({"verification": {"status": "verified", "detail": "d"}})

        assert (
            spoken_text_for_verification(response, "Deleted item.") == "Deleted item."
        )


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_exactly_the_five_file_actions_became_verifiable(self):
        from grandpa.desktop.control.verification import verifiable_actions

        added = {a for a in verifiable_actions() if a.startswith("file_")}

        assert added == set(FILE_ACTIONS)

    def test_no_new_action_types_were_added(self):
        for action in FILE_ACTIONS:
            assert (
                action in pc_control.LOW_RISK_ACTIONS
                or action in pc_control.MEDIUM_RISK_ACTIONS
                or action in pc_control.HIGH_RISK_ACTIONS
            )

    def test_the_verification_vocabulary_is_unchanged(self, tmp_path):
        statuses = {
            _verify("file_create", {"path": str(tmp_path)}).status,
            _verify("file_create", {"path": str(tmp_path / "no.txt")}).status,
            _verify("file_create", None).status,
        }

        assert statuses == {"verified", "failed", "unknown"}

    def test_the_previously_verifiable_actions_still_are(self):
        from grandpa.desktop.control.verification import verifiable_actions

        actions = set(verifiable_actions())

        assert {
            "volume_set",
            "open_app",
            "maximize_window",
            "clipboard_write",
        } <= actions
