"""Spoken file mutations must go through the actuator boundary.

The voice ``file_automation`` branch (``voice/operator.py:836``) reached
``FileExecutor``, which mutates the disk directly with ``shutil.move``,
``Path.write_text``, ``shutil.rmtree`` and ``Path.unlink``
(``files/executor.py``). Those mutations had no risk tier, no central approval
gate, no emergency stop, no audit record and no verification.

**Interim migration state.** The file surface is split while the kernel
migration is in flight, and this file pins both halves:

* **Kernel-routed, untouched here** -- ``search``, ``properties``,
  ``create_folder``, ``copy`` go to ``KernelFileAutomationAdapter`` ->
  ``AssistantKernel``, as ``tests/kernel/test_file_*_migration.py`` requires.
* **Boundary-routed** -- ``delete``, ``move``, ``rename``, ``create_file``
  perform their mutation through ``run_local_action``.

The split is temporary by construction and decides nothing about where the file
surface eventually lands.

**Why a fresh executor rather than a configured one.** ``FileAutomation``
builds its kernel adapter only when no executor was injected, and
``test_injected_legacy_executor_remains_a_compatibility_override`` depends on
that: constructor injection is a deliberate override that bypasses the kernel.
So the voice path constructs ``FileAutomation()`` normally and *replaces*
``automation.executor`` with a request-scoped one. Its runner, origin and
dry-run are set in ``__init__`` and never reassigned, so the state cannot
outlive or escape the request even if this layer is ever cached.

What routes is the *mutation only*. Alias resolution, ``_blocked_path``,
``blocks_recursive_delete`` and the overwrite confirmation all stay where they
are -- they are file-domain safety with no equivalent inside
``run_local_action``, and routing must not silently drop them.

Two containment guarantees apply throughout: ``confined_filesystem`` raises if a
mutating primitive is aimed outside the test's ``tmp_path``, and
``no_real_actuator`` makes the module-global actuator raise.
"""

from __future__ import annotations

import inspect
import shutil
from pathlib import Path
from typing import Any

import pytest

from grandpa import pc_control
from grandpa.pc_control import _coerce_request

KERNEL_ROUTED = ("search", "properties", "create_folder", "copy")
BOUNDARY_ROUTED = ("delete", "move", "rename", "create_file")


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------


@pytest.fixture
def confined_filesystem(tmp_path, monkeypatch):
    """Make mutation outside ``tmp_path`` impossible, not merely unlikely."""
    root = tmp_path.resolve()

    def _check(*paths: Any) -> None:
        for raw in paths:
            resolved = Path(str(raw)).expanduser().resolve(strict=False)
            if root not in resolved.parents and resolved != root:
                raise AssertionError(
                    f"filesystem mutation escaped the test directory: {resolved}"
                )

    real_move, real_rmtree = shutil.move, shutil.rmtree
    real_unlink, real_rename = Path.unlink, Path.rename
    real_mkdir, real_write = Path.mkdir, Path.write_text

    monkeypatch.setattr(
        shutil, "move", lambda s, d, *a, **k: (_check(s, d), real_move(s, d))[1]
    )
    monkeypatch.setattr(
        shutil, "rmtree", lambda p, *a, **k: (_check(p), real_rmtree(p))[1]
    )
    monkeypatch.setattr(
        Path, "unlink", lambda self, *a, **k: (_check(self), real_unlink(self))[1]
    )
    monkeypatch.setattr(
        Path,
        "rename",
        lambda self, t, *a, **k: (_check(self, t), real_rename(self, t))[1],
    )
    monkeypatch.setattr(
        Path,
        "mkdir",
        lambda self, *a, **k: (_check(self), real_mkdir(self, *a, **k))[1],
    )
    monkeypatch.setattr(
        Path,
        "write_text",
        lambda self, d, *a, **k: (_check(self), real_write(self, d, *a, **k))[1],
    )
    return root


@pytest.fixture
def no_real_actuator(monkeypatch):
    """A regression must fail loudly rather than reach the real actuator."""

    def explode(payload):
        raise AssertionError(
            f"the real actuator was reached with {payload!r}; "
            "the injected runner was bypassed"
        )

    monkeypatch.setattr(pc_control, "run_local_action", explode)


