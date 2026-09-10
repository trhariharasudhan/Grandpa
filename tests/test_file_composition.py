"""Production file surfaces build their automation through composition.

``FileExecutor`` has accepted an injected ``MutationBoundary`` since the
mutation-boundary slice, but injection was opt-in and exactly one caller opted
in. Both CLI modules, the HTTP chat route and the voice assistant all reached
``FileAutomation`` through its default construction, which supplies no runner --
so a typed or spoken ``delete``, ``move``, ``rename``, ``create_file``,
``create_folder`` or ``copy`` arriving through any of them mutated the disk
directly, with no risk tier, approval gate, emergency stop, audit record or
verification.

``grandpa.composition`` is the layer that closes that. It is the only module
permitted to name the concrete actuator: ``files/`` and ``policy/`` must both
stay off the execution module, and the four entry surfaces would otherwise
repeat the same wiring four times.

**What is deliberately unchanged.** ``FileExecutor(..., mutation_runner=None)``
still mutates the disk itself. That is a compatibility contract with direct
capability callers, asserted below and depended on by
``tests/test_file_automation.py`` and ``tests/test_file_capability_baseline.py``.
Composition opts the *entry surfaces* into the boundary; it does not change what
the capability does when nobody asks.

**Two kinds of assertion, on purpose.** Where a surface can be driven for real
-- the ``/files`` slash command and the voice assistant -- it is, with the
actuator substituted, and the payload is inspected. ``cli/ask.py``,
``chat_cmd``'s interactive loop and the async HTTP route sit behind click
commands, a REPL and FastAPI plumbing that would have to be reassembled here;
for those the call site is asserted statically, which is what would actually
regress -- someone dropping the ``origin`` argument.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from grandpa import pc_control
from grandpa.composition import build_file_automation
from grandpa.pc_control import _coerce_request

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "grandpa"
COMPOSITION_DIR = SRC / "composition"
COMPOSITION_MODULE = "src/grandpa/composition/files.py"


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class RecordingBoundary:
    """Satisfies ``MutationBoundary`` structurally; records instead of acting."""

    def __init__(self, *, status: str = "completed", ok: bool = True) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.status = status
        self.ok = ok

    def __call__(self, payload):
        self.payloads.append(dict(payload))
        return pc_control.LocalActionResponse(
            ok=self.ok,
            action_id=None,
            status=self.status,
            message="Done.",
            approval_required=self.status == "approval_required",
            risk_level="LOW",
            evidence={"path": payload.get("target", "")},
        )

    @property
    def action_types(self) -> list[str]:
        return [p.get("action_type") for p in self.payloads]

    @property
    def origins(self) -> list[str]:
        return [_coerce_request(p).origin for p in self.payloads]


@pytest.fixture
def confined_roots(tmp_path, monkeypatch):
    """A workspace the file layer treats as its only root.

    Both root sources are replaced: ``files.executor.safe_roots`` is what an
    empty ``roots`` resolves to, and ``file_assistant._safe_roots`` is what the
    shared handler passes in. A test that patched only one would exercise the
    real Downloads, Documents and Desktop folders through the other.
    """
    import grandpa.file_assistant as file_assistant
    import grandpa.files.executor as file_executor

    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    (root / "report.pdf").write_text("x", encoding="utf-8")
    (root / "note.txt").write_text("hello", encoding="utf-8")
    (root / "archive").mkdir()
    monkeypatch.setattr(file_executor, "safe_roots", lambda: (root,))
    monkeypatch.setattr(file_assistant, "_safe_roots", lambda: [root])
    return root


@pytest.fixture
def substituted_actuator(monkeypatch):
    """Replace the real actuator on the module the helper looks it up on."""
    boundary = RecordingBoundary()
    monkeypatch.setattr(pc_control, "run_local_action", boundary)
    return boundary


def _code_only(path: Path) -> str:
    """The module with its prose removed.

    The forbidden-symbol scan below is about what the module *does*, and this
    module's docstrings name several of those symbols precisely to say it does
    not do them. Stripping docstrings keeps the guard pointed at code, so the
    explanation of a rule cannot trip the rule.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body.pop(0)
    return ast.unparse(tree)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------


