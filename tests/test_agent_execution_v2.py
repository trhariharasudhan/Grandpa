"""Integration and regression tests for Agent Execution Engine V2."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import click.testing
import pytest

from grandpa.agent.execution import (
    PatchApprovalManager,
    analyze_failure,
    build_patch_proposal,
    inspect_repository,
    is_command_allowed,
    read_file_safe,
    resolve_and_verify_workspace,
)
from grandpa.agent.execution.models import (
    DiagnosticResult,
    FailureAnalysis,
    PatchProposal,
)
from grandpa.agent.runtime import AgentRuntime
from grandpa.cli.agent_run_cmd import agent_group
from grandpa.memory.service import MemoryService


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir).resolve()


@pytest.fixture
def setup_memory():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_memory.db"
        svc = MemoryService.get_instance(db_path=str(db_path))
        yield svc
        MemoryService.reset_instance()


# --- Workspace safety tests ---


def test_workspace_safety(temp_workspace) -> None:
    # 1. Valid workspace
    ws = resolve_and_verify_workspace(str(temp_workspace))
    assert ws.is_safe
    assert ws.root_path == str(temp_workspace)

    # 2. Invalid path
    ws_nonexistent = resolve_and_verify_workspace(str(temp_workspace / "nonexistent"))
    assert not ws_nonexistent.is_safe
    assert "exist" in ws_nonexistent.reason

    # 3. System directories rejection
    ws_sys = resolve_and_verify_workspace("C:\\Windows")
    assert not ws_sys.is_safe
    assert "blocked" in ws_sys.reason

    # 4. Traversal check / sensitive paths
    ws_ssh = resolve_and_verify_workspace("~/.ssh")
    assert not ws_ssh.is_safe
    assert "blocked" in ws_ssh.reason


class TestSensitivePathsBlockedRegardlessOfExistence:
    """A protected location is refused for being protected, not for being absent.

    resolve_and_verify_workspace used to test existence first, so ~/.ssh
    reported "does not exist" on a host without one and "blocked" on a host with
    one -- the same request yielding a different verdict, and an audit trail
    recording the wrong reason. GitHub's windows-latest runner has no ~/.ssh,
    which is how this surfaced.

    is_safe was False either way, so the outcome never changed; these tests pin
    the reason, which is what a reviewer or audit log actually reads.
    """

    @pytest.mark.parametrize("secret_dir", [".ssh", ".aws", ".gemini"])
    def test_nonexistent_user_secret_dir_is_blocked_not_missing(
        self, secret_dir, monkeypatch
    ):
        # The fake home must sit OUTSIDE the system temp directory. Anything
        # under temp is deliberately exempt from the secrets patterns (the
        # Windows temp directory is itself under AppData), so a tmp_path-based
        # home would skip the very check this test exists to pin.
        #
        # Nothing is created on disk -- being absent is the point. Without the
        # ordering fix each of these returns "Workspace path does not exist."
        fake_home = (
            "C:\\grandpa-test-home-does-not-exist"
            if sys.platform == "win32"
            else "/home/grandpa-test-home-does-not-exist"
        )
        monkeypatch.setenv("USERPROFILE", fake_home)
        monkeypatch.setenv("HOME", fake_home)

        ws = resolve_and_verify_workspace(f"~/{secret_dir}")

        assert not ws.is_safe
        assert "blocked" in ws.reason
        assert "does not exist" not in ws.reason

    # The system-directory list is platform-specific by construction: on
    # Windows "/etc" resolves to a drive-relative path such as D:\etc and can
    # never match the POSIX entries, and vice versa. Assert only the entries
    # that are meaningful on the host.
    @pytest.mark.parametrize(
        "system_dir",
        (
            ["C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)"]
            if sys.platform == "win32"
            else ["/etc", "/proc", "/usr/bin", "/sbin"]
        ),
    )
    def test_system_dir_is_blocked_before_existence(self, system_dir):
        ws = resolve_and_verify_workspace(system_dir)

        assert not ws.is_safe
        assert "blocked" in ws.reason
        assert "does not exist" not in ws.reason

    def test_absent_system_dir_is_still_blocked(self):
        # A subdirectory that certainly does not exist, under a directory that
        # certainly is protected. This is the case the reorder is for: the
        # refusal must be about the location, not about the missing folder.
        absent = (
            "C:\\Windows\\grandpa-nonexistent-subdir"
            if sys.platform == "win32"
            else "/etc/grandpa-nonexistent-subdir"
        )
        ws = resolve_and_verify_workspace(absent)

        assert not ws.is_safe
        assert "blocked" in ws.reason
        assert "does not exist" not in ws.reason

    def test_ordinary_missing_path_still_reports_missing(self, tmp_path):
        # The reorder must not turn every absent path into a security refusal;
        # a plain nonexistent directory keeps its original, accurate reason.
        ws = resolve_and_verify_workspace(str(tmp_path / "no-such-dir"))

        assert not ws.is_safe
        assert "exist" in ws.reason
        assert "blocked" not in ws.reason

    def test_temp_workspace_is_still_usable(self, temp_workspace):
        # Guards the is_in_temp carve-out: the Windows temp directory lives
        # under AppData, which is itself a secret pattern, so moving the secrets
        # check earlier must not start blocking legitimate temp workspaces.
        ws = resolve_and_verify_workspace(str(temp_workspace))

        assert ws.is_safe
        assert ws.root_path == str(temp_workspace)


# --- Repository inspection tests ---


def test_repository_inspection(temp_workspace) -> None:
    # Without .git it defaults to clean/empty repo
    state = inspect_repository(str(temp_workspace))
    assert state.is_clean
    assert state.current_branch == "unknown"


# --- Command Catalogue tests ---


def test_command_catalogue() -> None:
    # 1. Allowed
    assert is_command_allowed(
        ["python", "-m", "compileall", "-q", "src", "tests", "scripts"]
    )
    assert is_command_allowed(["uv", "run", "ruff", "check", "src", "tests"])
    assert is_command_allowed(["uv", "run", "pytest", "tests/test_agent_runtime.py"])

    # 2. Blocked raw shells, pipes, chaining
    assert not is_command_allowed(["rm", "-rf", "/"])
    assert not is_command_allowed(["python", "-m", "compileall", ";", "rm", "-rf", "/"])
    assert not is_command_allowed(
        ["uv", "run", "pytest", "tests/test.py", "|", "grep", "foo"]
    )
    assert not is_command_allowed(["powershell", "-Command", "Get-Process"])


# --- Failure Analysis & Evidence tests ---


def test_failure_analysis() -> None:
    # Pytest AssertionError
    res_pytest = DiagnosticResult(
        command=["uv", "run", "pytest", "tests/test_foo.py"],
        exit_code=1,
        stdout="tests/test_foo.py:12: AssertionError\nE assert False",
        stderr="",
        duration_seconds=0.5,
    )
    analysis, evidences = analyze_failure(res_pytest)
    assert analysis.failure_type == "assertion_failure"
    assert analysis.failing_file == "tests/test_foo.py"
    assert analysis.failing_line == 12
    assert analysis.is_confirmed
    assert len(evidences) == 1
    assert evidences[0].failure_type == "assertion_failure"

    # Ruff Undefined Name
    res_ruff = DiagnosticResult(
        command=["uv", "run", "ruff", "check", "src", "tests"],
        exit_code=1,
        stdout="src/grandpa/agent/runtime.py:29:41: F821 Undefined name `Any`",
        stderr="",
        duration_seconds=0.2,
    )
    analysis_ruff, evidences_ruff = analyze_failure(res_ruff)
    assert analysis_ruff.failure_type == "import_error"
    assert analysis_ruff.failing_file == "src/grandpa/agent/runtime.py"
    assert analysis_ruff.failing_line == 29
    assert analysis_ruff.is_confirmed
    assert len(evidences_ruff) == 1


# --- File Reader tests ---


def test_file_reader_safety(temp_workspace) -> None:
    # 1. Bounded reading
    file_path = temp_workspace / "test.py"
    file_path.write_text("print('hello')\n" * 10, encoding="utf-8")

    content = read_file_safe(str(file_path), str(temp_workspace), max_lines=5)
    assert len(content.splitlines()) == 6  # 5 lines + truncation msg
    assert "Truncated" in content

    # 2. Block sensitive files
    env_path = temp_workspace / ".env"
    env_path.write_text("API_KEY=secret", encoding="utf-8")
    content_env = read_file_safe(str(env_path), str(temp_workspace))
    assert "Access Denied" in content_env


# --- Evidence and Safety Proposal validation ---


def test_evidence_and_placeholder_validation(temp_workspace) -> None:
    file_path = temp_workspace / "lib.py"
    file_path.write_text("def my_func():\n    retur 42\n", encoding="utf-8")

    # 1. Block proposal without evidences
    analysis_no_ev = FailureAnalysis(
        analysis_id="an_123",
        failure_type="syntax_error",
        failing_file=str(file_path),
        is_confirmed=True,
        evidence_ids=[],  # Empty!
    )
    changes = [
        {
            "path": str(file_path),
            "diff": "--- a/lib.py\n+++ b/lib.py\n@@ -1,2 +1,2 @@\n def my_func():\n-    retur 42\n+    return 42\n",
        }
    ]
    with pytest.raises(ValueError, match="no diagnostic evidence"):
        build_patch_proposal("goal", analysis_no_ev, changes, str(temp_workspace))

    # 2. Reject comment-only or placeholder diffs
    analysis_ok = FailureAnalysis(
        analysis_id="an_456",
        failure_type="syntax_error",
        failing_file=str(file_path),
        is_confirmed=True,
        evidence_ids=["ev_123"],
    )
    changes_placeholder = [
        {
            "path": str(file_path),
            "diff": "--- a/lib.py\n+++ b/lib.py\n@@ -1,2 +1,2 @@\n def my_func():\n-    retur 42\n+# verified patch change\n",
        }
    ]
    with pytest.raises(ValueError, match="no real changes"):
        build_patch_proposal(
            "goal", analysis_ok, changes_placeholder, str(temp_workspace)
        )

    changes_comment = [
        {
            "path": str(file_path),
            "diff": "--- a/lib.py\n+++ b/lib.py\n@@ -1,2 +1,2 @@\n def my_func():\n+# some comment\n",
        }
    ]
    with pytest.raises(ValueError, match="no real changes"):
        build_patch_proposal("goal", analysis_ok, changes_comment, str(temp_workspace))


# --- Fabricated Proposal Invalidation ---


def test_fabricated_proposal_invalidation(temp_workspace) -> None:
    app_db = temp_workspace / "approvals.db"
    mgr = PatchApprovalManager(db_path=str(app_db))

    # We manually simulate/queue a proposal with a fabricated ID or diff content
    file_path = temp_workspace / "lib.py"
    file_path.write_text("content", encoding="utf-8")

    # 1. Fabricated ID
    prop = PatchProposal(
        proposal_id="4d97007a",
        goal="goal",
        root_cause="cause",
        affected_files=["lib.py"],
        exact_change_summary="summary",
        file_changes=[],
        approval_status="pending",
    )
    mgr.store_proposal(prop)

    loaded = mgr.get_proposal("4d97007a")
    assert loaded is not None
    assert loaded.approval_status == "rejected"

    # Attempting to approve it must fail
    with pytest.raises(ValueError, match="unsupported placeholder proposal"):
        mgr.approve_proposal("4d97007a")


# --- Calculator Fixture End-To-End (Fix 9) ---


def test_calculator_fixture_end_to_end(temp_workspace) -> None:
    # 1. Setup workspace structure
    (temp_workspace / "src").mkdir(exist_ok=True)
    (temp_workspace / "tests").mkdir(exist_ok=True)
    (temp_workspace / "scripts").mkdir(exist_ok=True)

    calc_file = temp_workspace / "calculator.py"
    calc_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    test_file = temp_workspace / "tests" / "test_calculator.py"
    test_file.write_text(
        "from calculator import add\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    app_db = temp_workspace / "approvals.db"
    runtime = AgentRuntime()

    # 2. Run diagnose
    prop = runtime.diagnose(
        goal="Fix error in calculator.py targeting tests/test_calculator.py",
        workspace_root=str(temp_workspace),
        db_path=str(app_db),
    )

    assert isinstance(prop, PatchProposal)
    assert prop.goal == "Fix error in calculator.py targeting tests/test_calculator.py"
    assert "calculator.py" in prop.affected_files
    assert prop.approval_status == "pending"

    # Verify file remains unchanged before approval
    assert "return a - b" in calc_file.read_text(encoding="utf-8")

    # 3. Approve and apply
    mgr = PatchApprovalManager(db_path=str(app_db))
    mgr.approve_proposal(prop.proposal_id)

    report = runtime.apply_patch(
        prop.proposal_id, str(temp_workspace), db_path=str(app_db)
    )
    assert report.final_status == "verified_success"

    # Verify patch actually fixed the calculator.py file
    assert "return a + b" in calc_file.read_text(encoding="utf-8")


# --- Goal Classification and Success checks (Fix 10) ---


def test_read_only_inspections_and_no_failures(temp_workspace, setup_memory) -> None:
    (temp_workspace / "src").mkdir(exist_ok=True)
    (temp_workspace / "tests").mkdir(exist_ok=True)
    (temp_workspace / "scripts").mkdir(exist_ok=True)

    # Write passing dummy test
    (temp_workspace / "tests" / "test_dummy.py").write_text(
        "def test_dummy():\n    assert True\n", encoding="utf-8"
    )

    runtime = AgentRuntime()

    # 1. Repository status inspection goal -> should produce no patch, skip pytest
    res_inspect = runtime.diagnose(
        "Check Grandpa repository status", str(temp_workspace)
    )
    assert isinstance(res_inspect, str)
    assert "repository inspection only" in res_inspect

    # 2. Diagnostics pass completely -> should return no issue detected
    res_ok = runtime.diagnose(
        "Find the failing test in tests/test_dummy.py", str(temp_workspace)
    )
    assert isinstance(res_ok, str)
    assert "No supported failure was found" in res_ok


# --- CLI Commands integration tests ---


def test_cli_execution(temp_workspace, setup_memory) -> None:
    runner = click.testing.CliRunner()
    app_db = temp_workspace / "approvals.db"

    # 1. Inspect command
    res_inspect = runner.invoke(
        agent_group, ["inspect", "Check status", "--workspace", str(temp_workspace)]
    )
    assert res_inspect.exit_code == 0
    assert "Git Status" in res_inspect.output

    # 2. Setup calculator bug for diagnose
    (temp_workspace / "src").mkdir(exist_ok=True)
    (temp_workspace / "tests").mkdir(exist_ok=True)
    (temp_workspace / "scripts").mkdir(exist_ok=True)

    calc_file = temp_workspace / "calculator.py"
    calc_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    test_file = temp_workspace / "tests" / "test_calculator.py"
    test_file.write_text(
        "from calculator import add\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    res_diagnose = runner.invoke(
        agent_group,
        [
            "diagnose",
            "Fix calculator.py in tests/test_calculator.py",
            "--workspace",
            str(temp_workspace),
            "--db-path",
            str(app_db),
        ],
    )
    assert res_diagnose.exit_code == 0
    assert "Proposal ID:" in res_diagnose.output

    import re

    m = re.search(r"Proposal ID:\s*([a-f0-9\-]+)", res_diagnose.output)
    assert m is not None
    prop_id = m.group(1)

    # 3. Preview command
    res_preview = runner.invoke(
        agent_group, ["patch", "preview", "--db-path", str(app_db)]
    )
    assert res_preview.exit_code == 0
    assert prop_id in res_preview.output

    # 4. Approve command
    res_approve = runner.invoke(
        agent_group, ["patch", "approve", prop_id, "--db-path", str(app_db)]
    )
    assert res_approve.exit_code == 0
    assert f"Approved patch proposal '{prop_id}'" in res_approve.output

    # 5. Apply command
    res_apply = runner.invoke(
        agent_group,
        [
            "patch",
            "apply",
            prop_id,
            "--workspace",
            str(temp_workspace),
            "--db-path",
            str(app_db),
        ],
    )
    assert res_apply.exit_code == 0
    assert "Final Status  : VERIFIED_SUCCESS" in res_apply.output
