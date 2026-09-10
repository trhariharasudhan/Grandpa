"""An approval authorises one action, not one name.

The approval record stored the raw target and nothing about what that target
resolved to, and the approve path re-derived everything from scratch. So a
staged launch could be approved and then execute a different program:

    stage    "bash"  ->  git-bash.exe        (shown, staged, approved by a person)
    inventory changes
    approve  correct code  ->  executed notepad.exe

The token was never the problem. ``compare_digest`` proves *who* may approve;
nothing proved *what* was approved. Those are two separate questions and this
file holds the second one.

The binding is a SHA-256 over the security-relevant identity of the action --
its type, target, arguments, and the executable and launch path it resolved to
at staging. It deliberately excludes who asked, when, and whether approval was
requested: the digest says what would run, not who wanted it or when.

A limit worth stating plainly: for a ``.lnk`` row the bound launch path is the
shortcut, because that is the only identity the inventory exposes. If the
shortcut's own target is repointed underneath, this cannot see it. That is the
documented shortcut limitation, unchanged here.

Nothing launches: the launcher is replaced by a recorder that records instead
of starting anything, and a test fails if a rejected action reaches it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa import pc_control
from grandpa.apps.inventory import AppInventoryRecord
from grandpa.apps.resolver import normalize_app_name, resolve_app
from grandpa.pc_control import LocalActionRequest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(tmp_path / "approvals.db"))
    monkeypatch.setattr(
        pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
    )
    pc_control.reset_emergency_stop()
    yield
    pc_control.reset_emergency_stop()


class Inventory:
    """A synthetic inventory whose contents can change between calls."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.rows: list[AppInventoryRecord] = []
        self.launched: list[str] = []
        self.resolve_calls: list[str] = []

    def set(self, *rows: tuple[str, str, tuple[str, ...]]) -> None:
        built = []
        for display, filename, aliases in rows:
            target = self.directory / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
            built.append(
                AppInventoryRecord(
                    display,
                    normalize_app_name(display),
                    str(target),
                    "test",
                    aliases,
                    1.0,
                )
            )
        self.rows = built

    def find_app(self, name: str, **_kwargs):
        self.resolve_calls.append(name)
        return resolve_app(name, self.rows)

    def launch(self, record) -> str:
        self.launched.append(record.path)
        return f"Opening {record.display_name}."


GIT_BASH = ("Git", "git-bash.exe", ("bash", "git", "git bash"))
NOTEPAD_AS_BASH = ("Bash Notes", "notepad.exe", ("bash", "bash notes"))
GIT_BASH_MOVED = ("Git", "elsewhere/git-bash.exe", ("bash", "git", "git bash"))


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    store = Inventory(tmp_path / "apps")
    store.set(GIT_BASH)
    monkeypatch.setattr("grandpa.apps.inventory.find_app", store.find_app)
    monkeypatch.setattr("grandpa.apps.inventory.launch_inventory_app", store.launch)
    return store


def _stage(target: str = "bash", **extra) -> tuple[str, str]:
    """Stage an approval and return (action_id, approval code)."""
    response = pc_control.run_local_action(
        {
            "action_type": "open_app",
            "target": target,
            "require_approval": True,
            **extra,
        }
    )
    assert response.status == "approval_required", response.status
    action_id = response.action_id or ""
    record = pc_control._load_pending_record(action_id)
    assert record is not None
    return action_id, record.approval_token


def _request(action_type: str = "open_app", target: str = "bash", **extra):
    return LocalActionRequest(action_type=action_type, target=target, **extra)


# ---------------------------------------------------------------------------
# A, L -- the binding holds, and the proven vulnerability is closed
# ---------------------------------------------------------------------------


class TestTheApprovedActionIsTheExecutedAction:
    def test_an_unchanged_identity_approves_and_runs(self, isolated, inventory):
        action_id, code = _stage()

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is True
        assert [Path(p).name for p in inventory.launched] == ["git-bash.exe"]

    def test_a_changed_executable_is_refused(self, isolated, inventory):
        """The regression. Staged as Git Bash, approved after the inventory
        started pointing the same word at Notepad."""
        action_id, code = _stage()
        inventory.set(NOTEPAD_AS_BASH)

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert approved.error == "approved_action_changed"
        assert inventory.launched == [], "a rejected action reached the launcher"

    def test_a_changed_launch_path_is_refused(self, isolated, inventory):
        """Same executable name, different location on disk."""
        action_id, code = _stage()
        inventory.set(GIT_BASH_MOVED)

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert approved.error == "approved_action_changed"
        assert inventory.launched == []

    def test_a_target_that_stops_resolving_is_refused(self, isolated, inventory):
        action_id, code = _stage()
        inventory.set()

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert approved.error == "approved_action_changed"
        assert inventory.launched == []

    def test_the_refusal_is_recorded_against_the_action(self, isolated, inventory):
        action_id, code = _stage()
        inventory.set(NOTEPAD_AS_BASH)

        pc_control.approve_local_action(action_id, code)

        record = next(
            r for r in pc_control.list_approval_records() if r["action_id"] == action_id
        )
        assert record["status"] != "completed"