class TestTheHelper:
    def test_it_returns_a_file_automation(self, confined_roots):
        from grandpa.files.automation import FileAutomation

        assert isinstance(build_file_automation(), FileAutomation)

    def test_it_injects_the_hardened_actuator_by_default(
        self, confined_roots, substituted_actuator
    ):
        automation = build_file_automation()

        assert automation.executor.mutation_runner is substituted_actuator

    def test_the_actuator_is_resolved_at_call_time_not_import_time(
        self, confined_roots, substituted_actuator
    ):
        """A helper that bound the actuator at import would hand a test's
        substitution back the real machine, silently."""
        import grandpa.composition.files as composition_files

        assert "run_local_action" not in vars(composition_files)
        assert build_file_automation().executor.mutation_runner is substituted_actuator

    def test_a_caller_with_its_own_runner_keeps_it(self, confined_roots):
        """The voice operator threads a per-turn runner and predates this
        module; defaulting rather than requiring is what preserves that seam."""
        boundary = RecordingBoundary()

        assert (
            build_file_automation(mutation_runner=boundary).executor.mutation_runner
            is boundary
        )

    def test_it_forwards_origin_dry_run_roots_and_opener(self, tmp_path):
        def opener(path):
            return None

        root = tmp_path / "w"
        root.mkdir()

        executor = build_file_automation(
            roots=(root,), opener=opener, origin="voice", dry_run=True
        ).executor

        assert executor.roots == (root,)
        assert executor.opener is opener
        assert executor.origin == "voice"
        assert executor.dry_run is True

    def test_empty_roots_and_opener_keep_their_existing_meaning(self, confined_roots):
        """``roots=()`` still means "the default roots", resolved where it
        always was, so composition adds a runner and nothing else."""
        executor = build_file_automation().executor

        assert executor.roots == (confined_roots,)
        assert executor.opener is not None

    def test_the_default_origin_is_the_least_privileged_one(self):
        from grandpa.composition import DEFAULT_FILE_ORIGIN

        assert DEFAULT_FILE_ORIGIN == "direct"
        assert DEFAULT_FILE_ORIGIN in pc_control.ACTION_ORIGINS
        assert build_file_automation().executor.origin == "direct"


# ---------------------------------------------------------------------------
# Composition owns composition, and nothing else
# ---------------------------------------------------------------------------


class TestItStaysComposition:
    def test_it_implements_no_policy_approval_or_execution(self):
        for path in COMPOSITION_DIR.glob("*.py"):
            body = _code_only(path)
            for forbidden in (
                "compare_digest",
                "_mark_pending_decision",
                "_EMERGENCY_STOP",
                "sqlite3",
                "shutil",
                "subprocess",
                "RISK_ACTIONS",
                "APPROVAL_REQUIRED",
                "hashlib",
            ):
                assert forbidden not in body, f"{path.name}: {forbidden}"

    def test_it_declares_no_risk_or_capability_tables(self):
        """A denylist or tier table here would be the second policy
        implementation this layering exists to prevent."""
        for path in COMPOSITION_DIR.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            containers = [
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.Dict, ast.Set))
                or (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") == "frozenset"
                )
            ]

            assert containers == [], path.name

    def test_it_has_one_public_entry_point(self):
        import grandpa.composition as composition

        assert composition.__all__ == ["DEFAULT_FILE_ORIGIN", "build_file_automation"]


# ---------------------------------------------------------------------------
# Layering
# ---------------------------------------------------------------------------


class TestLayering:
    def test_composition_names_the_actuator(self):
        """The one module allowed to. That is its whole reason to exist."""
        modules = _imports(COMPOSITION_DIR / "files.py")

        assert "grandpa" in modules or "grandpa.pc_control" in modules

    def test_the_capability_package_still_does_not(self):
        for path in (SRC / "files").rglob("*.py"):
            assert not any("pc_control" in m for m in _imports(path)), path.name

    def test_the_policy_package_still_does_not(self):
        for path in (SRC / "policy").glob("*.py"):
            assert not any("pc_control" in m for m in _imports(path)), path.name

    def test_nothing_below_the_entry_surfaces_imports_composition(self):
        """Composition is wired downward, never reached upward."""
        for package in ("files", "policy"):
            for path in (SRC / package).rglob("*.py"):
                assert not any("grandpa.composition" in m for m in _imports(path)), (
                    path.name
                )

    def test_the_importer_baseline_grew_by_exactly_the_composition_module(self):
        from tests.architecture.test_direct_executor_baseline import (
            _current_direct_imports,
        )

        baseline = {
            name: set(paths)
            for name, paths in json.loads(
                (
                    REPO / "tests" / "architecture" / "direct_executor_baseline.json"
                ).read_text(encoding="utf-8")
            ).items()
        }
        current = _current_direct_imports()

        # 53 since 4.5H-3: ``composition/ask_handlers.py`` is the approved
        # application-level composition consumer of ``local_actions``,
        # added for the ask.py dispatcher migration. Still an exact count,
        # so any further importer has to come past this line.
        assert sum(map(len, baseline.values())) == 53
        assert COMPOSITION_MODULE in baseline["pc_control"]

        previous = {
            name: paths - {COMPOSITION_MODULE} for name, paths in baseline.items()
        }
        added = {
            name: sorted(current[name] - previous[name])
            for name in previous
            if current[name] - previous[name]
        }

        assert added == {"pc_control": [COMPOSITION_MODULE]}