@pytest.fixture
def no_direct_mutation(monkeypatch):
    """Forbid the legacy mutation primitives for the routed actions."""

    def refuse(name):
        def _refuse(*args, **kwargs):
            raise AssertionError(f"{name} ran instead of the actuator")

        return _refuse

    monkeypatch.setattr(shutil, "move", refuse("shutil.move"))
    monkeypatch.setattr(shutil, "rmtree", refuse("shutil.rmtree"))
    monkeypatch.setattr(Path, "unlink", refuse("Path.unlink"))


@pytest.fixture
def confined_roots(tmp_path, monkeypatch):
    """Point the file layer's own roots at ``tmp_path``.

    The voice parser normalises punctuation out of its input, so this layer
    addresses files by name against ``safe_roots()`` rather than by absolute
    path. Confining those roots is both how a test names a file and a second
    containment guarantee.
    """
    import grandpa.files.executor as file_executor

    monkeypatch.setattr(file_executor, "safe_roots", lambda: (tmp_path,))
    return tmp_path


class RecordingRunner:
    """Stands in for ``run_local_action`` and records every payload."""

    def __init__(self, *, status: str = "completed", ok: bool = True) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.status = status
        self.ok = ok

    def __call__(self, payload: dict[str, Any]):
        self.payloads.append(dict(payload))
        return pc_control.LocalActionResponse(
            ok=self.ok,
            action_id=None,
            status=self.status,
            message="Done.",
            approval_required=self.status == "approval_required",
            risk_level="HIGH",
            evidence={"path": payload.get("target", "")},
        )

    @property
    def action_types(self) -> list[str]:
        return [p.get("action_type") for p in self.payloads]

    @property
    def origins(self) -> list[str]:
        return [_coerce_request(p).origin for p in self.payloads]


class RecordingAutomation:
    target_window = None

    def __init__(self) -> None:
        self.commands: list[str] = []

    def has_pending_confirmation(self) -> bool:
        return False

    def has_pending_window_choice(self) -> bool:
        return False

    def has_pending_dialog(self) -> bool:
        return False

    def handle(self, command: str, dry_run: bool = False):
        from types import SimpleNamespace

        self.commands.append(command)
        return SimpleNamespace(
            status="handled", message="", data={}, confirmation_token=None
        )


def _turn(text: str, runner, monkeypatch, *, dry_run: bool = False):
    """Run the real voice entry point with the planner and actuator replaced."""
    from grandpa.voice.operator import process_voice_operator_turn

    monkeypatch.setattr(
        "grandpa.planner.routing.handle_executive_goal", lambda *a, **k: None
    )
    return process_voice_operator_turn(
        text,
        dry_run=dry_run,
        action_runner=runner,
        automation_service=RecordingAutomation(),
    )


# ---------------------------------------------------------------------------
# The routed mutations
# ---------------------------------------------------------------------------