# ---------------------------------------------------------------------------
# D, E, F, G, H -- what the digest binds
# ---------------------------------------------------------------------------


class TestWhatTheDigestBinds:
    def test_dictionary_ordering_does_not_change_it(self):
        """Canonicalisation is by sorted keys, so equal arguments written in a
        different order are the same action."""
        first = pc_control._action_digest(
            _request(args={"a": 1, "b": 2}), "git-bash.exe", "C:/x/git-bash.exe"
        )
        second = pc_control._action_digest(
            _request(args={"b": 2, "a": 1}), "git-bash.exe", "C:/x/git-bash.exe"
        )

        assert first == second

    def test_it_is_deterministic_across_calls(self):
        request = _request(args={"new_instance": True})
        digests = {
            pc_control._action_digest(request, "git-bash.exe", "C:/x/git-bash.exe")
            for _ in range(5)
        }

        assert len(digests) == 1

    @pytest.mark.parametrize(
        ("field", "changed"),
        [
            ("action_type", {"action_type": "detect_app"}),
            ("target", {"target": "chrome"}),
            ("args", {"args": {"new_instance": True}}),
        ],
    )
    def test_changing_a_request_field_changes_it(self, field, changed):
        base = pc_control._action_digest(
            _request(args={}), "git-bash.exe", "C:/x/git-bash.exe"
        )
        other = pc_control._action_digest(
            _request(**changed), "git-bash.exe", "C:/x/git-bash.exe"
        )

        assert base != other, field

    @pytest.mark.parametrize(
        ("executable", "launch_path"),
        [
            ("notepad.exe", "C:/x/git-bash.exe"),
            ("git-bash.exe", "C:/elsewhere/git-bash.exe"),
        ],
    )
    def test_changing_the_resolved_identity_changes_it(self, executable, launch_path):
        base = pc_control._action_digest(
            _request(), "git-bash.exe", "C:/x/git-bash.exe"
        )

        assert base != pc_control._action_digest(_request(), executable, launch_path)

    def test_it_ignores_who_asked_and_whether_approval_was_requested(self):
        """The digest says what would run, not who wanted it or when."""
        plain = pc_control._action_digest(
            _request(), "git-bash.exe", "C:/x/git-bash.exe"
        )
        decorated = pc_control._action_digest(
            _request(origin="voice", require_approval=True, dry_run=True),
            "git-bash.exe",
            "C:/x/git-bash.exe",
        )

        assert plain == decorated

    def test_it_is_a_sha256_hex_digest(self):
        digest = pc_control._action_digest(_request(), "", "")

        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")


class TestStoredRecordTampering:
    """The digest is recomputed from the stored row, so editing the row is
    detected even when the inventory has not moved."""

    @pytest.mark.parametrize(
        ("column", "value"),
        [("action_type", "detect_app"), ("target", "chrome"), ("args_json", '{"x":1}')],
    )
    def test_editing_the_persisted_action_is_refused(
        self, isolated, inventory, column, value
    ):
        action_id, code = _stage()
        with pc_control._connect_approval_db() as conn:
            conn.execute(
                f"UPDATE pc_control_approvals SET {column} = ? WHERE action_id = ?",
                (value, action_id),
            )

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert inventory.launched == []


# ---------------------------------------------------------------------------
# I, J, K -- legacy rows, token independence, unchanged mechanics
# ---------------------------------------------------------------------------


class TestLegacyRows:
    """A row written before the column existed carries no binding.

    Missing is not the same as valid. Such a row is refused rather than given a
    freshly computed digest from whatever the inventory says now -- that would
    manufacture the very authorisation the binding exists to check. Pending
    rows live 300 seconds, so the practical population is empty; existing
    expiry clears them.
    """

    def test_a_row_without_a_binding_is_refused(self, isolated, inventory):
        action_id, code = _stage()
        with pc_control._connect_approval_db() as conn:
            conn.execute(
                "UPDATE pc_control_approvals SET action_digest = '' "
                "WHERE action_id = ?",
                (action_id,),
            )

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert approved.error == "approval_binding_missing"
        assert inventory.launched == []

    def test_it_is_not_silently_rebound(self, isolated, inventory):
        action_id, code = _stage()
        with pc_control._connect_approval_db() as conn:
            conn.execute(
                "UPDATE pc_control_approvals SET action_digest = '' "
                "WHERE action_id = ?",
                (action_id,),
            )
        pc_control.approve_local_action(action_id, code)

        with pc_control._connect_approval_db() as conn:
            stored = conn.execute(
                "SELECT action_digest FROM pc_control_approvals WHERE action_id = ?",
                (action_id,),
            ).fetchone()

        assert str(stored["action_digest"]) == ""

    def test_the_migration_is_idempotent(self, isolated):
        for _ in range(3):
            with pc_control._connect_approval_db() as conn:
                columns = [
                    str(row["name"])
                    for row in conn.execute("PRAGMA table_info(pc_control_approvals)")
                ]

        assert columns.count("action_digest") == 1