# ---------------------------------------------------------------------------
# Every mutation reaches the boundary; nothing else does
# ---------------------------------------------------------------------------


ROUTED = [
    ("create file fresh.txt", "file_create"),
    ("create folder alpha", "file_create"),
    ("copy note.txt to duplicate.txt", "file_copy"),
    ("delete note.txt", "file_delete"),
    ("move report.pdf to archive", "file_move"),
    ("rename note.txt to renamed.txt", "file_rename"),
]
READ_ONLY = ["search for note", "show properties of note.txt"]


class TestMutationsReachTheBoundary:
    @pytest.mark.parametrize(("command", "action_type"), ROUTED)
    def test_every_mutation_routes(
        self, command, action_type, confined_roots, substituted_actuator
    ):
        build_file_automation().handle(command, confirm=lambda *a: True)

        assert substituted_actuator.action_types == [action_type]

    @pytest.mark.parametrize(("command", "_action_type"), ROUTED)
    def test_nothing_is_written_before_the_boundary_is_asked(
        self, command, _action_type, confined_roots, substituted_actuator
    ):
        """The recorder never touches the disk, so an unchanged tree after a
        routed command is proof the mutation happened behind the boundary and
        not in front of it."""
        before = sorted(p.name for p in confined_roots.iterdir())

        build_file_automation().handle(command, confirm=lambda *a: True)

        assert substituted_actuator.payloads
        assert sorted(p.name for p in confined_roots.iterdir()) == before

    @pytest.mark.parametrize("command", READ_ONLY)
    def test_a_read_only_action_never_reaches_the_boundary(
        self, command, confined_roots, substituted_actuator
    ):
        build_file_automation().handle(command)

        assert substituted_actuator.payloads == []

    def test_a_delete_is_still_confirmation_gated_before_routing(
        self, confined_roots, substituted_actuator
    ):
        """File-domain safety runs first and is not replaced by the boundary."""
        result = build_file_automation().handle("delete note.txt", confirm=None)

        assert substituted_actuator.payloads == []
        assert result.requires_confirmation
        assert (confined_roots / "note.txt").exists()


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class TestProvenance:
    @pytest.mark.parametrize("origin", ["direct", "voice"])
    def test_the_requested_origin_reaches_the_boundary(
        self, origin, confined_roots, substituted_actuator
    ):
        build_file_automation(origin=origin).handle("create file fresh.txt")

        assert substituted_actuator.origins == [origin]

    def test_the_origin_vocabulary_is_not_extended(self):
        assert pc_control.ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )


# ---------------------------------------------------------------------------
# The four production surfaces
# ---------------------------------------------------------------------------


def _call_site_origins(module: str) -> list[str]:
    """The ``origin=`` literal at every ``handle_file_command`` call site."""
    tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
    origins: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "handle_file_command":
            continue
        value = {k.arg: k.value for k in node.keywords}.get("origin")
        origins.append(value.value if isinstance(value, ast.Constant) else "<missing>")
    return origins