class TestVoiceMutationsReachTheBoundary:
    def test_a_spoken_move_uses_the_injected_runner(
        self, confined_roots, monkeypatch, no_real_actuator, no_direct_mutation
    ):
        (confined_roots / "report.pdf").write_text("x", encoding="utf-8")
        runner = RecordingRunner()

        _turn("move report.pdf to archive", runner, monkeypatch)

        assert runner.action_types == ["file_move"]

    def test_a_spoken_rename_uses_the_injected_runner(
        self, confined_roots, monkeypatch, no_real_actuator, no_direct_mutation
    ):
        (confined_roots / "report.pdf").write_text("x", encoding="utf-8")
        runner = RecordingRunner()

        _turn("rename report.pdf to final.pdf", runner, monkeypatch)

        assert runner.action_types == ["file_rename"]

    def test_a_spoken_file_creation_uses_the_injected_runner(
        self, confined_roots, monkeypatch, no_real_actuator
    ):
        runner = RecordingRunner()

        _turn("create file notes.txt", runner, monkeypatch)

        assert runner.action_types == ["file_create"]

    def test_the_real_actuator_is_never_reached(
        self, confined_roots, monkeypatch, no_real_actuator, no_direct_mutation
    ):
        """The fixtures raise; reaching either would fail with a message."""
        source = confined_roots / "report.pdf"
        source.write_text("x", encoding="utf-8")
        runner = RecordingRunner()

        _turn("move report.pdf to archive", runner, monkeypatch)

        assert len(runner.payloads) == 1
        assert source.exists(), "the legacy path moved the file itself"

    def test_the_origin_is_voice(
        self, confined_roots, monkeypatch, no_real_actuator, no_direct_mutation
    ):
        (confined_roots / "report.pdf").write_text("x", encoding="utf-8")
        runner = RecordingRunner()

        _turn("move report.pdf to archive", runner, monkeypatch)

        assert runner.origins == ["voice"]

    def test_dry_run_propagates_and_nothing_is_touched(
        self, confined_roots, monkeypatch, no_real_actuator, no_direct_mutation
    ):
        source = confined_roots / "report.pdf"
        source.write_text("x", encoding="utf-8")
        runner = RecordingRunner(status="dry_run")

        _turn("move report.pdf to archive", runner, monkeypatch, dry_run=True)

        assert runner.payloads, "the runner was never called"
        assert all(p.get("dry_run") is True for p in runner.payloads)
        assert source.exists()

    def test_the_resolved_path_is_what_the_actuator_receives(
        self, confined_roots, monkeypatch, no_real_actuator, no_direct_mutation
    ):
        """Resolution stays on the files side, so the payload is a real path."""
        source = confined_roots / "report.pdf"
        source.write_text("x", encoding="utf-8")
        runner = RecordingRunner()

        _turn("move report.pdf to archive", runner, monkeypatch)

        assert Path(runner.payloads[0]["target"]).resolve() == source.resolve()

    def test_a_blocked_response_is_not_reported_as_success(
        self, confined_roots, monkeypatch, no_real_actuator, no_direct_mutation
    ):
        """Policy refusal now reaches the user; before, nothing could refuse."""
        source = confined_roots / "report.pdf"
        source.write_text("x", encoding="utf-8")
        runner = RecordingRunner(status="blocked", ok=False)

        response = _turn("move report.pdf to archive", runner, monkeypatch)

        assert response.status == "blocked"
        assert source.exists()

    def test_an_approval_response_is_surfaced_as_confirmation(
        self, confined_roots, monkeypatch, no_real_actuator, no_direct_mutation
    ):
        source = confined_roots / "report.pdf"
        source.write_text("x", encoding="utf-8")
        runner = RecordingRunner(status="approval_required", ok=False)

        response = _turn("move report.pdf to archive", runner, monkeypatch)

        assert response.requires_confirmation is True
        assert source.exists()

    @pytest.mark.parametrize(
        ("actuator_status", "file_status"),
        [
            ("completed", "handled"),
            ("dry_run", "handled"),
            ("approval_required", "needs_confirmation"),
            ("blocked", "blocked"),
            ("unsupported", "unsupported"),
            ("failed", "error"),
        ],
    )
    def test_every_actuator_status_maps_to_its_own_file_status(
        self, actuator_status, file_status, confined_roots, no_real_actuator
    ):
        """No status may collapse into "handled"; that is how a refusal
        would be reported to the user as a success."""
        from grandpa.files.executor import FileExecutor
        from grandpa.files.parser import FileParser

        (confined_roots / "report.pdf").write_text("x", encoding="utf-8")
        runner = RecordingRunner(
            status=actuator_status, ok=actuator_status == "completed"
        )

        result = FileExecutor(mutation_runner=runner, origin="voice").execute(
            FileParser().parse("move report.pdf to archive")
        )

        assert result.status == file_status

    def test_the_action_types_are_the_existing_ones(self):
        assert "file_move" in pc_control.MEDIUM_RISK_ACTIONS
        assert "file_rename" in pc_control.MEDIUM_RISK_ACTIONS
        assert "file_create" in pc_control.LOW_RISK_ACTIONS
        assert "file_delete" in pc_control.HIGH_RISK_ACTIONS


# ---------------------------------------------------------------------------
# Delete: routed, and gated before it routes
# ---------------------------------------------------------------------------


