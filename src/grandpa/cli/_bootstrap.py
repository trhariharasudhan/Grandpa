"""Initial local Ollama configuration writer."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import click

import grandpa
from grandpa.core import config as _cfg
from grandpa.core.config import (
    HardwareInfo,
    detect_hardware,
    recommend_engine,
    recommend_model,
)

# ---------------------------------------------------------------------------
# Initial config writer
# ---------------------------------------------------------------------------

_DEFAULT_SOUL = "# Agent Persona\n\nYou are Grandpa, a helpful personal AI assistant.\n"
_DEFAULT_MEMORY = "# Agent Memory\n\n"
_DEFAULT_USER = "# User Profile\n\n"


def _toml_quote(value: str) -> str:
    """Escape a runtime value for use inside TOML "..." double-quoted string.

    Per TOML spec: backslash and double-quote must be backslash-escaped in
    basic strings.  Other control chars are not common in our values, so we
    don't escape them — keeping this helper minimal.
    """
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _installer_version() -> str:
    return grandpa.__version__


def _render_provenance_lines() -> str:
    return (
        f"installed_at = {_toml_quote(_now_iso())}\n"
        f"installer_version = {_toml_quote(_installer_version())}\n"
    )


def write_initial_config(
    *,
    hardware: HardwareInfo,
    engine: str,
    model: str,
) -> Path:
    """Render the initial ``config.toml`` and seed memory files.

    Called by ``Grandpa init`` so the TOML format has one definition.
    """
    _cfg.DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    gpu_comment = ""
    if hardware.gpu:
        mem_label = "unified memory" if hardware.gpu.vendor == "apple" else "VRAM"
        gpu_comment = (
            f"\n# GPU: {hardware.gpu.name} ({hardware.gpu.vram_gb} GB {mem_label})"
        )

    intelligence_section = f"default_model = {_toml_quote(model)}"

    # Provenance must come before table declarations to be top-level keys.
    provenance = _render_provenance_lines().rstrip("\n")

    hardware_line = (
        f"# Hardware: {hardware.cpu_brand} "
        f"({hardware.cpu_count} cores, {hardware.ram_gb} GB RAM)"
    )

    base_toml = (
        f"# Grandpa configuration\n"
        f"{hardware_line}{gpu_comment}\n"
        f"# Full reference config: Grandpa init --full\n"
        f"\n"
        f"{provenance}\n"
        f"\n"
        f"[engine]\n"
        f"default = {_toml_quote(engine)}\n"
        f"\n"
        f"[engine.{engine}]\n"
        f"# host = "
        f'"http://localhost:11434"  '
        f"# set to remote URL if engine runs elsewhere\n"
        f"\n"
        f"[intelligence]\n"
        f"{intelligence_section}\n"
        f"\n"
        f"[agent]\n"
        f'default_agent = "simple"\n'
        f"\n"
        f"[tools]\n"
        f'enabled = ["code_interpreter", "web_search", '
        f'"file_read", "shell_exec"]\n'
    )

    _cfg.DEFAULT_CONFIG_PATH.write_text(base_toml)

    _seed_memory_files()

    return _cfg.DEFAULT_CONFIG_PATH


def _seed_memory_files() -> None:
    """Create SOUL.md / MEMORY.md / USER.md / skills/ if absent."""
    home = _cfg.DEFAULT_CONFIG_DIR
    if not (home / "SOUL.md").exists():
        (home / "SOUL.md").write_text(_DEFAULT_SOUL)
    if not (home / "MEMORY.md").exists():
        (home / "MEMORY.md").write_text(_DEFAULT_MEMORY)
    if not (home / "USER.md").exists():
        (home / "USER.md").write_text(_DEFAULT_USER)
    (home / "skills").mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# CLI command — internal helper, hidden from ``Grandpa --help``
# ---------------------------------------------------------------------------


@click.command("_bootstrap", hidden=True)
@click.option(
    "--write-config",
    is_flag=True,
    default=False,
    help="Render config.toml from detected hardware + provided engine/model.",
)
@click.option(
    "--engine",
    default="",
    help="Inference engine slug (e.g. ollama). Empty = auto-recommend.",
)
@click.option(
    "--model",
    default="",
    help="Model id (e.g. qwen3.5:2b). Empty = auto-recommend.",
)
def bootstrap_cmd(
    write_config: bool,
    engine: str,
    model: str,
) -> None:
    """Internal helper for writing the initial local configuration."""
    if not write_config:
        raise click.UsageError("--write-config is required")

    hw = detect_hardware()
    chosen_engine = engine or recommend_engine(hw)
    chosen_model = model or recommend_model(hw, chosen_engine)

    write_initial_config(
        hardware=hw,
        engine=chosen_engine,
        model=chosen_model,
    )
    click.echo(f"Wrote {_cfg.DEFAULT_CONFIG_PATH}")
