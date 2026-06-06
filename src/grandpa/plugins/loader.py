"""Plugin discovery and manifest-backed skill registration."""

from __future__ import annotations

import os
from pathlib import Path
from threading import RLock
from typing import Any

from grandpa.plugins.manifests import PluginManifest, load_manifest
from grandpa.plugins.registry import is_plugin_enabled, set_plugin_enabled
from grandpa.plugins.sandbox import validate_plugin_safety
from grandpa.skills.runtime import RuntimeSkill, SkillExecutionContext, SkillResult

_LOCK = RLock()
_PLUGIN_SKILLS: dict[str, list[str]] = {}
_LAST_DISCOVERY: list[PluginManifest] = []


def plugin_roots() -> list[Path]:
    configured = os.environ.get("GRANDPA_PLUGIN_PATH")
    roots = [Path("plugins/builtins"), Path("plugins/user")]
    if configured:
        roots.extend(Path(item) for item in configured.split(os.pathsep) if item.strip())
    return [path.resolve() for path in roots]


def discover_plugins() -> list[PluginManifest]:
    manifests: list[PluginManifest] = []
    seen: set[str] = set()
    for root in plugin_roots():
        if not root.exists():
            continue
        for manifest_path in sorted(root.glob("*/plugin.json")):
            manifest = load_manifest(manifest_path)
            if manifest.name in seen:
                manifests.append(
                    PluginManifest(
                        name=manifest.name,
                        version=manifest.version,
                        description=manifest.description,
                        permissions=manifest.permissions,
                        skills=manifest.skills,
                        path=manifest.path,
                        enabled_by_default=False,
                        error="Duplicate plugin name.",
                    )
                )
                continue
            seen.add(manifest.name)
            manifests.append(manifest)
    with _LOCK:
        _LAST_DISCOVERY.clear()
        _LAST_DISCOVERY.extend(manifests)
    return manifests


def load_enabled_plugins(*, force: bool = False) -> dict[str, Any]:
    """Register enabled, valid plugin skills with the central skill runtime."""
    from grandpa.skills.registry import register_skill
    from grandpa.skills.registry.core import unregister_skill

    with _LOCK:
        if force:
            for skill_names in _PLUGIN_SKILLS.values():
                for skill_name in skill_names:
                    unregister_skill(skill_name)
            _PLUGIN_SKILLS.clear()

        loaded: list[str] = []
        rejected: list[dict[str, str]] = []
        for manifest in discover_plugins():
            enabled = is_plugin_enabled(manifest.name, manifest.enabled_by_default)
            safe, reason = validate_plugin_safety(manifest)
            if not enabled:
                continue
            if not safe:
                rejected.append({"name": manifest.name, "reason": reason})
                continue
            registered: list[str] = []
            for skill in manifest.skills:
                if skill.name in {name for names in _PLUGIN_SKILLS.values() for name in names}:
                    continue
                try:
                    register_skill(_runtime_skill(manifest, skill))
                    registered.append(skill.name)
                except Exception as exc:
                    rejected.append({"name": manifest.name, "reason": f"{skill.name}: {exc.__class__.__name__}"})
            if registered:
                _PLUGIN_SKILLS[manifest.name] = registered
                loaded.append(manifest.name)
        return {"loaded": loaded, "rejected": rejected, "plugin_skill_count": sum(len(v) for v in _PLUGIN_SKILLS.values())}


def list_plugins() -> list[dict[str, Any]]:
    manifests = discover_plugins()
    return [_plugin_dict(manifest) for manifest in manifests]


def get_plugin(name: str) -> dict[str, Any] | None:
    clean = name.strip().lower()
    for manifest in discover_plugins():
        if manifest.name == clean:
            return _plugin_dict(manifest)
    return None


def enable_plugin(name: str) -> dict[str, Any]:
    plugin = get_plugin(name)
    if plugin is None:
        raise KeyError(name)
    set_plugin_enabled(plugin["name"], True)
    summary = load_enabled_plugins(force=True)
    return {"plugin": get_plugin(name), "reload": summary}


def disable_plugin(name: str) -> dict[str, Any]:
    plugin = get_plugin(name)
    if plugin is None:
        raise KeyError(name)
    set_plugin_enabled(plugin["name"], False)
    summary = load_enabled_plugins(force=True)
    return {"plugin": get_plugin(name), "reload": summary}


def reload_plugins() -> dict[str, Any]:
    return load_enabled_plugins(force=True)


def plugin_diagnostics() -> dict[str, Any]:
    plugins = list_plugins()
    return {
        "status": "ready",
        "plugin_count": len(plugins),
        "enabled_count": sum(1 for item in plugins if item["enabled"]),
        "invalid_count": sum(1 for item in plugins if item["status"] == "invalid"),
        "plugin_skill_count": sum(len(item.get("skills", [])) for item in plugins if item["enabled"] and item["status"] != "invalid"),
        "plugins": plugins,
        "roots": [str(path) for path in plugin_roots()],
        "local_only": True,
        "arbitrary_code_execution": False,
    }


def _runtime_skill(manifest: PluginManifest, skill_manifest):
    def _execute(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
        data = dict(skill_manifest.data)
        data.update({"plugin": manifest.name, "plugin_version": manifest.version})
        return SkillResult(
            ok=True,
            status="completed",
            message=skill_manifest.response,
            data=data,
            risk_level=skill_manifest.risk_level,
            approval_required=skill_manifest.approval_required,
        )

    return RuntimeSkill(
        name=skill_manifest.name,
        description=skill_manifest.description,
        category=skill_manifest.category,
        risk_level=skill_manifest.risk_level,
        approval_required=skill_manifest.approval_required,
        executor=_execute,
        aliases=skill_manifest.aliases,
    )


def _plugin_dict(manifest: PluginManifest) -> dict[str, Any]:
    enabled = is_plugin_enabled(manifest.name, manifest.enabled_by_default)
    safe, reason = validate_plugin_safety(manifest)
    data = manifest.to_dict(enabled=enabled, status="enabled" if enabled else "disabled")
    if not safe:
        data["status"] = "invalid"
        data["error"] = reason
    return data


__all__ = [
    "disable_plugin",
    "discover_plugins",
    "enable_plugin",
    "get_plugin",
    "list_plugins",
    "load_enabled_plugins",
    "plugin_diagnostics",
    "plugin_roots",
    "reload_plugins",
]
