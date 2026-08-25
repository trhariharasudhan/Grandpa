"""``Grandpa models`` and ``Grandpa model`` — model registry and metadata subcommands."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from grandpa.core.config import load_config
from grandpa.core.registry import ModelRegistry
from grandpa.core.types import ModelSpec
from grandpa.engine import discover_engines, discover_models, get_engine
from grandpa.intelligence import merge_discovered_models, register_builtin_models
from grandpa.intelligence.grandpa_models import get_model_role
from grandpa.intelligence.model_catalog import BUILTIN_MODELS


def _populate_registry() -> Any:
    """Populate ModelRegistry with built-in models and runtime discovered models."""
    register_builtin_models()
    try:
        from grandpa.models.manager import discover_native_models

        discover_native_models()
    except Exception:
        pass
    try:
        config = load_config()
        engines = discover_engines(config)
        all_models = discover_models(engines)
        for ek, model_ids in all_models.items():
            merge_discovered_models(ek, model_ids)
        return config
    except Exception:
        return None


def _resolve_spec(model_name: str) -> ModelSpec | None:
    """Resolve a model name, role, or alias from ModelRegistry."""
    clean_name = (model_name or "").strip()
    if not clean_name:
        return None

    if ModelRegistry.contains(clean_name):
        return ModelRegistry.get(clean_name)

    # Check if this matches a canonical role or alias (e.g., 'mini', 'fast', 'coder')
    role = get_model_role(clean_name)
    if role and ModelRegistry.contains(role.ollama_tag):
        return ModelRegistry.get(role.ollama_tag)

    # Case-insensitive search
    lower = clean_name.lower()
    for spec in ModelRegistry.list_models():
        if spec.model_id.lower() == lower or spec.name.lower() == lower:
            return spec

    return None


def _render_models_list(
    console: Console,
    *,
    capability: str | None = None,
    family: str | None = None,
    backend: str | None = None,
    status: str | None = None,
    as_json: bool = False,
) -> None:
    _populate_registry()

    specs = ModelRegistry.list_models()

    if capability:
        cap = capability.lower().strip()
        specs = [
            s
            for s in specs
            if any(str(c).lower().strip() == cap for c in s.capabilities)
        ]
    if family:
        fam = family.lower().strip()
        specs = [s for s in specs if s.family.lower().strip() == fam]
    if backend:
        b = backend.lower().strip()
        specs = [
            s
            for s in specs
            if s.backend.lower().strip() == b
            or any(str(e).lower().strip() == b for e in s.supported_engines)
        ]
    if status:
        st = status.lower().strip()
        specs = [s for s in specs if s.status.lower().strip() == st]

    if as_json:
        payload = [s.to_dict() for s in specs]
        console.print(json.dumps(payload, indent=2))
        return

    if not specs:
        console.print("[yellow]No models found matching query criteria.[/yellow]")
        return

    table = Table(title=f"Grandpa Model Registry ({len(specs)} models)")
    table.add_column("Model ID", style="cyan")
    table.add_column("Display Name", style="green")
    table.add_column("Family", style="magenta")
    table.add_column("Capabilities", style="blue")
    table.add_column("Backend", style="yellow")
    table.add_column("Params", justify="right")
    table.add_column("Context", justify="right")
    table.add_column("Status", style="dim")

    for spec in specs:
        params = f"{spec.parameter_count_b}B" if spec.parameter_count_b else "-"
        ctx = f"{spec.context_length:,}" if spec.context_length else "-"
        caps_str = ",".join(spec.capabilities) if spec.capabilities else "chat"
        table.add_row(
            spec.model_id,
            spec.display_name,
            spec.family or "-",
            caps_str,
            spec.backend or "local",
            params,
            ctx,
            spec.status or "available",
        )

    console.print(table)


def _render_model_info(
    console: Console,
    model_name: str,
    *,
    as_json: bool = False,
) -> None:
    if not model_name or not model_name.strip():
        console.print("[red]Error: Model name cannot be empty.[/red]")
        sys.exit(2)

    _populate_registry()
    spec = _resolve_spec(model_name)

    if spec is None:
        console.print(f"[red]Model not found:[/red] {model_name}")
        sys.exit(1)

    if as_json:
        console.print(json.dumps(spec.to_dict(), indent=2))
        return

    params = (
        f"{spec.parameter_count_b}B"
        if spec.parameter_count_b
        else "unknown"
    )
    active = (
        f"{spec.active_parameter_count_b}B"
        if spec.active_parameter_count_b
        else "-"
    )
    ctx_len = f"{spec.context_length:,}" if spec.context_length else "unknown"
    vram = f"{spec.min_vram_gb}GB" if spec.min_vram_gb else "-"
    caps_str = ", ".join(spec.capabilities) if spec.capabilities else "chat"
    engines_str = (
        ", ".join(spec.supported_engines)
        if spec.supported_engines
        else spec.backend or "local"
    )
    api_key = "required" if spec.requires_api_key else "not required"

    lines = [
        f"[bold]Model ID:[/bold]       {spec.model_id}",
        f"[bold]Display Name:[/bold]   {spec.display_name}",
        f"[bold]Version/Tag:[/bold]    {spec.version}",
        f"[bold]Model Family:[/bold]   {spec.family or '-'}",
        f"[bold]Capabilities:[/bold]   {caps_str}",
        f"[bold]Parameters:[/bold]     {params}",
        f"[bold]Active Params:[/bold]  {active}",
        f"[bold]Context Length:[/bold] {ctx_len}",
        f"[bold]Quantization:[/bold]   {spec.quantization.value}",
        f"[bold]Min VRAM:[/bold]       {vram}",
        f"[bold]Backend:[/bold]        {spec.backend}",
        f"[bold]Engines:[/bold]        {engines_str}",
        f"[bold]Local Path:[/bold]     {spec.local_path or 'managed'}",
        f"[bold]Status:[/bold]         {spec.status}",
        f"[bold]Provider:[/bold]       {spec.provider or '-'}",
        f"[bold]API Key:[/bold]        {api_key}",
    ]

    meta_labels = {
        "architecture": "Architecture",
        "url": "More Info",
        "teacher": "Teacher Model",
        "license": "License",
        "pricing_input": "Price (input)",
        "pricing_output": "Price (output)",
    }
    for key, label in meta_labels.items():
        value = spec.metadata.get(key)
        if value is not None:
            if key.startswith("pricing_"):
                value = f"${value}/M tokens"
            pad = " " * max(1, 14 - len(label))
            lines.append(f"[bold]{label}:[/bold]{pad}{value}")

    extra_keys = set(spec.metadata) - set(meta_labels)
    for key in sorted(extra_keys):
        pad = " " * max(1, 14 - len(key))
        lines.append(f"[bold]{key}:[/bold]{pad}{spec.metadata[key]}")

    console.print(
        Panel(
            "\n".join(lines),
            title=f"Model: {spec.display_name}",
            border_style="blue",
        )
    )


def _render_models_status(
    console: Console,
    *,
    as_json: bool = False,
) -> None:
    config = _populate_registry() or load_config()
    specs = ModelRegistry.list_models()

    default_model = config.intelligence.default_model or "grandpa-mini:latest"
    active_engine_key = config.engine.default or "ollama"

    resolved_engine = get_engine(config, active_engine_key)
    engine_healthy = resolved_engine[1].health() if resolved_engine else False
    installed_models = (
        resolved_engine[1].list_models() if resolved_engine else []
    )

    cap_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    backend_counts: dict[str, int] = {}

    for s in specs:
        for c in s.capabilities:
            cap_counts[c] = cap_counts.get(c, 0) + 1
        if s.family:
            family_counts[s.family] = family_counts.get(s.family, 0) + 1
        backend_counts[s.backend] = backend_counts.get(s.backend, 0) + 1

    status_data = {
        "status": "ready" if engine_healthy else "degraded",
        "default_model": default_model,
        "default_model_available": (default_model in installed_models)
        or any(s.model_id == default_model for s in specs),
        "active_backend": active_engine_key,
        "backend_healthy": engine_healthy,
        "total_registered_models": len(specs),
        "total_installed_models": len(installed_models),
        "capability_breakdown": cap_counts,
        "family_breakdown": family_counts,
        "backend_breakdown": backend_counts,
    }

    if as_json:
        console.print(json.dumps(status_data, indent=2))
        return

    table = Table(title="Grandpa Model Platform Status")
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")

    health_style = "[green]Healthy[/green]" if engine_healthy else "[red]Unreachable[/red]"
    table.add_row("Active Engine Backend", f"{active_engine_key} ({health_style})")
    table.add_row("Default Model", str(default_model))
    table.add_row("Total Registered Models", str(len(specs)))
    table.add_row("Installed Models on Engine", str(len(installed_models)))

    caps_summary = ", ".join(f"{k}: {v}" for k, v in sorted(cap_counts.items()))
    table.add_row("Capabilities", caps_summary or "-")

    families_summary = ", ".join(
        f"{k}: {v}" for k, v in sorted(family_counts.items())
    )
    table.add_row("Model Families", families_summary or "-")

    backends_summary = ", ".join(
        f"{k}: {v}" for k, v in sorted(backend_counts.items())
    )
    table.add_row("Backends", backends_summary or "-")

    console.print(table)


# ---------------------------------------------------------------------------
# Click Command Groups
# ---------------------------------------------------------------------------


@click.group("models")
def models_cmd() -> None:
    """Manage Grandpa model registry and metadata."""


@models_cmd.command("list")
@click.option("--capability", "-c", default=None, help="Filter by capability (e.g. chat, code, image, embeddings).")
@click.option("--family", "-f", default=None, help="Filter by model family (e.g. qwen, llama, deepseek).")
@click.option("--backend", "-b", default=None, help="Filter by backend (e.g. ollama, local, llamacpp).")
@click.option("--status", "-s", default=None, help="Filter by status (e.g. available, downloading).")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output results in JSON format.")
def models_list(
    capability: str | None,
    family: str | None,
    backend: str | None,
    status: str | None,
    as_json: bool,
) -> None:
    """List all registered models in the Grandpa registry."""
    console = Console()
    _render_models_list(
        console,
        capability=capability,
        family=family,
        backend=backend,
        status=status,
        as_json=as_json,
    )


@models_cmd.command("info")
@click.argument("model_name")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output in JSON format.")
def models_info(model_name: str, as_json: bool) -> None:
    """Show detailed metadata for a registered model."""
    console = Console()
    _render_model_info(console, model_name, as_json=as_json)

@models_cmd.command("status")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output status in JSON format.")
def models_status(as_json: bool) -> None:
    """Show current model registry and active backend status."""
    console = Console()
    _render_models_status(console, as_json=as_json)


def _handle_pull(
    model_name: str,
    *,
    filename: str | None = None,
    backend: str | None = None,
    model_id: str | None = None,
    sha256: str | None = None,
    revision: str = "main",
    console: Console,
) -> None:
    config = load_config()
    target_backend = (backend or "").lower().strip()

    # Determine if this is a native GGUF acquisition or Ollama pull
    is_native = (
        target_backend == "native"
        or (
            not target_backend
            and (
                filename is not None
                or model_name.lower().endswith(".gguf")
                or ("/" in model_name and not model_name.startswith("http"))
            )
        )
    )

    if is_native:
        from grandpa.models.manager import get_model_manager
        from grandpa.models.security import ChecksumMismatchError, ModelSecurityError

        mgr = get_model_manager(config)
        target_id = model_id or (
            filename.rsplit(".", 1)[0]
            if filename
            else model_name.split("/")[-1].rsplit(".", 1)[0]
        )

        console.print(f"Acquiring native model [cyan]{model_name}[/cyan]...")

        def _progress(downloaded: int, total: int | None) -> None:
            if total and total > 0:
                pct = int(downloaded / total * 100)
                mb_down = downloaded / (1024 * 1024)
                mb_total = total / (1024 * 1024)
                console.print(
                    f"  Downloading: {pct}% ({mb_down:.1f}/{mb_total:.1f} MB)",
                    end="\r",
                )
            else:
                mb_down = downloaded / (1024 * 1024)
                console.print(f"  Downloading: {mb_down:.1f} MB", end="\r")

        try:
            spec = mgr.install(
                model_id=target_id,
                source_ref=model_name,
                filename=filename,
                revision=revision,
                sha256=sha256,
                progress_callback=_progress,
            )
            mb_size = (spec.size_bytes or 0) / (1024 * 1024)
            console.print(
                f"\n[green]Successfully installed {spec.model_id} ({mb_size:.1f} MB)[/green]"
            )
            console.print(f"Path: {spec.local_path}")
        except (ModelSecurityError, ChecksumMismatchError) as exc:
            console.print(f"\n[red]Security/Verification Error:[/red] {exc}")
            sys.exit(1)
        except Exception as exc:
            console.print(f"\n[red]Acquisition failed:[/red] {exc}")
            sys.exit(1)
    else:
        host = (
            config.engine.ollama_host
            or os.environ.get("OLLAMA_HOST")
            or "http://localhost:11434"
        ).rstrip("/")
        if not ollama_pull(host, model_name, console):
            sys.exit(1)


def _handle_remove(model_name: str, console: Console) -> None:
    config = load_config()
    from grandpa.models.manager import get_model_manager

    mgr = get_model_manager(config)
    if mgr.remove(model_name):
        console.print(f"[green]Successfully removed local native model:[/green] {model_name}")
        return

    # Check if this exists on active engine (e.g. Ollama)
    try:
        engine = get_engine(config)
        if hasattr(engine, "delete_model"):
            if engine.delete_model(model_name):
                console.print(
                    f"[green]Successfully removed model from {config.engine.default}:[/green] {model_name}"
                )
                return
    except Exception:
        pass

    console.print(f"[yellow]Model not found or could not be removed:[/yellow] {model_name}")
    sys.exit(1)


@models_cmd.command("pull")
@click.argument("model_name")
@click.option("--filename", "-f", default=None, help="GGUF filename in repository.")
@click.option(
    "--backend",
    "-b",
    type=click.Choice(["native", "ollama"], case_sensitive=False),
    default=None,
    help="Target engine backend.",
)
@click.option("--model-id", default=None, help="Custom identifier for ModelRegistry.")
@click.option("--sha256", default=None, help="Expected SHA-256 checksum for verification.")
@click.option("--revision", default="main", help="Repository revision/branch.")
def models_pull(
    model_name: str,
    filename: str | None,
    backend: str | None,
    model_id: str | None,
    sha256: str | None,
    revision: str,
) -> None:
    """Download and install a model from Hugging Face (GGUF) or Ollama."""
    console = Console()
    _handle_pull(
        model_name,
        filename=filename,
        backend=backend,
        model_id=model_id,
        sha256=sha256,
        revision=revision,
        console=console,
    )


@models_cmd.command("remove")
@click.argument("model_name")
def models_remove(model_name: str) -> None:
    """Remove a locally installed model."""
    console = Console()
    _handle_remove(model_name, console)


@click.group("model")
def model() -> None:
    """Manage language models (alias for 'grandpa models')."""


@model.command("list")
@click.option("--capability", "-c", default=None, help="Filter by capability.")
@click.option("--family", "-f", default=None, help="Filter by model family.")
@click.option("--backend", "-b", default=None, help="Filter by backend.")
@click.option("--status", "-s", default=None, help="Filter by status.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output in JSON format.")
def legacy_model_list(
    capability: str | None,
    family: str | None,
    backend: str | None,
    status: str | None,
    as_json: bool,
) -> None:
    """List available models from running engines and registry."""
    console = Console()
    config = load_config()
    register_builtin_models()

    engines = discover_engines(config)
    if not engines:
        console.print(
            "[yellow]No inference engines detected.[/yellow]\n"
            "Start an engine (e.g. [cyan]ollama serve[/cyan]) and try again."
        )
        return

    _render_models_list(
        console,
        capability=capability,
        family=family,
        backend=backend,
        status=status,
        as_json=as_json,
    )


@model.command("info")
@click.argument("model_name")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output in JSON format.")
def legacy_model_info(model_name: str, as_json: bool) -> None:
    """Show details for a model."""
    console = Console()
    _render_model_info(console, model_name, as_json=as_json)


@model.command("status")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output in JSON format.")
def legacy_model_status(as_json: bool) -> None:
    """Show model platform status."""
    console = Console()
    _render_models_status(console, as_json=as_json)


def ollama_pull(host: str, model_name: str, console: Console) -> bool:
    """Pull a model via Ollama API. Returns True on success."""
    console.print(f"Pulling [cyan]{model_name}[/cyan] via Ollama...")
    try:
        with httpx.stream(
            "POST",
            f"{host}/api/pull",
            json={"name": model_name, "stream": True},
            timeout=600.0,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                status_val = data.get("status", "")
                if "total" in data and "completed" in data:
                    total = data["total"]
                    done = data["completed"]
                    pct = int(done / total * 100) if total else 0
                    console.print(f"  {status_val}: {pct}%", end="\r")
                elif status_val:
                    console.print(f"  {status_val}")
        console.print(f"\n[green]Successfully pulled {model_name}[/green]")
        return True
    except httpx.ConnectError:
        console.print("[red]Cannot connect to Ollama.[/red] Is it running?")
        return False
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]Ollama error:[/red] {exc.response.status_code}")
        return False


def find_model_spec(model_name: str) -> ModelSpec | None:
    """Look up a model in the builtin catalog. Returns None if not found."""
    for spec in BUILTIN_MODELS:
        if spec.model_id == model_name:
            return spec
    return None


@model.command("pull")
@click.argument("model_name")
@click.option("--filename", "-f", default=None, help="GGUF filename in repository.")
@click.option(
    "--backend",
    "-b",
    type=click.Choice(["native", "ollama"], case_sensitive=False),
    default=None,
    help="Target engine backend.",
)
@click.option("--model-id", default=None, help="Custom identifier for ModelRegistry.")
@click.option("--sha256", default=None, help="Expected SHA-256 checksum for verification.")
@click.option("--revision", default="main", help="Repository revision/branch.")
def pull(
    model_name: str,
    filename: str | None,
    backend: str | None,
    model_id: str | None,
    sha256: str | None,
    revision: str,
) -> None:
    """Download and install a model."""
    console = Console()
    _handle_pull(
        model_name,
        filename=filename,
        backend=backend,
        model_id=model_id,
        sha256=sha256,
        revision=revision,
        console=console,
    )


@model.command("remove")
@click.argument("model_name")
def remove(model_name: str) -> None:
    """Remove a locally installed model."""
    console = Console()
    _handle_remove(model_name, console)


__all__ = [
    "find_model_spec",
    "model",
    "models_cmd",
    "ollama_pull",
]
