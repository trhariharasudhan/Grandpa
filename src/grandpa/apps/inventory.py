"""Bounded Windows application inventory for Voice Operator Mode."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_APP_INVENTORY_PATH = DEFAULT_CONFIG_DIR / "app_inventory.json"
SAFE_LAUNCH_SUFFIXES = {".exe", ".lnk"}
MAX_DISCOVERED_APPS = 2_000


@dataclass(frozen=True)
class AppInventoryRecord:
    display_name: str
    normalized_name: str
    launch_target: str
    source: str
    aliases: tuple[str, ...]
    last_seen_at: float

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["aliases"] = list(self.aliases)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppInventoryRecord":
        return cls(
            display_name=str(data.get("display_name") or ""),
            normalized_name=str(data.get("normalized_name") or normalize_app_name(str(data.get("display_name") or ""))),
            launch_target=str(data.get("launch_target") or ""),
            source=str(data.get("source") or "unknown"),
            aliases=tuple(str(item) for item in data.get("aliases", ()) if str(item).strip()),
            last_seen_at=float(data.get("last_seen_at") or 0.0),
        )


@dataclass(frozen=True)
class AppFindResult:
    status: str
    matches: tuple[AppInventoryRecord, ...]
    message: str


def normalize_app_name(value: str) -> str:
    cleaned = Path(value).stem if value.lower().endswith((".exe", ".lnk")) else value
    cleaned = cleaned.replace("_", " ").replace("-", " ").strip().lower()
    for suffix in (" shortcut",):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    return " ".join(cleaned.split())


def scan_app_inventory(
    *,
    start_menu_roots: list[Path] | None = None,
    install_roots: list[Path] | None = None,
    store_path: Path = DEFAULT_APP_INVENTORY_PATH,
) -> list[AppInventoryRecord]:
    records: dict[str, AppInventoryRecord] = {}
    for path in _iter_safe_app_targets(start_menu_roots or default_start_menu_roots(), "*.lnk", "start_menu"):
        _add_record(records, path, "start_menu")
    for root in install_roots or default_install_roots():
        for pattern in ("*.exe",):
            for path in _iter_safe_app_targets([root], pattern, "install_path"):
                if _looks_like_uninstaller(path):
                    continue
                _add_record(records, path, "install_path")
                if len(records) >= MAX_DISCOVERED_APPS:
                    break
            if len(records) >= MAX_DISCOVERED_APPS:
                break
        if len(records) >= MAX_DISCOVERED_APPS:
            break
    for record in _records_from_windows_resolver():
        records.setdefault(record.normalized_name, record)
    apps = sorted(records.values(), key=lambda item: item.normalized_name)
    save_inventory(apps, store_path=store_path)
    return apps


def list_apps(*, store_path: Path = DEFAULT_APP_INVENTORY_PATH) -> list[AppInventoryRecord]:
    if not store_path.exists():
        return []
    try:
        data = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_apps = data.get("apps", data if isinstance(data, list) else [])
    if not isinstance(raw_apps, list):
        return []
    return [AppInventoryRecord.from_dict(item) for item in raw_apps if isinstance(item, dict)]


def save_inventory(apps: list[AppInventoryRecord], *, store_path: Path = DEFAULT_APP_INVENTORY_PATH) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": time.time(), "apps": [app.to_dict() for app in apps]}
    store_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def find_app(name: str, *, store_path: Path = DEFAULT_APP_INVENTORY_PATH) -> AppFindResult:
    query = normalize_app_name(name)
    if not query:
        return AppFindResult("missing", (), "Tell me which app to find.")
    apps = list_apps(store_path=store_path)
    exact = [app for app in apps if query == app.normalized_name or query in app.aliases]
    if len(exact) == 1:
        return AppFindResult("found", (exact[0],), f"Found {exact[0].display_name}.")
    if len(exact) > 1:
        return AppFindResult("ambiguous", tuple(exact), _ambiguous_message(exact))
    contains = [app for app in apps if query in app.normalized_name or any(query in alias for alias in app.aliases)]
    if len(contains) == 1:
        return AppFindResult("found", (contains[0],), f"Found {contains[0].display_name}.")
    if len(contains) > 1:
        return AppFindResult("ambiguous", tuple(contains[:8]), _ambiguous_message(contains[:8]))
    return AppFindResult("missing", (), f"I could not find an installed app named {name}. Try `grandpa apps scan`.")


def launch_inventory_app(record: AppInventoryRecord) -> str:
    target = Path(record.launch_target)
    if not _is_safe_launch_target(target):
        raise ValueError("dangerous_launch_target")
    if target.suffix.lower() == ".exe":
        subprocess.Popen([str(target)], shell=False)  # noqa: S603
    else:
        os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606
    return f"Opening {record.display_name}."


def default_start_menu_roots() -> list[Path]:
    return [
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
        Path(os.environ.get("AppData", "")) / r"Microsoft\Windows\Start Menu\Programs",
    ]


def default_install_roots() -> list[Path]:
    return [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    ]


def _iter_safe_app_targets(roots: list[Path], pattern: str, source: str):
    count = 0
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        try:
            iterator = root.rglob(pattern)
            for path in iterator:
                if count >= MAX_DISCOVERED_APPS:
                    return
                if path.is_file() and _is_safe_launch_target(path):
                    count += 1
                    yield path
        except OSError:
            continue


def _add_record(records: dict[str, AppInventoryRecord], path: Path, source: str) -> None:
    display_name = _display_name_from_target(path)
    normalized = normalize_app_name(display_name)
    if not normalized or normalized in records:
        return
    records[normalized] = AppInventoryRecord(
        display_name=display_name,
        normalized_name=normalized,
        launch_target=str(path),
        source=source,
        aliases=_aliases_for(display_name, normalized),
        last_seen_at=time.time(),
    )


def _records_from_windows_resolver() -> list[AppInventoryRecord]:
    try:
        from grandpa.windows_app_resolver import list_installed_apps
    except Exception:
        return []
    records: list[AppInventoryRecord] = []
    for item in list_installed_apps(refresh=True):
        target = Path(str(item.get("launch_target") or ""))
        if item.get("status") != "found" or not _is_safe_launch_target(target):
            continue
        display_name = str(item.get("display_name") or target.stem)
        normalized = normalize_app_name(display_name)
        records.append(
            AppInventoryRecord(
                display_name=display_name,
                normalized_name=normalized,
                launch_target=str(target),
                source=f"resolver:{item.get('source') or 'unknown'}",
                aliases=_aliases_for(display_name, normalized),
                last_seen_at=time.time(),
            )
        )
    return records


def _display_name_from_target(path: Path) -> str:
    name = path.stem
    replacements = {
        "chrome": "Chrome",
        "msedge": "Microsoft Edge",
        "code": "VS Code",
        "calc": "Calculator",
        "notepad": "Notepad",
    }
    return replacements.get(name.lower(), name.replace("_", " ").replace("-", " ").strip())


def _aliases_for(display_name: str, normalized: str) -> tuple[str, ...]:
    aliases = {normalized}
    lower = display_name.lower()
    if "visual studio code" in lower or normalized in {"code", "vs code"}:
        aliases.update({"vscode", "vs code", "visual studio code", "code"})
    if normalized == "chrome":
        aliases.add("google chrome")
    if normalized == "microsoft edge":
        aliases.add("edge")
    return tuple(sorted(aliases))


def _looks_like_uninstaller(path: Path) -> bool:
    name = normalize_app_name(path.name)
    return any(token in name for token in ("uninstall", "setup", "installer", "update helper"))


def _is_safe_launch_target(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix not in SAFE_LAUNCH_SUFFIXES:
        return False
    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts & {".ssh", "system volume information", "$recycle.bin"}:
        return False
    return True


def _ambiguous_message(matches: list[AppInventoryRecord]) -> str:
    names = ", ".join(app.display_name for app in matches[:8])
    return f"I found multiple apps: {names}. Which one should I open?"


__all__ = [
    "AppFindResult",
    "AppInventoryRecord",
    "DEFAULT_APP_INVENTORY_PATH",
    "find_app",
    "launch_inventory_app",
    "list_apps",
    "normalize_app_name",
    "scan_app_inventory",
]
