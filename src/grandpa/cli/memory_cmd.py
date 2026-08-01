"""``Grandpa memory`` — memory management subcommands."""

from __future__ import annotations

import time
from pathlib import Path

import click
from rich.console import Console
from rich.progress import track
from rich.table import Table

from grandpa.core.config import load_config
from grandpa.core.registry import MemoryRegistry
from grandpa.memory.models import redact_sensitive
from grandpa.memory.service import MemoryService
from grandpa.tools.storage.chunking import ChunkConfig
from grandpa.tools.storage.ingest import ingest_path


def _get_backend(backend_key: str | None = None):
    """Instantiate the configured (or overridden) memory backend."""
    config = load_config()
    key = backend_key or config.memory.default_backend

    # Ensure backends are registered
    from grandpa.tools.storage import load_storage_backends

    load_storage_backends()

    if not MemoryRegistry.contains(key):
        raise click.ClickException(
            f"Memory backend '{key}' not found. "
            f"Available: {', '.join(MemoryRegistry.keys())}"
        )

    if key == "sqlite":
        return MemoryRegistry.create(key, db_path=config.memory.db_path)
    return MemoryRegistry.create(key)


@click.group()
def memory() -> None:
    """Manage the memory store."""


@memory.command()
@click.argument("path")
@click.option(
    "--backend",
    "-b",
    default=None,
    help="Override the default memory backend.",
)
@click.option(
    "--chunk-size",
    default=512,
    type=int,
    help="Chunk size in tokens.",
)
@click.option(
    "--chunk-overlap",
    default=64,
    type=int,
    help="Overlap between chunks in tokens.",
)
def index(
    path: str,
    backend: str | None,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    """Index documents from a file or directory."""
    console = Console(stderr=True)
    target = Path(path)

    if not target.exists():
        console.print(f"[red]Path not found:[/red] {path}")
        raise SystemExit(1)

    t0 = time.time()
    cfg = ChunkConfig(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    console.print(f"[cyan]Indexing[/cyan] {path} ...")
    chunks = ingest_path(target, config=cfg)

    if not chunks:
        console.print("[yellow]No indexable content found.[/yellow]")
        return

    mem = _get_backend(backend)
    try:
        for chunk in track(chunks, description="Storing chunks...", console=console):
            mem.store(
                chunk.content,
                source=chunk.source,
                metadata={
                    "offset": chunk.offset,
                    "index": chunk.index,
                },
            )
    finally:
        if hasattr(mem, "close"):
            mem.close()

    elapsed = time.time() - t0
    sources = {c.source for c in chunks}
    console.print(
        f"[green]Indexed {len(chunks)} chunks "
        f"from {len(sources)} file(s) "
        f"in {elapsed:.1f}s.[/green]"
    )


@memory.command()
@click.argument("query", nargs=-1, required=True)
@click.option(
    "--top-k",
    "-k",
    default=5,
    type=int,
    help="Number of results to return.",
)
@click.option(
    "--backend",
    "-b",
    default=None,
    help="Override the default memory backend.",
)
def search(
    query: tuple[str, ...],
    top_k: int,
    backend: str | None,
) -> None:
    """Search the memory store."""
    console = Console()
    query_text = " ".join(query)

    # First search MemoryService V1 store
    svc = MemoryService.get_instance()
    v1_results = svc.search(query_text, limit=top_k)

    mem = _get_backend(backend)
    results = []
    try:
        results = mem.retrieve(query_text, top_k=top_k)
    except Exception:
        pass
    finally:
        if hasattr(mem, "close"):
            mem.close()

    if not v1_results and not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search: {query_text}")
    table.add_column("#", style="dim", width=3)
    table.add_column("Category/Score", width=14)
    table.add_column("Key/Source", style="cyan")
    table.add_column("Content")

    row_num = 1
    for item in v1_results:
        preview = redact_sensitive(item.content[:200]) + ("..." if len(item.content) > 200 else "")
        table.add_row(
            str(row_num),
            f"V1: {item.category}",
            item.key,
            preview,
        )
        row_num += 1

    for r in results:
        preview = redact_sensitive(r.content[:200]) + ("..." if len(r.content) > 200 else "")
        table.add_row(
            str(row_num),
            f"{r.score:.4f}",
            r.source or "-",
            preview,
        )
        row_num += 1

    console.print(table)


@memory.command()
@click.option(
    "--backend",
    "-b",
    default=None,
    help="Override the default memory backend.",
)
def stats(backend: str | None) -> None:
    """Show memory store statistics."""
    console = Console()
    svc = MemoryService.get_instance()
    v1_items = svc.list_memories(limit=1000)

    mem = _get_backend(backend)
    try:
        count = 0
        if hasattr(mem, "count"):
            count = mem.count()

        table = Table(title="Memory Statistics")
        table.add_column("Property", style="cyan")
        table.add_column("Value")
        table.add_row("Backend", mem.backend_id)
        table.add_row("V1 Memories Count", str(len(v1_items)))
        table.add_row("Vector Documents", str(count))

        if hasattr(svc.store, "db_path") and svc.store.db_path.exists():
            size_kb = svc.store.db_path.stat().st_size / 1024
            table.add_row("V1 Database Size", f"{size_kb:.1f} KB")
            table.add_row("V1 Database Path", str(svc.store.db_path))

        console.print(table)
    finally:
        if hasattr(mem, "close"):
            mem.close()


@memory.command(name="remember")
@click.argument("text")
@click.option("--category", "-c", default="knowledge", type=click.Choice(["knowledge", "project", "preference", "session"]), help="Memory category")
@click.option("--key", "-k", default=None, help="Custom unique memory key")
@click.option("--project", "-p", default=None, help="Project name association")
def remember_cmd(text: str, category: str, key: str | None, project: str | None) -> None:
    """Remember a new memory entry."""
    console = Console()
    svc = MemoryService.get_instance()
    try:
        item = svc.remember(content=text, category=category, key=key, project_name=project)  # type: ignore[arg-type]
        console.print("[green]Memory stored successfully![/green]")
        console.print(f"  ID       : [cyan]{item.id}[/cyan]")
        console.print(f"  Key      : [cyan]{item.key}[/cyan]")
        console.print(f"  Category : {item.category}")
        if item.project_name:
            console.print(f"  Project  : {item.project_name}")
        console.print(f"  Content  : {redact_sensitive(item.content)}")
    except Exception as exc:
        console.print(f"[red]Error storing memory:[/red] {exc}")


@memory.command(name="list")
@click.option("--category", "-c", default=None, help="Filter by memory category")
@click.option("--project", "-p", default=None, help="Filter by project name")
@click.option("--limit", "-n", default=50, type=int, help="Limit maximum items")
def list_cmd(category: str | None, project: str | None, limit: int) -> None:
    """List memory items."""
    console = Console()
    svc = MemoryService.get_instance()
    items = svc.list_memories(category=category, project_name=project, limit=limit)

    if not items:
        console.print("[yellow]No memory items found.[/yellow]")
        return

    table = Table(title="Stored Memories")
    table.add_column("ID", style="dim", width=12)
    table.add_column("Key", style="cyan")
    table.add_column("Category", width=12)
    table.add_column("Project", width=14)
    table.add_column("Content")

    for item in items:
        preview = redact_sensitive(item.content[:100]) + ("..." if len(item.content) > 100 else "")
        table.add_row(
            item.id,
            item.key,
            item.category,
            item.project_name or "-",
            preview,
        )

    console.print(table)


@memory.command(name="show")
@click.argument("id_or_key")
def show_cmd(id_or_key: str) -> None:
    """Show details of a specific memory item."""
    console = Console()
    svc = MemoryService.get_instance()
    item = svc.recall(id_or_key)

    if not item:
        console.print(f"[yellow]Memory item '{id_or_key}' not found.[/yellow]")
        return

    console.print(f"🔍 [bold]Memory Details: {item.key}[/bold]")
    console.print(f"  ID          : {item.id}")
    console.print(f"  Key         : {item.key}")
    console.print(f"  Category    : {item.category}")
    console.print(f"  Project     : {item.project_name or 'N/A'}")
    console.print(f"  Confidence  : {item.confidence}")
    console.print(f"  Access Count: {item.access_count}")
    console.print(f"  Created At  : {time.ctime(item.created_at)}")
    console.print(f"  Updated At  : {time.ctime(item.updated_at)}")
    console.print(f"  Content     :\n{redact_sensitive(item.content)}")


@memory.command(name="update")
@click.argument("id_or_key")
@click.argument("text")
def update_cmd(id_or_key: str, text: str) -> None:
    """Update content of an existing memory item."""
    console = Console()
    svc = MemoryService.get_instance()
    try:
        updated = svc.update(id_or_key, content=text)
        if not updated:
            console.print(f"[yellow]Memory item '{id_or_key}' not found.[/yellow]")
            return
        console.print(f"[green]Memory item '{updated.key}' updated successfully.[/green]")
    except Exception as exc:
        console.print(f"[red]Error updating memory:[/red] {exc}")


@memory.command(name="delete")
@click.argument("id_or_key")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def delete_cmd(id_or_key: str, yes: bool) -> None:
    """Delete a memory item."""
    console = Console()
    if not yes:
        click.confirm(f"Are you sure you want to delete memory '{id_or_key}'?", abort=True)

    svc = MemoryService.get_instance()
    success = svc.delete(id_or_key)
    if success:
        console.print(f"[green]Memory item '{id_or_key}' deleted.[/green]")
    else:
        console.print(f"[yellow]Memory item '{id_or_key}' not found.[/yellow]")


@memory.command(name="clear")
@click.option("--category", "-c", default=None, help="Category to clear")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def clear_cmd(category: str | None, yes: bool) -> None:
    """Clear memories (requires confirmation)."""
    console = Console()
    target_desc = f"all memories in category '{category}'" if category else "ALL stored memories"
    if not yes:
        click.confirm(f"⚠️  Are you sure you want to clear {target_desc}?", abort=True)

    svc = MemoryService.get_instance()
    count = svc.clear(category=category, confirm=True)
    console.print(f"[green]Cleared {count} memory items.[/green]")


@memory.command(name="preferences")
@click.option("--set", "set_pair", nargs=2, metavar="KEY VALUE", help="Set preference key and value")
def preferences_cmd(set_pair: tuple[str, str] | None) -> None:
    """List or set user preferences."""
    console = Console()
    svc = MemoryService.get_instance()

    if set_pair:
        pkey, pval = set_pair
        svc.preferences.set_preference(pkey, pval)
        console.print(f"[green]Preference '{pkey}' set to '{pval}'.[/green]")
        return

    prefs = svc.preferences.list_all_preferences()
    table = Table(title="User Preferences")
    table.add_column("Preference Key", style="cyan")
    table.add_column("Value")

    for k, v in prefs.items():
        table.add_row(k, v)

    console.print(table)


@memory.command(name="projects")
def projects_cmd() -> None:
    """List tracked project memories."""
    console = Console()
    svc = MemoryService.get_instance()
    projects = svc.projects.list_projects()

    if not projects:
        console.print("[yellow]No tracked project memories found.[/yellow]")
        return

    table = Table(title="Tracked Projects")
    table.add_column("Project", style="cyan")
    table.add_column("Path")
    table.add_column("Latest Feature")
    table.add_column("Next Task")

    for p in projects:
        table.add_row(
            p.get("project_name", "-"),
            p.get("path") or "-",
            p.get("latest_feature") or "-",
            p.get("next_task") or "-",
        )

    console.print(table)
