"""Confidence-ranked, bounded Windows application discovery."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import replace
from pathlib import Path

from grandpa.apps.models import ApplicationInfo
from grandpa.apps.registry import DEFAULT_APP_REGISTRY_PATH, save_app_registry
from grandpa.apps.resolver import (
    canonicalize_app_identity,
    generate_aliases,
    normalize_app_name,
)
from grandpa.apps.safety import looks_like_launchable_application, looks_user_facing

logger = logging.getLogger(__name__)

MAX_DISCOVERED_APPS = 500
MAX_PROGRAM_FILES_CANDIDATES = 250

SOURCE_CONFIDENCE = {
    "start_menu": 1.0,
    "resolver": 0.95,
    "registry_app_path": 0.92,
    "registry_uninstall": 0.72,
    "program_files": 0.55,
}


def scan_app_inventory(
    *,
    start_menu_roots: list[Path] | None = None,
    install_roots: list[Path] | None = None,
    store_path: Path = DEFAULT_APP_REGISTRY_PATH,
    registry_rows: list[dict[str, str]] | None = None,
    resolver_rows: list[dict[str, str]] | None = None,
    app_path_rows: list[dict[str, str]] | None = None,
) -> list[ApplicationInfo]:
    """Scan trusted sources in priority order and persist canonical applications."""

    records: dict[str, ApplicationInfo] = {}
    path_index: dict[str, str] = {}

    selected_start_roots = (
        default_start_menu_roots() if start_menu_roots is None else start_menu_roots
    )
    selected_install_roots = (
        default_install_roots() if install_roots is None else install_roots
    )

    for path in _iter_start_menu_targets(selected_start_roots):
        _merge_record(records, path_index, _path_record(path, "start_menu"))

    trusted_rows = (
        resolver_rows if resolver_rows is not None else _windows_resolver_rows()
    )
    for row in trusted_rows:
        _merge_record(records, path_index, _row_record(row, default_source="resolver"))

    app_paths = (
        app_path_rows if app_path_rows is not None else _registry_app_path_rows()
    )
    for row in app_paths:
        _merge_record(
            records, path_index, _row_record(row, default_source="registry_app_path")
        )

    uninstall_rows = (
        registry_rows if registry_rows is not None else _registry_installed_apps()
    )
    for row in uninstall_rows:
        _merge_record(
            records, path_index, _row_record(row, default_source="registry_uninstall")
        )

    if len(records) < MAX_DISCOVERED_APPS:
        for path in _iter_program_files_candidates(selected_install_roots):
            _merge_record(records, path_index, _path_record(path, "program_files"))
            if len(records) >= MAX_DISCOVERED_APPS:
                break

    apps = sorted(records.values(), key=lambda item: item.display_name.casefold())
    save_app_registry(apps, store_path=store_path)
    logger.info(
        "Application scan completed: %s apps (%s user-facing)",
        len(apps),
        sum(app.is_user_facing for app in apps),
    )
    return apps


def default_start_menu_roots() -> list[Path]:
    return [
        Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        / r"Microsoft\Windows\Start Menu\Programs",
        Path(os.environ.get("AppData", "")) / r"Microsoft\Windows\Start Menu\Programs",
    ]


def default_install_roots() -> list[Path]:
    return [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    ]


def _iter_start_menu_targets(roots: list[Path]):
    count = 0
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*.lnk"):
                if count >= MAX_DISCOVERED_APPS:
                    return
                if path.is_file() and looks_user_facing(path, path.stem):
                    count += 1
                    yield path
        except OSError as exc:
            logger.debug("Skipping Start Menu root %s: %s", root, exc)


def _iter_program_files_candidates(roots: list[Path]):
    """Yield only shallow product-root executables; never recurse through SDK trees."""

    yielded = 0
    for root in roots:
        if not root.is_dir():
            continue
        try:
            product_dirs = [path for path in root.iterdir() if path.is_dir()]
        except OSError as exc:
            logger.debug("Skipping install root %s: %s", root, exc)
            continue
        for product_dir in product_dirs:
            if yielded >= MAX_PROGRAM_FILES_CANDIDATES:
                return
            try:
                candidates = list(product_dir.glob("*.exe"))
                # A vendor directory commonly contains one additional product level.
                for child in product_dir.iterdir():
                    if child.is_dir():
                        candidates.extend(child.glob("*.exe"))
            except OSError:
                continue
            for path in candidates:
                if yielded >= MAX_PROGRAM_FILES_CANDIDATES:
                    return
                if not _matches_product_folder(path, product_dir):
                    continue
                if looks_user_facing(path, product_dir.name):
                    yielded += 1
                    yield path


def _matches_product_folder(path: Path, product_dir: Path) -> bool:
    app_name = normalize_app_name(path.stem)
    folder_names = {
        normalize_app_name(product_dir.name),
        normalize_app_name(path.parent.name),
    }
    known_launchers = {
        "chrome",
        "msedge",
        "firefox",
        "code",
        "spotify",
        "obs64",
        "blender",
    }
    return app_name in known_launchers or any(
        folder and (app_name == folder or app_name in folder or folder in app_name)
        for folder in folder_names
    )


def _path_record(path: Path, source: str) -> ApplicationInfo | None:
    display_name = _display_name_from_target(path)
    return _make_record(display_name=display_name, target=path, source=source)


def _row_record(row: dict[str, str], *, default_source: str) -> ApplicationInfo | None:
    target = Path(
        str(row.get("path") or row.get("launch_target") or row.get("executable") or "")
    )
    display_name = str(row.get("display_name") or row.get("name") or target.stem)
    return _make_record(
        display_name=display_name,
        target=target,
        source=str(row.get("source") or default_source),
        working_directory=str(row.get("working_directory") or target.parent),
        publisher=str(row.get("publisher") or ""),
        version=str(row.get("version") or ""),
        icon_path=str(row.get("icon_path") or target),
    )


def _make_record(
    *,
    display_name: str,
    target: Path,
    source: str,
    working_directory: str = "",
    publisher: str = "",
    version: str = "",
    icon_path: str = "",
) -> ApplicationInfo | None:
    if not display_name or not looks_like_launchable_application(target):
        return None
    source_kind = _source_kind(source)
    user_facing = looks_user_facing(target, display_name)
    canonical_key = canonicalize_app_identity(display_name, target.name)
    return ApplicationInfo(
        name=normalize_app_name(display_name),
        aliases=generate_aliases(display_name, target.name),
        display_name=_canonical_display_name(display_name, canonical_key),
        path=str(target),
        working_directory=working_directory or str(target.parent),
        publisher=publisher,
        version=version,
        source=source,
        icon_path=icon_path or str(target),
        last_seen_at=time.time(),
        confidence=SOURCE_CONFIDENCE[source_kind],
        is_user_facing=user_facing,
        is_launchable=True,
        canonical_key=canonical_key,
    )


def _merge_record(
    records: dict[str, ApplicationInfo],
    path_index: dict[str, str],
    candidate: ApplicationInfo | None,
) -> None:
    if candidate is None or not candidate.canonical_key:
        return
    normalized_path = _normalized_path(candidate.path)
    key = path_index.get(normalized_path, candidate.canonical_key)
    existing = records.get(key)
    if existing is None and key != candidate.canonical_key:
        existing = records.get(candidate.canonical_key)
    if existing is None:
        records[candidate.canonical_key] = candidate
        path_index[normalized_path] = candidate.canonical_key
        return

    preferred, secondary = (
        (candidate, existing)
        if _record_rank(candidate) > _record_rank(existing)
        else (existing, candidate)
    )
    aliases = tuple(
        sorted(
            set(preferred.aliases) | set(secondary.aliases) | {preferred.canonical_key}
        )
    )
    merged = replace(
        preferred,
        aliases=aliases,
        publisher=preferred.publisher or secondary.publisher,
        version=preferred.version or secondary.version,
        icon_path=preferred.icon_path or secondary.icon_path,
        is_user_facing=preferred.is_user_facing or secondary.is_user_facing,
        is_launchable=preferred.is_launchable or secondary.is_launchable,
        last_seen_at=max(preferred.last_seen_at, secondary.last_seen_at),
    )
    old_key = next(
        (item_key for item_key, item in records.items() if item is existing), key
    )
    records.pop(old_key, None)
    records[merged.canonical_key] = merged
    path_index[_normalized_path(existing.path)] = merged.canonical_key
    path_index[normalized_path] = merged.canonical_key


def _record_rank(app: ApplicationInfo) -> tuple[float, int, int]:
    return (
        app.confidence,
        int(app.path.casefold().endswith(".lnk")),
        int(bool(app.publisher)),
    )


def _normalized_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value.strip().strip('"')))


def _source_kind(source: str) -> str:
    for kind in SOURCE_CONFIDENCE:
        if (
            source == kind
            or source.startswith(f"{kind}:")
            or (kind == "resolver" and source.startswith("resolver:"))
        ):
            return kind
    return "registry_uninstall"


def _canonical_display_name(display_name: str, canonical_key: str) -> str:
    known = {
        "google chrome": "Google Chrome",
        "microsoft edge": "Microsoft Edge",
        "visual studio code": "Visual Studio Code",
    }
    return known.get(canonical_key, display_name.strip())


def _display_name_from_target(path: Path) -> str:
    replacements = {
        "chrome": "Google Chrome",
        "msedge": "Microsoft Edge",
        "code": "Visual Studio Code",
        "calc": "Calculator",
        "mspaint": "Paint",
    }
    return replacements.get(
        path.stem.casefold(), path.stem.replace("_", " ").replace("-", " ").strip()
    )


def _registry_app_path_rows() -> list[dict[str, str]]:
    try:
        import winreg
    except ImportError:
        return []
    rows: list[dict[str, str]] = []
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, base) as parent:
                count = winreg.QueryInfoKey(parent)[0]
                for index in range(count):
                    try:
                        sub_name = winreg.EnumKey(parent, index)
                        with winreg.OpenKey(parent, sub_name) as sub_key:
                            target = _query_reg(winreg, sub_key, "")
                    except OSError:
                        continue
                    if target:
                        rows.append(
                            {
                                "display_name": Path(sub_name).stem,
                                "path": target,
                                "source": "registry_app_path",
                            }
                        )
        except OSError:
            continue
    return rows


def _registry_installed_apps() -> list[dict[str, str]]:
    try:
        import winreg
    except ImportError:
        return []
    rows: list[dict[str, str]] = []
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    bases = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    for root in roots:
        for base in bases:
            rows.extend(_read_uninstall_key(winreg, root, base))
    return rows


def _read_uninstall_key(winreg_module, root, base: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    try:
        with winreg_module.OpenKey(root, base) as parent:
            count = winreg_module.QueryInfoKey(parent)[0]
            for index in range(count):
                try:
                    sub_name = winreg_module.EnumKey(parent, index)
                    with winreg_module.OpenKey(parent, sub_name) as sub_key:
                        display_name = _query_reg(winreg_module, sub_key, "DisplayName")
                        install_location = _query_reg(
                            winreg_module, sub_key, "InstallLocation"
                        )
                        display_icon = _query_reg(winreg_module, sub_key, "DisplayIcon")
                        publisher = _query_reg(winreg_module, sub_key, "Publisher")
                        version = _query_reg(winreg_module, sub_key, "DisplayVersion")
                except OSError:
                    continue
                executable = _registry_executable(
                    display_icon, install_location, display_name
                )
                if display_name and executable:
                    rows.append(
                        {
                            "display_name": display_name,
                            "path": executable,
                            "publisher": publisher,
                            "version": version,
                            "source": "registry_uninstall",
                        }
                    )
    except OSError:
        return []
    return rows


def _query_reg(winreg_module, key, name: str) -> str:
    try:
        value, _ = winreg_module.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value or "").strip().strip('"')


def _registry_executable(
    display_icon: str, install_location: str, display_name: str
) -> str:
    if display_icon:
        candidate = display_icon.split(",", 1)[0].strip().strip('"')
        if candidate.casefold().endswith(".exe") and looks_user_facing(
            candidate, display_name
        ):
            return candidate
    if install_location:
        root = Path(install_location)
        try:
            for path in root.glob("*.exe"):
                if _matches_product_folder(path, root) and looks_user_facing(
                    path, display_name
                ):
                    return str(path)
        except OSError:
            return ""
    return ""


def _windows_resolver_rows() -> list[dict[str, str]]:
    try:
        from grandpa.windows_app_resolver import list_installed_apps
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for item in list_installed_apps(refresh=True):
        if item.get("status") != "found":
            continue
        target = str(item.get("launch_target") or "")
        rows.append(
            {
                "display_name": str(item.get("display_name") or Path(target).stem),
                "path": target,
                "source": f"resolver:{item.get('source') or 'unknown'}",
            }
        )
    return rows


__all__ = [
    "MAX_DISCOVERED_APPS",
    "MAX_PROGRAM_FILES_CANDIDATES",
    "SOURCE_CONFIDENCE",
    "default_install_roots",
    "default_start_menu_roots",
    "scan_app_inventory",
]