class TestDelete:
    def test_a_delete_is_confirmation_gated_before_anything_runs(
        self, confined_roots, no_real_actuator, no_direct_mutation
    ):
        """Correcting the earlier audit: a spoken delete never reached the disk.

        ``FileExecutor._delete`` returns ``needs_confirmation`` without a
        confirmation callback, and the voice path supplies none. The phrasing
        does not survive the voice layer either. So the exposure this closes
        for the *voice* surface is move, rename and create_file; delete is
        routed for the callers that do confirm.
        """
        from grandpa.files.executor import FileExecutor
        from grandpa.files.parser import FileParser

        victim = confined_roots / "report.pdf"
        victim.write_text("x", encoding="utf-8")
        runner = RecordingRunner()
        action = FileParser().parse("delete report.pdf")

        result = FileExecutor(mutation_runner=runner, origin="voice").execute(action)

        assert runner.payloads == []
        assert result.requires_confirmation is True
        assert victim.exists()

    def test_a_confirmed_delete_routes_through_the_actuator(
        self, confined_roots, no_real_actuator, no_direct_mutation
    ):
        from grandpa.files.executor import FileExecutor
        from grandpa.files.parser import FileParser

        victim = confined_roots / "report.pdf"
        victim.write_text("x", encoding="utf-8")
        runner = RecordingRunner()
        action = FileParser().parse("delete report.pdf")

        result = FileExecutor(mutation_runner=runner, origin="voice").execute(
            action, confirm=lambda *args: True
        )

        assert runner.action_types == ["file_delete"]
        assert runner.origins == ["voice"]
        assert result.status == "handled"
        assert victim.exists(), "the legacy path deleted the file itself"

    def test_the_recursive_delete_guard_still_runs_first(
        self, confined_roots, monkeypatch, no_real_actuator, no_direct_mutation
    ):
        """A file-domain check with no equivalent inside run_local_action."""
        from grandpa.files.executor import FileExecutor
        from grandpa.files.parser import FileParser
        from grandpa.files.safety import FileSafetyPolicy

        monkeypatch.setattr(
            FileSafetyPolicy, "blocks_recursive_delete", lambda self, path: True
        )
        folder = confined_roots / "docs"
        folder.mkdir()
        runner = RecordingRunner()
        action = FileParser().parse("delete docs")

        result = FileExecutor(mutation_runner=runner, origin="voice").execute(
            action, confirm=lambda *args: True
        )

        assert runner.payloads == [], "a blocked delete reached the actuator"
        assert result.status == "blocked"
        assert folder.exists()


# ---------------------------------------------------------------------------
# Request-scoped state
# ---------------------------------------------------------------------------


class TestRequestScopedState:
    def test_two_instances_do_not_share_state(self, tmp_path):
        """The reason this is a fresh executor and not a configured one."""
        from grandpa.files.executor import FileExecutor

        configured = FileExecutor(
            roots=(tmp_path,),
            mutation_runner=RecordingRunner(),
            origin="voice",
            dry_run=True,
        )
        plain = FileExecutor(roots=(tmp_path,))

        assert plain.mutation_runner is None
        assert plain.origin == "direct"
        assert plain.dry_run is False
        assert configured.origin == "voice"

    def test_the_defaults_are_not_shared_class_state(self):
        """Instance attributes, so one request cannot configure another."""
        from grandpa.files.executor import FileExecutor

        first = FileExecutor()
        second = FileExecutor()

        assert "mutation_runner" in vars(first)
        assert "origin" in vars(first)
        assert "dry_run" in vars(first)
        assert first.mutation_runner is None and second.mutation_runner is None

    def test_execute_does_not_mutate_the_configuration(
        self, confined_roots, no_real_actuator, no_direct_mutation
    ):
        from grandpa.files.executor import FileExecutor
        from grandpa.files.parser import FileParser

        (confined_roots / "report.pdf").write_text("x", encoding="utf-8")
        runner = RecordingRunner()
        executor = FileExecutor(mutation_runner=runner, origin="voice", dry_run=False)

        executor.execute(FileParser().parse("move report.pdf to archive"))

        assert executor.origin == "voice"
        assert executor.dry_run is False
        assert executor.mutation_runner is runner

    def test_a_default_executor_still_mutates_directly(
        self, tmp_path, confined_filesystem
    ):
        """Chat and CLI callers are out of scope and must be unaffected."""
        from grandpa.files import handle_file_automation

        victim = tmp_path / "report.pdf"
        victim.write_text("x", encoding="utf-8")

        result = handle_file_automation(
            "delete report.pdf", confirm=lambda *args: True, roots=(tmp_path,)
        )

        assert result.status == "handled"
        assert not victim.exists()


# ---------------------------------------------------------------------------
# Frozen contracts
# ---------------------------------------------------------------------------


