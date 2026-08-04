"""Windows sign-in startup integration for Grandpa."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

ENTRY_FILENAME = "GrandpaAssistant-startup.cmd"
ENTRY_MARKER = ":: GrandpaAssistant startup entry"


@dataclass(frozen=True)
class StartupResult:
    ok: bool
    status: str
    message: str
    entry_path: Path | None = None
    command: list[str] | None = None
    stale: bool = False
    unsupported: bool = False
    error: str | None = None


def startup_command(python_executable: str | Path | None = None) -> list[str]:
    """Return the backend/background command launched at Windows sign-in."""

    executable = str(python_executable or sys.executable)
    return [executable, "-m", "grandpa.cli", "start"]


def get_startup_entry_path(startup_dir: Path | str | None = None) -> Path:
    """Return Grandpa's owned current-user Startup entry path."""

    return _startup_dir(startup_dir) / ENTRY_FILENAME


def enable_startup(
    *,
    startup_dir: Path | str | None = None,
    python_executable: str | Path | None = None,
    platform: str | None = None,
) -> StartupResult:
    """Create or refresh Grandpa's current-user Windows startup entry."""

    if not _is_windows(platform):
        return _unsupported_result()
    entry_path = get_startup_entry_path(startup_dir)
    command = startup_command(python_executable)
    try:
        if entry_path.exists() and not _is_owned_entry(entry_path):
            return StartupResult(
                False,
                "blocked",
                "A non-Grandpa file already exists at the startup entry path.",
                entry_path=entry_path,
                command=command,
                error="Refusing to overwrite unrelated Startup folder file.",
            )
        content = _launcher_content(command)
        if entry_path.exists() and entry_path.read_text(encoding="utf-8") == content:
            return StartupResult(
                True,
                "enabled",
                "Grandpa startup is already enabled.",
                entry_path=entry_path,
                command=command,
            )
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        entry_path.write_text(content, encoding="utf-8", newline="\r\n")
        return StartupResult(
            True,
            "enabled",
            "Grandpa startup enabled.",
            entry_path=entry_path,
            command=command,
        )
    except OSError as exc:
        return StartupResult(
            False,
            "failed",
            "Could not write Grandpa startup entry. Check Startup folder permissions.",
            entry_path=entry_path,
            command=command,
            error=str(exc),
        )


def disable_startup(
    *,
    startup_dir: Path | str | None = None,
    platform: str | None = None,
) -> StartupResult:
    """Remove Grandpa's current-user Windows startup entry if present."""

    if not _is_windows(platform):
        return _unsupported_result()
    entry_path = get_startup_entry_path(startup_dir)
    try:
        if not entry_path.exists():
            return StartupResult(
                True,
                "disabled",
                "Grandpa startup is already disabled.",
                entry_path=entry_path,
            )
        if not _is_owned_entry(entry_path):
            return StartupResult(
                False,
                "blocked",
                "Startup entry exists but is not owned by Grandpa.",
                entry_path=entry_path,
                error="Refusing to remove unrelated Startup folder file.",
            )
        entry_path.unlink()
        return StartupResult(
            True, "disabled", "Grandpa startup disabled.", entry_path=entry_path
        )
    except OSError as exc:
        return StartupResult(
            False,
            "failed",
            "Could not remove Grandpa startup entry. Check Startup folder permissions.",
            entry_path=entry_path,
            error=str(exc),
        )


def startup_status(
    *,
    startup_dir: Path | str | None = None,
    python_executable: str | Path | None = None,
    platform: str | None = None,
) -> StartupResult:
    """Inspect Grandpa's Windows startup entry without changing it."""

    if not _is_windows(platform):
        return _unsupported_result()
    entry_path = get_startup_entry_path(startup_dir)
    command = startup_command(python_executable)
    try:
        if not entry_path.exists():
            return StartupResult(
                True,
                "disabled",
                "Grandpa startup is disabled.",
                entry_path=entry_path,
                command=command,
            )
        if not _is_owned_entry(entry_path):
            return StartupResult(
                False,
                "blocked",
                "Startup entry path is occupied by a non-Grandpa file.",
                entry_path=entry_path,
                command=command,
                error="Refusing to manage unrelated Startup folder file.",
            )
        stale = _is_stale_entry(entry_path)
        if stale:
            return StartupResult(
                True,
                "enabled_stale",
                "Grandpa startup is enabled, but the launcher points to a missing executable.",
                entry_path=entry_path,
                command=command,
                stale=True,
            )
        return StartupResult(
            True,
            "enabled",
            "Grandpa startup is enabled.",
            entry_path=entry_path,
            command=command,
        )
    except OSError as exc:
        return StartupResult(
            False,
            "failed",
            "Could not inspect Grandpa startup entry. Check Startup folder permissions.",
            entry_path=entry_path,
            command=command,
            error=str(exc),
        )


def _is_windows(platform: str | None = None) -> bool:
    return (platform or sys.platform) == "win32"


def _unsupported_result() -> StartupResult:
    return StartupResult(
        False,
        "unsupported",
        "Windows startup integration is only supported on Windows.",
        unsupported=True,
    )


def _startup_dir(startup_dir: Path | str | None = None) -> Path:
    if startup_dir is not None:
        return Path(startup_dir)
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise OSError("APPDATA is not set; cannot locate the Windows Startup folder.")
    return (
        Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    )


def _launcher_content(command: list[str]) -> str:
    executable = _cmd_quote(command[0])
    args = " ".join(_cmd_quote(part) for part in command[1:])
    return (
        "@echo off\n"
        f"{ENTRY_MARKER}\n"
        "setlocal\n"
        f"if not exist {executable} exit /b 1\n"
        f'start "" /min {executable} {args}\n'
        "endlocal\n"
    )


def _cmd_quote(value: str) -> str:
    escaped = str(value).replace('"', '""')
    return f'"{escaped}"'


def _is_owned_entry(entry_path: Path) -> bool:
    try:
        return ENTRY_MARKER in entry_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def _is_stale_entry(entry_path: Path) -> bool:
    try:
        for line in entry_path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
            stripped = line.strip()
            if stripped.startswith("if not exist "):
                raw = (
                    stripped.removeprefix("if not exist ")
                    .removesuffix(" exit /b 1")
                    .strip()
                )
                executable = (
                    raw[1:-1].replace('""', '"')
                    if raw.startswith('"') and raw.endswith('"')
                    else raw
                )
                return not Path(executable).exists()
    except OSError:
        return True
    return False


__all__ = [
    "ENTRY_FILENAME",
    "ENTRY_MARKER",
    "StartupResult",
    "disable_startup",
    "enable_startup",
    "get_startup_entry_path",
    "startup_command",
    "startup_status",
]
