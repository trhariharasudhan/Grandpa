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
PREFERRED_TITLES = ("Mr.", "Ms.", "Mrs.", "Mx.", "")
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
    title: str
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
        title=validate_title(getattr(config.user, "title", "")),
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
    title_prompt: Callable[[str], str] | None = None,
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
        title_prompt=title_prompt,
        heading="Welcome to Grandpa",
    )


def configure_profile(
    *,
    console: Console,
    path: Path | None = None,
    config: GrandpaConfig | None = None,
    interactive: bool = True,
    text_prompt: TextPrompt | None = None,
    title_prompt: Callable[[str], str] | None = None,
    heading: str = "Grandpa Profile",
    edit_username: bool = True,
    edit_title: bool = True,
) -> GrandpaConfig:
    """Collect and atomically persist profile-owned identity fields."""

    target = config_path(path)
    current = config or load_config(target)
    username_default = _safe_username(current.user.username)

    if interactive:
        prompt_text = text_prompt or _click_text_prompt
        console.print(f"[bold #ffc448]{heading}[/bold #ffc448]")
        console.print(
            "[dim]Your profile stays on this computer. No account is required.[/dim]"
        )
        username = (
            _prompt_username(console, prompt_text, username_default)
            if edit_username
            else username_default
        )
        title = (
            validate_title((title_prompt or _click_title_prompt)(current.user.title))
            if edit_title
            else validate_title(current.user.title)
        )
    else:
        return current

    atomic_update_profile(
        target,
        username=username,
        title=title,
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
    from grandpa.intelligence.grandpa_models import canonical_installed_tag

    canonical_model = canonical_installed_tag(configured_model, available_models)
    model_needs_migration = bool(
        canonical_model and canonical_model != configured_model
    )
    if not engine_is_bad and not model_is_bad and not model_needs_migration:
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
    elif model_needs_migration:
        updates["model"] = canonical_model

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
        "title": ("user", "title"),
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
        f"Preferred title: {profile.title or 'None'}\n"
        f"Mode: {profile.mode}\n"
        f"Engine: {profile.engine}\n"
        f"Model: {profile.model}\n"
        f"Memory: {memory}"
    )


def _click_text_prompt(label: str, default: str) -> str:
    return str(click.prompt(label, default=default, show_default=True))


def _click_title_prompt(current: str) -> str:
    labels = ("Mr.", "Ms.", "Mrs.", "Mx.", "No title")
    default = str(PREFERRED_TITLES.index(validate_title(current)) + 1)
    click.echo("Preferred title:")
    for index, label in enumerate(labels, start=1):
        click.echo(f"  {index}. {label}")
    selected = click.prompt(
        "Select preferred title",
        type=click.Choice(tuple(str(index) for index in range(1, 6))),
        default=default,
        show_default=True,
    )
    return PREFERRED_TITLES[int(selected) - 1]


def validate_title(value: object) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized or normalized.casefold() in {"none", "no title"}:
        return ""
    without_period = normalized.rstrip(".").casefold()
    for title in PREFERRED_TITLES[:-1]:
        if title.rstrip(".").casefold() == without_period:
            return title
    raise ValueError("Preferred title must be Mr., Ms., Mrs., Mx., or no title.")


def format_profile_display_name(profile_or_config: LocalProfile | GrandpaConfig) -> str:
    """Return the canonical formal profile name for greeting surfaces."""

    profile = (
        profile_or_config
        if isinstance(profile_or_config, LocalProfile)
        else profile_from_config(profile_or_config)
    )
    return f"{profile.title} {profile.username}".strip()


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
    from grandpa.intelligence.grandpa_models import DEFAULT_MODEL_TAG

    for candidate in (fallback, DEFAULT_MODEL_TAG, "grandpa-fast:latest", recommended):
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
    "format_profile_display_name",
    "load_profile",
    "profile_from_config",
    "reset_profile",
    "repair_runtime_configuration",
    "validate_username",
    "validate_title",
]
