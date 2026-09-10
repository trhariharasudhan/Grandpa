"""The seam a capability package uses to reach the hardened boundary.

``FileExecutor`` already routes its mutations through an injected callable
rather than importing ``pc_control``. That indirection is what keeps the file
layer off the execution module, and it is why ``files/`` does not appear in the
saturated importer baseline. What it lacked was a name and an owner: the type
lived in ``files/executor.py`` as a bare ``Callable`` alias, so the seam was an
implementation detail of the capability rather than a contract the policy layer
offered.

This gives it both. ``MutationBoundary`` is declared in ``grandpa.policy``,
which the target architecture names as a permitted dependency for capability
packages -- unlike ``pc_control``, which is an entry-surface module they must
not import.

**It is a callable protocol, not an object with a ``run`` method**, and that is
deliberate rather than a shortcut. The existing seam is invoked as
``self.mutation_runner(payload)`` and the thing injected is
``run_local_action`` itself. A method-based protocol would satisfy nobody
without an adapter at every injection site, and adapters are exactly the
"semantic change" this slice is forbidden to make. Structural typing already
describes what is there.

Nothing about enforcement moves. Policy names the seam; ``pc_control`` still
owns every gate behind it; ``FileExecutor`` still owns filesystem behaviour.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from grandpa.policy.boundary import MutationBoundary

REPO = Path(__file__).resolve().parents[1]
POLICY_DIR = REPO / "src" / "grandpa" / "policy"
FILES_DIR = REPO / "src" / "grandpa" / "files"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class RecordingBoundary:
    """A boundary that records instead of acting. Satisfies the protocol
    structurally, without inheriting from it."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]) -> Any:
        self.payloads.append(dict(payload))
        from grandpa.pc_control import LocalActionResponse

        return LocalActionResponse(
            ok=True,
            action_id=None,
            status="completed",
            message="recorded",
            approval_required=False,
            risk_level="LOW",
            evidence={},
        )


def _use(boundary: MutationBoundary, payload: dict[str, Any]) -> Any:
    """Bind something to the protocol and call it, so conformance is
    exercised rather than asserted."""
    return boundary(payload)


# ---------------------------------------------------------------------------
# A -- the protocol
# ---------------------------------------------------------------------------


class TestTheProtocol:
    def test_it_is_importable_from_the_policy_package(self):
        from grandpa.policy import MutationBoundary as exported

        assert exported is MutationBoundary

    def test_it_describes_a_callable_not_an_object_with_a_method(self):
        """The existing seam is invoked as ``runner(payload)`` and the thing
        injected is ``run_local_action``. A ``.run`` method would need an
        adapter at every injection site, which is a semantic change."""
        assert hasattr(MutationBoundary, "__call__")
        assert not hasattr(MutationBoundary, "run")

    def test_the_hardened_runner_satisfies_it_unchanged(self):
        """No adapter: the production runner is passed as-is."""
        from grandpa.pc_control import run_local_action

        assert callable(run_local_action)
        bound: MutationBoundary = run_local_action
        assert bound is run_local_action

    def test_a_fake_satisfies_it_without_inheriting(self):
        boundary = RecordingBoundary()

        assert MutationBoundary not in type(boundary).__mro__

        _use(boundary, {"action_type": "file_create", "target": "x"})

        assert boundary.payloads == [{"action_type": "file_create", "target": "x"}]

    def test_it_asks_exactly_one_thing(self):
        """A seam that grew methods would stop being a seam."""
        public = [
            name
            for name in vars(MutationBoundary)
            if not name.startswith("_") and callable(vars(MutationBoundary)[name])
        ]

        assert public == []


# ---------------------------------------------------------------------------
# B, I, J -- dependency direction
# ---------------------------------------------------------------------------


