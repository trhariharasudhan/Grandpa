"""Manifest contracts for Grandpa's local plugin runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

PluginStatus = Literal["enabled", "disabled", "invalid"]
PluginSkillKind = Literal["static_response"]
PluginRiskLevel = Literal["LOW", "MEDIUM", "HIGH", "BLOCKED"]


@dataclass(frozen=True)
class PluginSkillManifest:
    """Declarative skill exposed by a plugin package."""

    name: str
    description: str
    category: str
    risk_level: PluginRiskLevel = "LOW"
    approval_required: bool = False
    aliases: tuple[str, ...] = ()
    kind: PluginSkillKind = "static_response"
    response: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
            "aliases": list(self.aliases),
            "kind": self.kind,
            "response": self.response,
            "data": self.data,
        }


@dataclass(frozen=True)
class PluginManifest:
    """Validated local plugin manifest."""

    name: str
    version: str
    description: str
    permissions: tuple[str, ...]
    skills: tuple[PluginSkillManifest, ...]
    path: Path
    enabled_by_default: bool = True
    error: str = ""

    def to_dict(self, *, enabled: bool | None = None, status: PluginStatus | None = None) -> dict[str, Any]:
        resolved_status: PluginStatus = status or ("enabled" if enabled else "disabled")
        if self.error:
            resolved_status = "invalid"
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "permissions": list(self.permissions),
            "skills": [skill.to_dict() for skill in self.skills],
            "path": str(self.path),
            "enabled_by_default": self.enabled_by_default,
            "enabled": bool(enabled) if enabled is not None else self.enabled_by_default,
            "status": resolved_status,
            "error": self.error,
        }


def load_manifest(path: Path) -> PluginManifest:
    """Read and validate a ``plugin.json`` file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _invalid(path, f"Manifest JSON could not be read: {exc.__class__.__name__}")

    try:
        name = _clean_name(raw.get("name"))
        version = str(raw.get("version") or "").strip()
        description = str(raw.get("description") or "").strip()
        if not name:
            raise ValueError("name is required")
        if not version:
            raise ValueError("version is required")
        if not description:
            raise ValueError("description is required")
        permissions = tuple(_clean_permission(item) for item in raw.get("permissions", []))
        if any(not item for item in permissions):
            raise ValueError("permissions must be non-empty strings")
        skills = tuple(_parse_skill(item) for item in raw.get("skills", []))
        if not skills:
            raise ValueError("at least one skill is required")
        return PluginManifest(
            name=name,
            version=version,
            description=description,
            permissions=permissions,
            skills=skills,
            path=path.parent,
            enabled_by_default=bool(raw.get("enabled_by_default", True)),
        )
    except Exception as exc:
        return _invalid(path, str(exc))


def _parse_skill(raw: Any) -> PluginSkillManifest:
    if not isinstance(raw, dict):
        raise ValueError("each skill must be an object")
    name = _clean_skill_name(raw.get("name"))
    description = str(raw.get("description") or "").strip()
    category = str(raw.get("category") or "plugin").strip().lower()
    risk = str(raw.get("risk_level") or "LOW").strip().upper()
    kind = str(raw.get("kind") or "static_response").strip()
    if not name:
        raise ValueError("skill name is required")
    if not description:
        raise ValueError(f"description is required for skill {name}")
    if risk not in {"LOW", "MEDIUM", "HIGH", "BLOCKED"}:
        raise ValueError(f"invalid risk level for skill {name}")
    if kind != "static_response":
        raise ValueError(f"unsupported skill kind for {name}: {kind}")
    if risk != "LOW" and not bool(raw.get("approval_required", False)):
        raise ValueError(f"non-low risk plugin skill {name} must require approval")
    return PluginSkillManifest(
        name=name,
        description=description,
        category=category,
        risk_level=risk,  # type: ignore[arg-type]
        approval_required=bool(raw.get("approval_required", False)),
        aliases=tuple(str(item).strip() for item in raw.get("aliases", []) if str(item).strip()),
        kind="static_response",
        response=str(raw.get("response") or f"{name} completed."),
        data=dict(raw.get("data") or {}),
    )


def _invalid(path: Path, error: str) -> PluginManifest:
    return PluginManifest(
        name=path.parent.name,
        version="0.0.0",
        description="Invalid plugin manifest.",
        permissions=(),
        skills=(),
        path=path.parent,
        enabled_by_default=False,
        error=error,
    )


def _clean_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text.replace("-", "").replace("_", "").isalnum() else ""


def _clean_skill_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    parts = text.split(".")
    if len(parts) < 2:
        return ""
    return text if all(part.replace("_", "").replace("-", "").isalnum() for part in parts) else ""


def _clean_permission(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


__all__ = ["PluginManifest", "PluginSkillManifest", "load_manifest"]
