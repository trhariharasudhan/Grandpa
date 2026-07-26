"""Application Manager data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ApplicationInfo:
    """A safely launchable Windows application discovered by Grandpa."""

    name: str
    aliases: tuple[str, ...]
    display_name: str
    path: str
    working_directory: str = ""
    publisher: str = ""
    version: str = ""
    source: str = "unknown"
    icon_path: str = ""
    last_seen_at: float = 0.0
    confidence: float = 1.0
    is_user_facing: bool = True
    is_launchable: bool = True
    canonical_key: str = ""

    @property
    def normalized_name(self) -> str:
        return self.name

    @property
    def launch_target(self) -> str:
        return self.path

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["aliases"] = list(self.aliases)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApplicationInfo":
        return cls(
            name=str(data.get("name") or data.get("normalized_name") or ""),
            aliases=tuple(str(item) for item in data.get("aliases", ()) if str(item).strip()),
            display_name=str(data.get("display_name") or data.get("name") or ""),
            path=str(data.get("path") or data.get("launch_target") or ""),
            working_directory=str(data.get("working_directory") or ""),
            publisher=str(data.get("publisher") or ""),
            version=str(data.get("version") or ""),
            source=str(data.get("source") or "unknown"),
            icon_path=str(data.get("icon_path") or ""),
            last_seen_at=float(data.get("last_seen_at") or data.get("discovered_at") or 0.0),
            confidence=float(data.get("confidence", 1.0)),
            is_user_facing=bool(data.get("is_user_facing", True)),
            is_launchable=bool(data.get("is_launchable", True)),
            canonical_key=str(data.get("canonical_key") or data.get("name") or ""),
        )


@dataclass(frozen=True)
class AppResolveResult:
    """Result from matching user text to indexed applications."""

    status: str
    matches: tuple[ApplicationInfo, ...]
    message: str
    score: float = 0.0


@dataclass(frozen=True)
class AppProcessInfo:
    """A running application/process row."""

    pid: int
    name: str
    display_name: str = ""
    executable: str = ""
    process_count: int = 1


__all__ = ["AppProcessInfo", "AppResolveResult", "ApplicationInfo"]