class TestDependencyDirection:
    def test_the_policy_package_imports_no_execution_module(self):
        for path in POLICY_DIR.glob("*.py"):
            modules = _imports(path)
            assert not any("pc_control" in m for m in modules), path.name
            assert not any("local_actions" in m for m in modules), path.name
            assert not any(m.startswith("grandpa.kernel") for m in modules), path.name

    def test_the_boundary_module_stays_capability_agnostic(self):
        """No filesystem, browser, subprocess, window or network concepts."""
        modules = _imports(POLICY_DIR / "boundary.py")

        assert modules <= {"__future__", "collections.abc", "typing"}

    def test_no_files_module_imports_pc_control(self):
        """The property that keeps ``files/`` out of the saturated baseline."""
        for path in FILES_DIR.rglob("*.py"):
            assert not any("pc_control" in m for m in _imports(path)), path.relative_to(
                REPO
            ).as_posix()

    def test_the_baseline_grew_only_for_the_composition_layer(self):
        """Fifty-one when this seam was introduced; fifty-two once the entry
        surfaces were composed. The one addition is the module whose job is to
        name the actuator -- which is the opposite of the bypass the baseline
        guards against, and the reason capability packages can stay off it.
        ``tests/test_file_composition.py`` pins which module that is."""
        baseline = json.loads(
            (
                REPO / "tests" / "architecture" / "direct_executor_baseline.json"
            ).read_text(encoding="utf-8")
        )

        # 53 since 4.5H-3: ``composition/ask_handlers.py`` is the approved
        # application-level composition consumer of ``local_actions``,
        # added for the ask.py dispatcher migration. Still an exact count,
        # so any further importer has to come past this line.
        assert sum(len(paths) for paths in baseline.values()) == 53
        assert "src/grandpa/composition/files.py" in baseline["pc_control"]

    def test_the_executor_names_the_seam_from_policy(self):
        """``files/`` depends on ``policy``, which the layering permits, rather
        than on the execution module, which it does not."""
        assert "grandpa.policy.boundary" in _imports(FILES_DIR / "executor.py")

    def test_the_executor_alias_is_the_policy_protocol(self):
        """Importing the protocol is not the same as using it.

        A mutation that reverted ``MutationRunner`` to a locally-declared
        ``Callable`` survived the rest of this file: the import stayed, unused,
        and every behavioural test still passed because the runtime seam is
        structural either way. That is precisely the regression this slice
        exists to prevent -- the capability package would once again own the
        name of a boundary it does not own -- so the identity is pinned rather
        than inferred from the import.
        """
        from grandpa.files.executor import MutationRunner

        assert MutationRunner is MutationBoundary


# ---------------------------------------------------------------------------
# C, D, E, F -- behaviour through the seam is unchanged
# ---------------------------------------------------------------------------


ROUTED = [
    ("create file fresh.txt", "file_create"),
    ("create folder alpha", "file_create"),
    ("copy note.txt to duplicate.txt", "file_copy"),
    ("delete note.txt", "file_delete"),
    ("move note.txt to existing", "file_move"),
    ("rename note.txt to renamed.txt", "file_rename"),
]


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("hello", encoding="utf-8")
    (root / "existing").mkdir()
    return root


def _executor(workspace: Path, boundary=None):
    from grandpa.files.executor import FileExecutor
    from grandpa.files.safety import FileSafetyPolicy

    return FileExecutor(
        roots=(workspace,), safety=FileSafetyPolicy(), mutation_runner=boundary
    )


def _run(executor, command: str):
    from grandpa.files.parser import FileParser

    action = FileParser().parse(command)
    assert action is not None, command
    return executor.execute(action, confirm=lambda *args: True)


