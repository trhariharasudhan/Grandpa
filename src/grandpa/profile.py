"""Local-only user profile and first-run onboarding."""

from __future__ import annotations

import os
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import click
import tomlkit
from rich.console import Console

from grandpa.core.config import (
    DEFAULT_CONFIG_PATH,
    GrandpaConfig,
    load_config,
    recommend_engine,
    recommend_model,
)

DEFAULT_USERNAME = "Username"
LOCAL_MODE = "Local only"

TextPrompt = Callable[[str, str], str]
MAX_USERNAME_LENGTH = 40
_KNOWN_BAD_ONBOARDING_VALUES = {
    "1",
    "n",
    "no",
    "ok",
    "okay",
    "oki",
    "true",
    "y",
    "yes",
}


@dataclass(frozen=True)
class LocalProfile:
    username: str
    engine: str
    model: str
    memory_enabled: bool
    onboarding_completed: bool
    mode: str = LOCAL_MODE


def config_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.environ.get("Grandpa_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()


def profile_from_config(config: GrandpaConfig) -> LocalProfile:
    return LocalProfile(
        username=_safe_username(config.user.username),
        engine=config.engine.default or "ollama",
        model=config.intelligence.default_model or "Not configured",
        memory_enabled=bool(config.agent.context_from_memory),
        onboarding_completed=bool(config.user.onboarding_completed),
    )


def load_profile(path: Path | None = None) -> LocalProfile:
    return profile_from_config(load_config(config_path(path)))


def ensure_profile(
    *,
    console: Console,
    path: Path | None = None,
    config: GrandpaConfig | None = None,
    interactive: bool | None = None,
    text_prompt: TextPrompt | None = None,
) -> GrandpaConfig:
    """Run onboarding once, using local defaults when input is unavailable."""

    target = config_path(path)
    current = config or load_config(target)
    if current.user.onboarding_completed:
        return current
    if interactive is None:
        interactive = bool(getattr(sys.stdin, "isatty", lambda: False)())
    if not interactive:
        console.print(
            "[dim]Onboarding is available in an interactive terminal; "
            "continuing with local defaults.[/dim]"
        )
        return current
    return configure_profile(
        console=console,
        path=target,
        config=current,
        interactive=True,
        text_prompt=text_prompt,
        heading="Welcome to Grandpa",
    )


def configure_profile(
    *,
    console: Console,
    path: Path | None = None,
    config: GrandpaConfig | None = None,
    interactive: bool = True,
    text_prompt: TextPrompt | None = None,
    heading: str = "Grandpa Profile",
) -> GrandpaConfig:
    """Collect and atomically persist the display name only."""

    target = config_path(path)
    current = config or load_config(target)
    username_default = _safe_username(current.user.username)

    if interactive:
        prompt_text = text_prompt or _click_text_prompt
        console.print(f"[bold #ffc448]{heading}[/bold #ffc448]")
        console.print(
            "[dim]Your profile stays on this computer. No account is required.[/dim]"
        )
        username = _prompt_username(console, prompt_text, username_default)
    else:
        return current

    atomic_update_profile(
        target,
        username=username,
        onboarding_completed=True,
    )
    load_config.cache_clear()
    updated = load_config(target)
    if interactive:
        console.print("[green]Local profile saved.[/green]")
        console.print()
    return updated


def reset_profile(
    *,
    path: Path | None = None,
    confirmed: bool = False,
) -> bool:
    if not confirmed:
        return False
    target = config_path(path)
    atomic_update_profile(target, onboarding_completed=False)
    load_config.cache_clear()
    return True


def repair_runtime_configuration(
    config: GrandpaConfig,
    *,
    resolved_engine: str,
    available_models: list[str] | tuple[str, ...] = (),
    path: Path | None = None,
) -> GrandpaConfig:
    """Repair values plausibly written by the retired free-form onboarding.

    The repair is intentionally narrow. It never downloads a model and leaves
    legitimate custom runtime settings untouched.
    """

    if not config.user.onboarding_completed:
        return config

    configured_engine = str(config.engine.default or "").strip()
    configured_model = str(config.intelligence.default_model or "").strip()
    try:
        from grandpa.core.registry import EngineRegistry

        known_engines = set(EngineRegistry.keys())
    except Exception:
        known_engines = set()
    if resolved_engine:
        known_engines.add(resolved_engine)
    engine_is_bad = _is_bad_onboarding_value(configured_engine) or bool(
        configured_engine and known_engines and configured_engine not in known_engines
    )
    installed_models = {
        str(model).strip() for model in available_models if str(model).strip()
    }
    model_is_bad = _is_bad_onboarding_value(configured_model) or bool(
        engine_is_bad
        and configured_model
        and installed_models
        and configured_model not in installed_models
    )
    if not engine_is_bad and not model_is_bad:
        return config

    updates: dict[str, object] = {}
    if engine_is_bad:
        updates["engine"] = resolved_engine or recommend_engine(config.hardware)
    if model_is_bad:
        updates["model"] = _select_repair_model(
            config,
            resolved_engine=resolved_engine,
            available_models=available_models,
        )

    atomic_update_profile(config_path(path), **updates)
    load_config.cache_clear()
    return load_config(config_path(path))


def atomic_update_profile(path: Path, **values: object) -> None:
    """Update profile-owned TOML keys with an atomic same-directory replace."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        document = tomlkit.parse(target.read_text(encoding="utf-8"))
    else:
        document = tomlkit.document()

    mapping = {
        "username": ("user", "username"),
        "onboarding_completed": ("user", "onboarding_completed"),
        "engine": ("engine", "default"),
        "model": ("intelligence", "default_model"),
        "memory_enabled": ("agent", "context_from_memory"),
    }
    for name, value in values.items():
        section_name, key = mapping[name]
        if section_name not in document:
            document.add(section_name, tomlkit.table())
        document[section_name][key] = value

    fd, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(tomlkit.dumps(document))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def format_profile(profile: LocalProfile) -> str:
    memory = "Enabled" if profile.memory_enabled else "Disabled"
    return (
        "Local Profile\n"
        f"Name: {profile.username}\n"
        f"Mode: {profile.mode}\n"
        f"Engine: {profile.engine}\n"
        f"Model: {profile.model}\n"
        f"Memory: {memory}"
    )


def _click_text_prompt(label: str, default: str) -> str:
    return str(click.prompt(label, default=default, show_default=True))


def validate_username(value: object) -> str:
    raw = str(value or "")
    if any(unicodedata.category(character).startswith("C") for character in raw):
        raise ValueError("Display name cannot contain control characters.")
    normalized = " ".join(raw.split()).strip()
    if not normalized:
        raise ValueError("Display name cannot be empty.")
    if len(normalized) > MAX_USERNAME_LENGTH:
        raise ValueError(
            f"Display name must be {MAX_USERNAME_LENGTH} characters or fewer."
        )
    return normalized


def _safe_username(value: object) -> str:
    try:
        return validate_username(value)
    except ValueError:
        return DEFAULT_USERNAME


def _prompt_username(
    console: Console,
    prompt_text: TextPrompt,
    default: str,
) -> str:
    while True:
        try:
            return validate_username(prompt_text("Display name", default))
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")


def _is_bad_onboarding_value(value: str) -> bool:
    return value.casefold() in _KNOWN_BAD_ONBOARDING_VALUES


def _select_repair_model(
    config: GrandpaConfig,
    *,
    resolved_engine: str,
    available_models: list[str] | tuple[str, ...],
) -> str:
    installed = [str(model).strip() for model in available_models if str(model).strip()]
    fallback = str(config.intelligence.fallback_model or "").strip()
    recommended = recommend_model(config.hardware, resolved_engine)
    for candidate in (fallback, "grandpa-fast:latest", recommended):
        if candidate and candidate in installed:
            return candidate
    if installed:
        return installed[0]
    if fallback and not _is_bad_onboarding_value(fallback):
        return fallback
    return recommended


__all__ = [
    "LOCAL_MODE",
    "LocalProfile",
    "atomic_update_profile",
    "config_path",
    "configure_profile",
    "ensure_profile",
    "format_profile",
    "load_profile",
    "profile_from_config",
    "reset_profile",
    "repair_runtime_configuration",
    "validate_username",
]
