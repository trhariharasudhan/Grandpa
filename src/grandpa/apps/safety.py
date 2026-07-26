"""Safety policy for application discovery and launching."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

SAFE_LAUNCH_SUFFIXES = {".exe", ".lnk"}
BLOCKED_EXECUTABLE_NAMES = {
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "regedit.exe",
    "diskpart.exe",
}
NOISY_EXECUTABLE_TOKENS = (
    "uninstall",
    "unins",
    "setup",
    "installer",
    "update",
    "updater",
    "crash",
    "helper",
    "service",
    "broker",
    "elevat",
    "testhost",
    "vstest",
    "proxy",
    "webview",
    "symbolizer",
    "makeappx",
    "signtool",
    "mspdbsrv",
    "vboxsvc",
    "vboxmanage",
    "sha256sum",
    "crashpad",
    "telemetry",
    "diagnostic",
    "runtime",
    "hostfxr",
    "application verifier",
    "administrative tools",
    "command prompt",
    "developer command",
    "sdk tool",
)
TECHNICAL_EXECUTABLE_NAMES = {
    "7z.exe",
    "7za.exe",
    "conhost.exe",
    "fontdrvhost.exe",
    "mkdir.exe",
    "rm.exe",
    "taskkill.exe",
    "vstest.console.exe",
}
CRITICAL_PROCESS_NAMES = {
    "explorer.exe",
    "winlogon.exe",
    "csrss.exe",
    "lsass.exe",
    "services.exe",
    "smss.exe",
    "svchost.exe",
    "system",
    "system idle process",
    "registry",
    "dwm.exe",
    "wininit.exe",
    "fontdrvhost.exe",
    "conhost.exe",
    "runtimebroker.exe",
    "wudfhost.exe",
    "applicationframehost.exe",
    "textinputhost.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
    "searchhost.exe",
}
PROTECTED_PARTS = {".ssh", "$recycle.bin", "system volume information"}


def is_safe_launch_target(path: Path | str) -> bool:
    value = Path(path)
    suffix = value.suffix.lower()
    if suffix not in SAFE_LAUNCH_SUFFIXES:
        return False
    if value.name.lower() in BLOCKED_EXECUTABLE_NAMES:
        return False
    lowered_parts = {part.lower() for part in _path_parts(value)}
    return not bool(lowered_parts & PROTECTED_PARTS)


def looks_like_launchable_application(path: Path | str) -> bool:
    value = Path(path)
    if not is_safe_launch_target(value):
        return False
    if value.name.casefold() in TECHNICAL_EXECUTABLE_NAMES:
        return False
    normalized_name = value.stem.lower().replace("_", " ").replace("-", " ")
    return not any(token in normalized_name for token in NOISY_EXECUTABLE_TOKENS)


def looks_user_facing(path: Path | str, display_name: str = "") -> bool:
    """Return whether a discovered target resembles an end-user application."""

    value = Path(path)
    if not looks_like_launchable_application(value):
        return False
    text = f"{value.stem} {display_name} {' '.join(value.parts[-4:])}".casefold()
    return not any(token in text for token in NOISY_EXECUTABLE_TOKENS)


def is_critical_process(name: str) -> bool:
    return name.strip().lower() in CRITICAL_PROCESS_NAMES


def _path_parts(path: Path) -> tuple[str, ...]:
    if "\\" in str(path):
        return PureWindowsPath(str(path)).parts
    return path.parts


__all__ = [
    "BLOCKED_EXECUTABLE_NAMES",
    "CRITICAL_PROCESS_NAMES",
    "SAFE_LAUNCH_SUFFIXES",
    "is_critical_process",
    "is_safe_launch_target",
    "looks_like_launchable_application",
    "looks_user_facing",
]