class TestBehaviourThroughTheSeam:
    @pytest.mark.parametrize(("command", "action_type"), ROUTED)
    def test_every_routed_mutation_reaches_the_boundary(
        self, command, action_type, workspace
    ):
        boundary = RecordingBoundary()

        _run(_executor(workspace, boundary), command)

        assert [p["action_type"] for p in boundary.payloads] == [action_type]

    @pytest.mark.parametrize(("command", "_action_type"), ROUTED)
    def test_the_payload_shape_is_unchanged(self, command, _action_type, workspace):
        """A compatibility contract: the payload is what ``run_local_action``
        already accepts."""
        boundary = RecordingBoundary()

        _run(_executor(workspace, boundary), command)

        assert set(boundary.payloads[0]) == {
            "action_type",
            "target",
            "args",
            "origin",
            "dry_run",
            "require_approval",
        }

    @pytest.mark.parametrize(
        "command", ["search for note", "show properties of note.txt"]
    )
    def test_a_read_only_action_never_touches_the_boundary(self, command, workspace):
        boundary = RecordingBoundary()

        _run(_executor(workspace, boundary), command)

        assert boundary.payloads == []

    @pytest.mark.parametrize(("command", "_action_type"), ROUTED)
    def test_without_a_boundary_the_executor_behaves_as_before(
        self, command, _action_type, workspace
    ):
        """Injection stays optional; callers that supply nothing are
        untouched."""
        result = _run(_executor(workspace, None), command)

        assert result.status == "handled"


# ---------------------------------------------------------------------------
# K -- the security invariants this slice must not touch
# ---------------------------------------------------------------------------


class TestFrozenContractsUnchanged:
    def test_the_risk_vocabulary_and_tables_are_untouched(self):
        from grandpa import pc_control
        from grandpa.apps.safety import BLOCKED_EXECUTABLE_NAMES

        assert pc_control.ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )
        assert len(pc_control.SENSITIVE_APP_RISK) == 21
        assert dict(pc_control.SENSITIVE_EXECUTABLE_RISK) == {"git-bash.exe": "MEDIUM"}
        assert len(BLOCKED_EXECUTABLE_NAMES) == 5

    def test_the_request_contract_is_untouched(self):
        from dataclasses import fields

        from grandpa.pc_control import LocalActionRequest

        assert [f.name for f in fields(LocalActionRequest)] == [
            "action_type",
            "target",
            "args",
            "require_approval",
            "dry_run",
            "origin",
        ]

    def test_the_enforcement_gates_still_live_in_pc_control(self):
        """Policy names the seam; it does not own a single gate."""
        import inspect

        from grandpa import pc_control

        approve = inspect.getsource(pc_control._approve_local_action_impl)
        assert "compare_digest" in approve
        assert "if not _mark_pending_decision" in approve
        assert "_EMERGENCY_STOP_ACTIVE" in inspect.getsource(pc_control)

    def test_policy_holds_no_execution_state_or_approval_store(self):
        """The seam must not become a place where policy re-implements the
        thing it points at.

        What is forbidden is *machinery*, and the token list says which:
        ``compare_digest`` (approval-token comparison), ``_mark_pending_decision``
        (mutating persistent approval state), ``EMERGENCY_STOP`` (the stop
        flag), ``sqlite3`` (the approval store), and ``shutil`` / ``subprocess``
        (touching the machine). Those belong to the execution module, and a
        copy of any of them here would make ``policy`` a second place where an
        action can be approved or run.

        **A pure rule is not machinery.** ``policy.engine`` states what the
        tier is and whether approval is required; it decides nothing, persists
        nothing and actuates nothing, and those functions are the point of the
        package rather than a violation of it. The earlier name for this test
        -- ``test_no_second_execution_or_approval_implementation_exists`` --
        read as though it forbade ``requires_approval`` itself, which it never
        did and does not now. The assertion below is unchanged; only the name
        and this explanation are.

        Enforcement staying put is a separate claim, held by
        ``test_the_enforcement_gates_still_live_in_pc_control`` above and by
        ``tests/test_kernel_approval_facade.py``.
        """
        for path in POLICY_DIR.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            for forbidden in (
                "compare_digest",
                "_mark_pending_decision",
                "EMERGENCY_STOP",
                "sqlite3",
                "shutil",
                "subprocess",
            ):
                assert forbidden not in source, f"{path.name}: {forbidden}"