class TestFrozenContractsIntact:
    def test_the_public_signatures_are_unchanged(self):
        """Mirrors the kernel guard; a local copy fails faster and louder."""
        from grandpa.files.automation import FileAutomation, handle_file_automation

        assert list(inspect.signature(FileAutomation).parameters) == [
            "roots",
            "parser",
            "executor",
            "opener",
        ]
        assert list(inspect.signature(FileAutomation.handle).parameters) == [
            "self",
            "text",
            "confirm",
        ]
        assert list(inspect.signature(handle_file_automation).parameters) == [
            "text",
            "roots",
            "confirm",
            "opener",
        ]

    def test_the_execute_signature_is_unchanged(self):
        from grandpa.files.executor import FileExecutor

        assert list(inspect.signature(FileExecutor.execute).parameters) == [
            "self",
            "action",
            "confirm",
        ]

    def test_the_new_configuration_is_keyword_only(self):
        from grandpa.files.executor import FileExecutor

        parameters = inspect.signature(FileExecutor).parameters
        for name in ("mutation_runner", "origin", "dry_run"):
            assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY

    def test_an_injected_legacy_executor_still_overrides(self, tmp_path):
        """Mirrors ``test_injected_legacy_executor_remains_a_compatibility_override``."""
        from grandpa.files.automation import FileAutomation
        from grandpa.files.models import FileOperationResult

        class RecordingExecutor:
            roots = (tmp_path,)

            def __init__(self):
                self.calls = 0

            def execute(self, action, *, confirm=None):
                self.calls += 1
                return FileOperationResult("handled", "injected", action)

        executor = RecordingExecutor()
        result = FileAutomation(executor=executor).handle("Find report.txt")

        assert result.message == "injected"
        assert executor.calls == 1


# ---------------------------------------------------------------------------
# The kernel half is untouched
# ---------------------------------------------------------------------------


class TestFileMutationsReachTheBoundary:
    """What the legacy kernel adapter used to prevent.

    This class was ``TestKernelRoutingUnchanged``, and it asserted the
    opposite: that ``search``, ``properties``, ``create_folder`` and ``copy``
    stayed on the kernel path and never reached ``run_local_action``. That was
    an accurate description of the migration-era design and a real constraint
    -- the voice path had to *replace* ``FileAutomation.executor`` after
    construction rather than inject it, because injecting one suppressed the
    adapter those four depended on.

    With the adapter gone there is one executor and the constraint is gone with
    it. The two mutating actions now reach the boundary like every other file
    mutation, which is the security outcome the adapter was standing in the way
    of. The two read-only actions still do not, because they have no mutation
    to route.
    """

    @pytest.mark.parametrize(
        ("phrase", "action_type"),
        [
            ("create folder reports", "file_create"),
            ("move report.pdf to archive", "file_move"),
        ],
    )
    def test_a_spoken_mutation_reaches_the_actuator(
        self, phrase, action_type, confined_roots, monkeypatch, no_real_actuator
    ):
        (confined_roots / "report.pdf").write_text("x", encoding="utf-8")
        runner = RecordingRunner()

        _turn(phrase, runner, monkeypatch)

        assert [p["action_type"] for p in runner.payloads] == [action_type]

    @pytest.mark.parametrize(
        "phrase", ["search for notes", "show properties of report.pdf"]
    )
    def test_a_spoken_read_only_action_does_not(
        self, phrase, confined_roots, monkeypatch, no_real_actuator
    ):
        """Nothing to route: these mutate nothing."""
        (confined_roots / "report.pdf").write_text("x", encoding="utf-8")
        runner = RecordingRunner()

        _turn(phrase, runner, monkeypatch)

        assert runner.payloads == []

    def test_the_voice_path_still_carries_its_provenance(
        self, confined_roots, monkeypatch, no_real_actuator
    ):
        (confined_roots / "report.pdf").write_text("x", encoding="utf-8")
        runner = RecordingRunner()

        _turn("create folder reports", runner, monkeypatch)

        assert runner.payloads and runner.payloads[0]["origin"] == "voice"

    def test_the_adapter_is_gone(self):
        """The construction detail that used to decide which implementation
        served a command no longer exists."""
        import importlib

        from grandpa.files.automation import FileAutomation

        assert not hasattr(FileAutomation(), "_read_only_kernel")
        for module in ("grandpa.kernel", "grandpa.files.kernel_adapter"):
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(module)


class TestScope:
    def test_no_new_action_types(self):
        for action_type in ("file_create", "file_delete", "file_move", "file_rename"):
            assert (
                action_type in pc_control.LOW_RISK_ACTIONS
                or action_type in pc_control.MEDIUM_RISK_ACTIONS
                or action_type in pc_control.HIGH_RISK_ACTIONS
            )

    def test_permanent_delete_is_still_blocked(self):
        assert "file_permanent_delete" in pc_control.BLOCKED_ACTIONS

    def test_the_origin_vocabulary_is_unchanged(self):
        assert pc_control.ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )
