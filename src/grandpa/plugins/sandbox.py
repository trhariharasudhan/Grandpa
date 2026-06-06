"""Safety checks for manifest-driven plugins."""

from __future__ import annotations

from grandpa.plugins.manifests import PluginManifest

_ALLOWED_PERMISSIONS = {
    "diagnostics.read",
    "skills.read",
    "memory.read",
    "browser.read",
    "desktop.read",
    "workflow.read",
}


def validate_plugin_safety(manifest: PluginManifest) -> tuple[bool, str]:
    """Validate that a plugin cannot bypass Grandpa's approval system."""
    if manifest.error:
        return False, manifest.error
    unknown = [item for item in manifest.permissions if item not in _ALLOWED_PERMISSIONS]
    if unknown:
        return False, f"Unsupported permission(s): {', '.join(unknown)}"
    for skill in manifest.skills:
        if skill.kind != "static_response":
            return False, f"Unsupported plugin skill kind: {skill.kind}"
        if skill.risk_level in {"MEDIUM", "HIGH"} and not skill.approval_required:
            return False, f"Plugin skill {skill.name} needs approval for {skill.risk_level} risk."
        if skill.risk_level == "BLOCKED":
            return False, f"Plugin skill {skill.name} is blocked by policy."
    return True, ""


__all__ = ["validate_plugin_safety"]