class TestTheProductionSurfaces:
    def test_the_shared_handler_builds_through_composition(
        self, confined_roots, substituted_actuator, tmp_path
    ):
        """All four surfaces reach the file layer through this one function."""
        from grandpa.file_assistant import FileAssistantStore, handle_file_command

        handle_file_command(
            "create file fresh.txt", store=FileAssistantStore(tmp_path / "s.db")
        )

        assert substituted_actuator.action_types == ["file_create"]

    def test_the_cli_slash_command_routes_as_direct(
        self, confined_roots, substituted_actuator
    ):
        from grandpa.cli.chat_cmd import _handle_files_slash_command

        _handle_files_slash_command("/files create-folder alpha")

        assert substituted_actuator.action_types == ["file_create"]
        assert substituted_actuator.origins == ["direct"]

    def test_the_voice_assistant_routes_as_voice(
        self, confined_roots, substituted_actuator
    ):
        from grandpa.voice.assistant import VoiceCommandProcessor

        VoiceCommandProcessor().handle_user_input("create folder alpha")

        assert substituted_actuator.action_types == ["file_create"]
        assert substituted_actuator.origins == ["voice"]

    def test_the_voice_operator_routes_as_voice_through_the_helper(
        self, confined_roots, monkeypatch
    ):
        from grandpa.voice.operator import process_voice_operator_turn

        boundary = RecordingBoundary()
        monkeypatch.setattr(
            "grandpa.planner.routing.handle_executive_goal", lambda *a, **k: None
        )
        process_voice_operator_turn(
            "move report.pdf to archive", action_runner=boundary
        )

        assert boundary.action_types == ["file_move"]
        assert boundary.origins == ["voice"]

    @pytest.mark.parametrize(
        ("module", "expected"),
        [
            # 4.5I removed ``cli/ask.py`` from this list: it no longer calls
            # ``handle_file_command`` itself. It states ``origin="direct"`` on
            # the ``RequestContext`` instead, and the composition adapter
            # forwards that to the file handler. Asserted just below.
            ("cli/chat_cmd.py", ["direct", "direct", "direct"]),
            # D-5: the HTTP chat surface states "api", not "direct".
            ("server/routes.py", ["api"]),
            ("voice/assistant.py", ["voice"]),
        ],
    )
    def test_every_call_site_states_its_provenance(self, module, expected):
        """Behind a click command, a REPL and FastAPI plumbing; what would
        regress here is the argument, so the argument is what is pinned."""
        assert _call_site_origins(module) == expected

    def test_ask_states_its_provenance_on_the_request_context(self):
        """``ask``'s provenance moved, it did not disappear.

        It no longer calls ``handle_file_command`` directly, so the static
        argument check above no longer applies to it. What replaced that is a
        ``RequestContext`` carrying an explicit origin, which the composition
        adapter forwards to the file handler -- pinned end to end in
        ``tests/cli/test_ask_dispatcher_wiring.py`` and
        ``tests/cli/test_ask_output_parity.py``.
        """
        source = (SRC / "cli" / "ask.py").read_text(encoding="utf-8")

        assert "handle_file_command(" not in source
        assert 'origin="direct"' in source
        assert "RequestContext(" in source

    def test_no_surface_wires_the_actuator_itself(self):
        """One place knows the concrete runner. Four would be four places to
        fix, and four chances to differ."""
        for module in (
            "cli/ask.py",
            "cli/chat_cmd.py",
            "server/routes.py",
            "voice/assistant.py",
            "file_assistant.py",
        ):
            source = (SRC / module).read_text(encoding="utf-8")
            assert "mutation_runner" not in source, module


# ---------------------------------------------------------------------------
# The compatibility contract composition must not disturb
# ---------------------------------------------------------------------------


class TestDirectCapabilityCallersAreUntouched:
    @pytest.mark.parametrize(("command", "_action_type"), ROUTED)
    def test_a_runner_free_executor_still_mutates_directly(
        self, command, _action_type, confined_roots
    ):
        from grandpa.files.automation import FileAutomation

        before = sorted(p.name for p in confined_roots.iterdir())
        result = FileAutomation(roots=(confined_roots,)).handle(
            command, confirm=lambda *a: True
        )

        assert result.status == "handled"
        assert sorted(p.name for p in confined_roots.iterdir()) != before

    def test_the_default_stays_none(self):
        from grandpa.files.executor import FileExecutor

        parameter = inspect.signature(FileExecutor).parameters["mutation_runner"]

        assert parameter.default is None

    def test_the_convenience_entry_point_stays_runner_free(self, confined_roots):
        """``handle_file_automation`` is a capability-level convenience and
        stays one; production reaches the boundary through composition."""
        from grandpa.files import handle_file_automation

        result = handle_file_automation(
            "create file fresh.txt", roots=(confined_roots,)
        )

        assert result.status == "handled"
        assert (confined_roots / "fresh.txt").exists()

    def test_the_public_file_signatures_are_unchanged(self):
        from grandpa.files.automation import FileAutomation, handle_file_automation

        assert list(inspect.signature(FileAutomation).parameters) == [
            "roots",
            "parser",
            "executor",
            "opener",
        ]
        assert list(inspect.signature(handle_file_automation).parameters) == [
            "text",
            "roots",
            "confirm",
            "opener",
        ]
