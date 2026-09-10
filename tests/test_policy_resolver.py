"""The resolver port, before anything is plugged into it.

``AppTargetResolver`` is the one question policy needs to ask the outside
world: what does this target name refer to? It is a ``typing.Protocol`` with a
single method, and no implementation exists yet -- the inventory, the alias
tables and the Windows resolver already answer this question, and a later slice
injects one of them.

These tests hold three things: that a fake can satisfy the port without
inheriting from it, that the port itself performs no I/O and pulls in nothing
that could, and that this slice remains inert -- no production caller, and the
saturated importer baseline untouched.

Structural typing is checked the way structural typing is meant to be: by
binding a fake to a protocol-annotated parameter and calling it. The protocol
is not ``runtime_checkable``, matching ``kernel/interfaces.py`` and
``jarvis/voice_input.py``; ``isinstance`` against a Protocol only checks that
method *names* exist, which would be a weaker claim than the one made here.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import get_type_hints

from grandpa.policy.models import CanonicalTarget
from grandpa.policy.resolver import AppTargetResolver

RESOLVER_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "grandpa" / "policy" / "resolver.py"
)
POLICY_DIR = Path(__file__).resolve().parents[1] / "src" / "grandpa" / "policy"


class FakeResolver:
    """A resolver that knows two names and nothing else.

    Does not inherit from ``AppTargetResolver`` -- that is the point of a
    structural port.
    """

    def __init__(self, known: dict[str, CanonicalTarget] | None = None) -> None:
        self.known = known or {}
        self.calls: list[str] = []

    def resolve(self, raw_target: str) -> CanonicalTarget:
        self.calls.append(raw_target)
        return self.known.get(raw_target, CanonicalTarget(raw=raw_target))


def _resolve_through_the_port(
    resolver: AppTargetResolver, raw_target: str
) -> CanonicalTarget:
    """Bind a resolver to the port and use it, so conformance is exercised
    rather than asserted."""
    return resolver.resolve(raw_target)


# ---------------------------------------------------------------------------
# The port exists and can be satisfied
# ---------------------------------------------------------------------------


class TestThePortIsUsable:
    def test_it_is_importable(self):
        from grandpa.policy import AppTargetResolver as exported

        assert exported is AppTargetResolver

    def test_a_fake_satisfies_it_without_inheriting(self):
        fake = FakeResolver()

        assert AppTargetResolver not in type(fake).__mro__

        result = _resolve_through_the_port(fake, "wsl")

        assert isinstance(result, CanonicalTarget)

    def test_it_asks_exactly_one_question(self):
        """A port that mirrored the inventory's scoring, match lists and store
        paths would have to change whenever the inventory did."""
        methods = [
            name
            for name in vars(AppTargetResolver)
            if not name.startswith("_") and callable(vars(AppTargetResolver)[name])
        ]

        assert methods == ["resolve"]

    def test_the_signature_is_raw_string_in_canonical_target_out(self):
        hints = get_type_hints(AppTargetResolver.resolve)

        assert hints["raw_target"] is str
        assert hints["return"] is CanonicalTarget


# ---------------------------------------------------------------------------
# Both outcomes flow through it
# ---------------------------------------------------------------------------


class TestBothOutcomesFlowThrough:
    def test_an_unresolved_target_comes_back_unresolved(self):
        """A missing or unreadable inventory is an ordinary condition, not an
        error: the request stays classifiable by today's rules."""
        fake = FakeResolver()

        result = _resolve_through_the_port(fake, "no-such-app")

        assert result.resolved is False
        assert result.raw == "no-such-app"
        assert result.app_id is None

    def test_a_resolved_target_carries_the_identity(self):
        resolved = CanonicalTarget(
            raw="wsl",
            app_id="wsl",
            display_name="WSL",
            executable="wsl.exe",
            launch_path="C:/x/WSL.lnk",
            source="inventory",
        )
        fake = FakeResolver({"wsl": resolved})

        result = _resolve_through_the_port(fake, "wsl")

        assert result.resolved is True
        assert result.display_name == "WSL"
        assert result.launch_path.endswith("WSL.lnk")

    def test_the_raw_words_survive_resolution(self):
        """A decision needs the resolved identity; an audit record needs what
        the user actually said."""
        fake = FakeResolver(
            {"wsl": CanonicalTarget(raw="wsl", display_name="WSL", source="inventory")}
        )

        assert _resolve_through_the_port(fake, "wsl").raw == "wsl"

    def test_an_alias_resolution_is_distinguishable_from_an_inventory_one(self):
        """A later step may want to treat a curated alias and a fuzzy inventory
        match differently."""
        alias = CanonicalTarget(raw="wt", app_id="terminal", source="alias")
        inventory = CanonicalTarget(raw="wsl", app_id="wsl", source="inventory")

        assert alias.source != inventory.source
        assert alias.resolved and inventory.resolved

    def test_the_port_is_deterministic_for_the_same_input(self):
        """A tier decided against one identity and an action taken against
        another is the bug this port exists to prevent."""
        fake = FakeResolver(
            {"wsl": CanonicalTarget(raw="wsl", app_id="wsl", source="inventory")}
        )

        first = _resolve_through_the_port(fake, "wsl")
        second = _resolve_through_the_port(fake, "wsl")

        assert first == second


# ---------------------------------------------------------------------------
# It does nothing
# ---------------------------------------------------------------------------


