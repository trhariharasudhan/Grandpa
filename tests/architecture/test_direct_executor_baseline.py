from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).with_name("direct_executor_baseline.json")
IMPORT_CATEGORIES = (
    "pc_control",
    "local_actions",
    "tool_executor",
    "legacy_action_router",
)


def _current_direct_imports() -> dict[str, set[str]]:
    current = {name: set() for name in IMPORT_CATEGORIES}
    for path in (ROOT / "src" / "grandpa").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        relative = path.relative_to(ROOT).as_posix()
        categories: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = {alias.name for alias in node.names}
                if "grandpa.pc_control" in modules:
                    categories.add("pc_control")
                if "grandpa.local_actions" in modules:
                    categories.add("local_actions")
                if "grandpa.actions.router" in modules:
                    categories.add("legacy_action_router")
            elif isinstance(node, ast.ImportFrom):
                names = {alias.name for alias in node.names}
                if node.module == "grandpa" and "pc_control" in names:
                    categories.add("pc_control")
                if node.module == "grandpa.pc_control":
                    categories.add("pc_control")
                if node.module == "grandpa.local_actions":
                    categories.add("local_actions")
                if node.module == "grandpa.tools._stubs" and "ToolExecutor" in names:
                    categories.add("tool_executor")
                if node.module == "grandpa.actions.router":
                    categories.add("legacy_action_router")
        for category in categories:
            current[category].add(relative)
    return current


def test_legacy_direct_executor_imports_do_not_exceed_phase1_baseline():
    baseline = {
        name: set(paths)
        for name, paths in json.loads(BASELINE_PATH.read_text(encoding="utf-8")).items()
    }
    current = _current_direct_imports()

    unexpected = {
        name: sorted(current[name] - baseline[name])
        for name in IMPORT_CATEGORIES
        if current[name] - baseline[name]
    }

    assert not unexpected, (
        f"New direct executor imports bypass the kernel: {unexpected}"
    )
    assert sum(map(len, current.values())) <= sum(map(len, baseline.values()))
