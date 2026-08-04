"""Application name normalization, aliases, and matching."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from grandpa.apps.models import ApplicationInfo, AppResolveResult

FUZZY_THRESHOLD = 0.72

_CANONICAL_NAMES = {
    "chrome": "google chrome",
    "google chrome": "google chrome",
    "code": "visual studio code",
    "vs code": "visual studio code",
    "vscode": "visual studio code",
    "microsoft visual studio code": "visual studio code",
    "microsoft visual studio code user": "visual studio code",
    "msedge": "microsoft edge",
    "edge": "microsoft edge",
}


def normalize_app_name(value: str) -> str:
    cleaned = Path(value).stem if value.lower().endswith((".exe", ".lnk")) else value
    cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
    cleaned = cleaned.replace("_", " ").replace("-", " ").replace(".", " ")
    cleaned = re.sub(
        r"\b(shortcut|app|application)\b", " ", cleaned, flags=re.IGNORECASE
    )
    return " ".join(cleaned.casefold().split())


def generate_aliases(display_name: str, executable_name: str = "") -> tuple[str, ...]:
    normalized = normalize_app_name(display_name)
    exe = normalize_app_name(executable_name)
    aliases = {item for item in (normalized, exe) if item}
    words = normalized.split()
    if normalized.startswith("microsoft "):
        aliases.add(normalized.removeprefix("microsoft ").strip())
    if normalized.startswith("google "):
        aliases.add(normalized.removeprefix("google ").strip())
    if "visual studio code" in aliases or exe == "code":
        aliases.update({"visual studio code", "vs code", "vscode", "code"})
    if "android studio" in aliases:
        aliases.add("studio")
    if len(words) > 1:
        aliases.add(words[-1])
    return tuple(sorted(alias for alias in aliases if alias))


def canonicalize_app_identity(display_name: str, executable_name: str = "") -> str:
    """Return a stable identity shared by shortcuts, registry rows, and executables."""

    without_qualifiers = re.sub(r"\([^)]*\)", " ", display_name)
    without_version = re.sub(
        r"\s+v?\d+(?:\.\d+)+(?:\.\d+)*\s*$", "", without_qualifiers, flags=re.IGNORECASE
    )
    normalized = normalize_app_name(without_version)
    executable = normalize_app_name(executable_name)
    for candidate in (normalized, executable):
        if candidate in _CANONICAL_NAMES:
            return _CANONICAL_NAMES[candidate]
    if (
        normalized.startswith("microsoft ")
        and normalized.removeprefix("microsoft ") in _CANONICAL_NAMES
    ):
        return _CANONICAL_NAMES[normalized.removeprefix("microsoft ")]
    return normalized or executable


def resolve_app(query: str, apps: list[ApplicationInfo]) -> AppResolveResult:
    normalized = normalize_app_name(query)
    if not normalized:
        return AppResolveResult("missing", (), "Tell me which application to use.")

    searchable = [app for app in apps if app.is_user_facing and app.is_launchable]
    exact_name = [
        app
        for app in searchable
        if normalized == app.name or normalized == app.canonical_key
    ]
    if len(exact_name) == 1:
        return AppResolveResult(
            "found", (exact_name[0],), f"Found {exact_name[0].display_name}.", 1.0
        )
    if len(exact_name) > 1:
        preferred = _preferred_single_match(exact_name)
        if preferred is not None:
            return AppResolveResult(
                "found", (preferred,), f"Found {preferred.display_name}.", 1.0
            )
        return AppResolveResult(
            "ambiguous", tuple(exact_name[:8]), _ambiguous_message(exact_name), 1.0
        )

    exact_alias = [app for app in searchable if normalized in app.aliases]
    if len(exact_alias) == 1:
        return AppResolveResult(
            "found", (exact_alias[0],), f"Found {exact_alias[0].display_name}.", 1.0
        )
    if len(exact_alias) > 1:
        preferred = _preferred_single_match(exact_alias)
        if preferred is not None:
            return AppResolveResult(
                "found", (preferred,), f"Found {preferred.display_name}.", 1.0
            )
        return AppResolveResult(
            "ambiguous", tuple(exact_alias[:8]), _ambiguous_message(exact_alias), 1.0
        )

    starts_with = [
        app
        for app in searchable
        if app.name.startswith(normalized)
        or any(alias.startswith(normalized) for alias in app.aliases)
    ]
    if len(starts_with) == 1:
        return AppResolveResult(
            "found", (starts_with[0],), f"Found {starts_with[0].display_name}.", 0.88
        )
    if len(starts_with) > 1:
        return AppResolveResult(
            "ambiguous", tuple(starts_with[:8]), _ambiguous_message(starts_with), 0.88
        )

    contains = [
        app
        for app in searchable
        if normalized in app.name or any(normalized in alias for alias in app.aliases)
    ]
    if len(contains) == 1:
        return AppResolveResult(
            "found", (contains[0],), f"Found {contains[0].display_name}.", 0.8
        )
    if len(contains) > 1:
        return AppResolveResult(
            "ambiguous", tuple(contains[:8]), _ambiguous_message(contains), 0.8
        )

    fuzzy: list[tuple[float, ApplicationInfo]] = []
    for app in searchable:
        candidates = (app.name, *app.aliases)
        score = max(
            difflib.SequenceMatcher(a=normalized, b=candidate).ratio()
            for candidate in candidates
        )
        if score >= FUZZY_THRESHOLD:
            fuzzy.append((score, app))
    fuzzy.sort(key=lambda item: item[0], reverse=True)
    if not fuzzy:
        return AppResolveResult(
            "missing",
            (),
            f"I could not find an installed app named {query}. Try `grandpa apps scan`.",
        )
    best_score = fuzzy[0][0]
    close = [app for score, app in fuzzy if best_score - score < 0.05]
    if len(close) == 1:
        return AppResolveResult(
            "found", (close[0],), f"Found {close[0].display_name}.", best_score
        )
    return AppResolveResult(
        "ambiguous", tuple(close[:8]), _ambiguous_message(close), best_score
    )


def _ambiguous_message(matches: list[ApplicationInfo]) -> str:
    names = ", ".join(app.display_name for app in matches[:8])
    return f"I found multiple apps: {names}. Which one should I open?"


def _preferred_single_match(matches: list[ApplicationInfo]) -> ApplicationInfo | None:
    normalized_targets = {app.path.casefold() for app in matches}
    if len(normalized_targets) == 1:
        return matches[0]
    exe_matches = [app for app in matches if app.path.casefold().endswith(".exe")]
    if len(exe_matches) == 1:
        return exe_matches[0]
    unique_names = {app.name for app in matches}
    if len(unique_names) == 1 and exe_matches:
        return exe_matches[0]
    return None


__all__ = [
    "FUZZY_THRESHOLD",
    "canonicalize_app_identity",
    "generate_aliases",
    "normalize_app_name",
    "resolve_app",
]