class TestTokenAndBindingAreSeparateChecks:
    def test_a_wrong_token_still_fails_with_a_matching_binding(
        self, isolated, inventory
    ):
        action_id, _code = _stage()

        approved = pc_control.approve_local_action(action_id, "DEADBEEF")

        assert approved.ok is False
        assert approved.error == "invalid_approval_token"
        assert inventory.launched == []

    def test_a_correct_token_fails_with_a_mismatched_binding(self, isolated, inventory):
        action_id, code = _stage()
        inventory.set(NOTEPAD_AS_BASH)

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert approved.error == "approved_action_changed"

    def test_a_wrong_token_does_not_consume_the_action(self, isolated, inventory):
        action_id, code = _stage()
        pc_control.approve_local_action(action_id, "DEADBEEF")

        assert pc_control.approve_local_action(action_id, code).ok is True


class TestExistingMechanicsAreUnchanged:
    def test_expiry_still_refuses(self, isolated, inventory, monkeypatch):
        action_id, code = _stage()
        monkeypatch.setattr(pc_control.time, "time", lambda: 1e12)

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert approved.error in {"approval_expired", "already_expired"}
        assert inventory.launched == []

    def test_an_emergency_stop_still_cancels(self, isolated, inventory):
        action_id, code = _stage()
        pc_control.emergency_stop()

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert inventory.launched == []

    def test_rejection_still_works(self, isolated, inventory):
        action_id, _code = _stage()

        pc_control.reject_local_action(action_id)

        assert inventory.launched == []

    def test_an_approved_action_cannot_be_approved_twice(self, isolated, inventory):
        action_id, code = _stage()
        assert pc_control.approve_local_action(action_id, code).ok is True

        second = pc_control.approve_local_action(action_id, code)

        assert second.ok is False
        assert len(inventory.launched) == 1


# ---------------------------------------------------------------------------
# Resolution is not repeated needlessly, and the direct path is untouched
# ---------------------------------------------------------------------------


class TestResolutionBudget:
    def test_execution_reuses_the_identity_approval_checked(self, isolated, inventory):
        """Approval resolves to compare; execution must consume that result
        rather than asking again and racing the answer."""
        action_id, code = _stage()
        inventory.resolve_calls.clear()

        pc_control.approve_local_action(action_id, code)

        assert len(inventory.resolve_calls) == 1, inventory.resolve_calls

    def test_the_direct_path_still_launches_without_approval(self, isolated, inventory):
        response = pc_control.run_local_action(
            {"action_type": "open_app", "target": "chrome"}
        )

        assert response.status in {"completed", "failed", "unsupported", "blocked"}
        assert pc_control.classify_risk(_request(target="chrome")) == "LOW"

    def test_an_ordinary_direct_launch_is_not_staged(self, isolated, inventory):
        inventory.set(("Google Chrome", "chrome.exe", ("chrome", "google chrome")))

        response = pc_control.run_local_action(
            {"action_type": "open_app", "target": "chrome"}
        )

        assert response.status != "approval_required"


class TestScope:
    def test_the_frozen_request_contract_is_unchanged(self):
        from dataclasses import fields

        assert [f.name for f in fields(LocalActionRequest)] == [
            "action_type",
            "target",
            "args",
            "require_approval",
            "dry_run",
            "origin",
        ]

    def test_the_risk_tables_are_unchanged(self):
        from grandpa.apps.safety import BLOCKED_EXECUTABLE_NAMES

        assert len(pc_control.SENSITIVE_APP_RISK) == 21
        assert dict(pc_control.SENSITIVE_EXECUTABLE_RISK) == {"git-bash.exe": "MEDIUM"}
        assert len(BLOCKED_EXECUTABLE_NAMES) == 5

    def test_origin_survives_reload(self, isolated, inventory):
        """This recorded a defect when the binding landed: provenance was lost
        across the approval boundary, so a spoken action was audited as
        ``direct``. It was fixed in the following slice, and the assertion
        flipped with it rather than being deleted.

        It stays here because it is also a scope statement: the digest excludes
        origin, so preserving provenance changed nothing about identity
        binding. ``tests/test_approval_provenance.py`` holds the full round
        trip."""
        action_id, _code = _stage(origin="voice")

        record = pc_control._load_pending_record(action_id)

        assert record is not None
        assert record.request.origin == "voice"