class TestThePortPerformsNoIO:
    @staticmethod
    def _imported_modules(path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        return modules

    def test_it_imports_nothing_that_could_perform_io(self):
        forbidden = {
            "os",
            "io",
            "pathlib",
            "sqlite3",
            "json",
            "subprocess",
            "shutil",
            "socket",
            "winreg",
        }

        assert not (self._imported_modules(RESOLVER_PATH) & forbidden)

    def test_it_imports_only_typing_and_the_policy_models(self):
        assert self._imported_modules(RESOLVER_PATH) == {
            "__future__",
            "typing",
            "grandpa.policy.models",
        }

    def test_the_protocol_body_is_only_a_declaration(self):
        """A Protocol method with a body is an implementation waiting to be
        called by accident."""
        tree = ast.parse(RESOLVER_PATH.read_text(encoding="utf-8"))
        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "resolve"
        )
        body = list(method.body)
        # Drop the docstring only. ``...`` is itself an Expr(Constant), so a
        # filter for "not a constant expression" removes both and proves
        # nothing -- which is exactly what the first draft of this test did.
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]

        assert len(body) == 1
        assert isinstance(body[0], ast.Expr)
        assert isinstance(body[0].value, ast.Constant)
        assert body[0].value.value is Ellipsis

    def test_no_module_in_the_package_reaches_a_database(self):
        """Not just this file: the whole package must stay importable without
        opening anything."""
        for path in POLICY_DIR.glob("*.py"):
            modules = self._imported_modules(path)
            assert "sqlite3" not in modules, path.name
            assert not any(m.startswith("grandpa.apps") for m in modules), path.name


# ---------------------------------------------------------------------------
# Dependency direction, and nothing moved
# ---------------------------------------------------------------------------


class TestNothingElseChanged:
    @staticmethod
    def _imported_modules(path: Path) -> set[str]:
        return TestThePortPerformsNoIO._imported_modules(path)

    def test_no_policy_module_imports_pc_control_or_local_actions(self):
        for path in POLICY_DIR.glob("*.py"):
            modules = self._imported_modules(path)
            assert not any("pc_control" in module for module in modules), path.name
            assert not any("local_actions" in module for module in modules), path.name

    def test_the_baseline_guard_total_is_53(self):
        """51 while every file entry surface still bypassed the boundary;
        52 once the composition layer that ended that arrived. It is the
        one approved addition, and ``tests/test_file_composition.py`` pins
        which module it is."""
        baseline = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "tests"
                / "architecture"
                / "direct_executor_baseline.json"
            ).read_text(encoding="utf-8")
        )

        # 53 since 4.5H-3: ``composition/ask_handlers.py`` is the approved
        # application-level composition consumer of ``local_actions``,
        # added for the ask.py dispatcher migration. Still an exact count,
        # so any further importer has to come past this line.
        assert sum(len(paths) for paths in baseline.values()) == 53
        assert "src/grandpa/composition/files.py" in baseline["pc_control"]

    def test_only_the_intended_modules_import_the_new_package(self):
        """``pc_control`` delegates classification here,
        ``files/executor.py`` names the mutation seam here, and
        ``composition/files.py`` names the same seam to type the runner it
        injects. ``dispatch/context.py`` takes the ``ActionOrigin`` vocabulary
        and nothing else, because ``RequestContext`` requires a provenance it
        refuses to default. The eight ``desktop/control/`` services were added
        by AD-028.1 and take models only; ``tests/test_policy_models.py`` holds
        the rationale. ``desktop/kernel/risk.py`` was added with the §4.11
        approval-predicate extraction, is authorised by AD-028.2, and is the
        one entry that takes policy *behaviour* rather than vocabulary; the
        same file holds why. The resolver port itself
        still has no caller at all -- which the second half checks, and which
        is why the two are asserted separately."""
        root = Path(__file__).resolve().parents[1] / "src" / "grandpa"
        importers = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if "grandpa.policy" in path.read_text(encoding="utf-8")
            and path.parent.name != "policy"
        )

        assert importers == [
            "composition/files.py",
            "desktop/control/applications.py",
            "desktop/control/automation.py",
            "desktop/control/clipboard.py",
            "desktop/control/diagnostics.py",
            "desktop/control/files.py",
            "desktop/control/monitors.py",
            "desktop/control/power.py",
            "desktop/control/windows.py",
            "desktop/kernel/risk.py",
            "dispatch/context.py",
            "files/executor.py",
            "pc_control.py",
        ]

        resolver_callers = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if "policy.resolver" in path.read_text(encoding="utf-8")
            and path.parent.name != "policy"
        ]

        assert resolver_callers == []

    def test_the_live_safety_contracts_are_unchanged(self):
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
        assert set(BLOCKED_EXECUTABLE_NAMES) == {
            "cmd.exe",
            "powershell.exe",
            "pwsh.exe",
            "regedit.exe",
            "diskpart.exe",
        }

    def test_the_existing_resolvers_are_untouched(self):
        """The port describes what they already do; it does not change them."""
        from grandpa.apps.models import AppResolveResult
        from grandpa.apps.resolver import resolve_app

        assert [f for f in AppResolveResult.__dataclass_fields__] == [
            "status",
            "matches",
            "message",
            "score",
        ]
        assert resolve_app("", []).status == "missing"
