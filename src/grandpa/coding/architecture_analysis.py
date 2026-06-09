"""Read-only architecture shape analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from grandpa.coding.project_scanner import ROOT

ARCHITECTURE_LAYERS = {
    "service_layer": ("src/grandpa/services", "src/grandpa/server", "services"),
    "agent_layer": ("src/grandpa/agents", "src/grandpa/planner", "src/grandpa/mcp"),
    "api_layer": ("src/grandpa/server", "frontend/src/lib/api.ts"),
    "plugin_layer": ("src/grandpa/plugins", "plugins"),
    "skill_layer": ("src/grandpa/skills", "src/grandpa/skill_builder"),
    "desktop_layer": ("src/grandpa/desktop",),
    "browser_layer": ("src/grandpa/browser", "browser-extension"),
    "memory_layer": ("src/grandpa/memory", "src/grandpa/memory_context.py"),
}


def analyze_architecture(path: str | Path | None = None) -> dict[str, Any]:
    root = Path(path or ROOT).resolve()
    folders = _folder_structure(root)
    layers = []
    for name, candidates in ARCHITECTURE_LAYERS.items():
        evidence = [candidate for candidate in candidates if (root / candidate).exists()]
        layers.append(
            {
                "name": name,
                "present": bool(evidence),
                "evidence": evidence,
            }
        )
    return {
        "path": str(root),
        "folder_structure": folders,
        "layers": layers,
        "present_layers": [item["name"] for item in layers if item["present"]],
        "missing_layers": [item["name"] for item in layers if not item["present"]],
        "read_only": True,
    }


def _folder_structure(root: Path) -> list[dict[str, Any]]:
    rows = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if child.name.startswith(".") and child.name not in {".github"}:
            continue
        if child.is_dir():
            rows.append({"name": child.name, "type": "directory", "path": str(child)})
        elif child.name in {"pyproject.toml", "package.json", "Cargo.toml", "pubspec.yaml", "README.md"}:
            rows.append({"name": child.name, "type": "file", "path": str(child)})
    return rows[:80]


__all__ = ["ARCHITECTURE_LAYERS", "analyze_architecture"]
