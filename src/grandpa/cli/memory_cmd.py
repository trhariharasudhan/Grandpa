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

    mem = None
    results = []
    try:
        mem = _get_backend(backend)
        results = mem.retrieve(query_text, top_k=top_k)
    except Exception:
        pass
    finally:
        if mem is not None and hasattr(mem, "close"):
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
        preview = redact_sensitive(item.content[:200]) + (
            "..." if len(item.content) > 200 else ""
        )
        table.add_row(
            str(row_num),
            f"V1: {item.category}",
            item.key,
            preview,
        )
        row_num += 1

    for r in results:
        preview = redact_sensitive(r.content[:200]) + (
            "..." if len(r.content) > 200 else ""
        )
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

    mem = None
    count = 0
    backend_id = "sqlite"
    try:
        mem = _get_backend(backend)
        if hasattr(mem, "count"):
            count = mem.count()
        backend_id = getattr(mem, "backend_id", "sqlite")
    except Exception:
        pass
    finally:
        if mem is not None and hasattr(mem, "close"):
            mem.close()

    table = Table(title="Memory Statistics")
    table.add_column("Property", style="cyan")
    table.add_column("Value")
    table.add_row("Backend", backend_id)
    table.add_row("V1 Memories Count", str(len(v1_items)))
    table.add_row("Vector Documents", str(count))

    if hasattr(svc.store, "db_path") and svc.store.db_path.exists():
        size_kb = svc.store.db_path.stat().st_size / 1024
        table.add_row("V1 Database Size", f"{size_kb:.1f} KB")
        table.add_row("V1 Database Path", str(svc.store.db_path))

    console.print(table)


@memory.command(name="remember")
@click.argument("text")
@click.option(
    "--category",
    "-c",
    default="knowledge",
    type=click.Choice(["knowledge", "project", "preference", "session"]),
    help="Memory category",
)
@click.option("--key", "-k", default=None, help="Custom unique memory key")
@click.option("--project", "-p", default=None, help="Project name association")
def remember_cmd(
    text: str, category: str, key: str | None, project: str | None
) -> None:
    """Remember a new memory entry."""
    console = Console()
    svc = MemoryService.get_instance()
    try:
        item = svc.remember(
            content=text, category=category, key=key, project_name=project
        )  # type: ignore[arg-type]
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
        preview = redact_sensitive(item.content[:100]) + (
            "..." if len(item.content) > 100 else ""
        )
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
        console.print(
            f"[green]Memory item '{updated.key}' updated successfully.[/green]"
        )
    except Exception as exc:
        console.print(f"[red]Error updating memory:[/red] {exc}")


@memory.command(name="delete")
@click.argument("id_or_key")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def delete_cmd(id_or_key: str, yes: bool) -> None:
    """Delete a memory item."""
    console = Console()
    if not yes:
        click.confirm(
            f"Are you sure you want to delete memory '{id_or_key}'?", abort=True
        )

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
    target_desc = (
        f"all memories in category '{category}'" if category else "ALL stored memories"
    )
    if not yes:
        click.confirm(f"⚠️  Are you sure you want to clear {target_desc}?", abort=True)

    svc = MemoryService.get_instance()
    count = svc.clear(category=category, confirm=True)
    console.print(f"[green]Cleared {count} memory items.[/green]")


@memory.command(name="preferences")
@click.option(
    "--set",
    "set_pair",
    nargs=2,
    metavar="KEY VALUE",
    help="Set preference key and value",
)
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


@memory.command(name="recent")
@click.option("--limit", "-n", default=10, type=int, help="Limit number of items")
def recent_cmd(limit: int) -> None:
    """Show recent memories across all categories."""
    console = Console()
    svc = MemoryService.get_instance()
    items = svc.list_memories(limit=limit)

    if not items:
        console.print("[yellow]No recent memory items found.[/yellow]")
        return

    table = Table(title="Recent Memories")
    table.add_column("Key", style="cyan")
    table.add_column("Category", width=12)
    table.add_column("Updated", width=20)
    table.add_column("Content")

    for item in items:
        preview = redact_sensitive(item.content[:80])
        table.add_row(
            item.key,
            item.category,
            time.ctime(item.updated_at),
            preview,
        )

    console.print(table)


@memory.command(name="relevant")
@click.argument("query")
@click.option("--project", "-p", default=None, help="Project name context")
def relevant_cmd(query: str, project: str | None) -> None:
    """Retrieve bounded relevant memories for a query context."""
    console = Console()
    svc = MemoryService.get_instance()
    items = svc.retrieve_relevant(query=query, project_name=project, limit=5)

    if not items:
        console.print(
            f"[yellow]No relevant memory items found for query '{query}'.[/yellow]"
        )
        return

    table = Table(title=f"Relevant Memories for '{query}'")
    table.add_column("Key", style="cyan")
    table.add_column("Category", width=12)
    table.add_column("Content")

    for item in items:
        table.add_row(item.key, item.category, redact_sensitive(item.content[:100]))

    console.print(table)


@memory.command(name="project")
@click.argument("name")
def project_cmd(name: str) -> None:
    """Show project-specific memory details."""
    console = Console()
    svc = MemoryService.get_instance()

    clean_name = name.strip().lower().replace(" ", "_")
    items = svc.list_memories(category="project", project_name=name, limit=100)

    if not items:
        # Fallback to key-prefix search
        all_proj_items = svc.list_memories(category="project", limit=100)
        items = [
            item
            for item in all_proj_items
            if (item.project_name and item.project_name.lower() == name.lower())
            or item.key.startswith(f"proj_{clean_name}")
        ]

    if not items:
        console.print(f"[yellow]No memory found for project '{name}'.[/yellow]")
        return

    summary_val = "N/A"
    path_val = "N/A"
    feature_val = "N/A"
    commit_val = "N/A"
    next_task_val = "N/A"
    failed_plan_val = "N/A"

    for item in items:
        k = item.key.lower()
        content = item.content
        meta = item.metadata or {}

        # Set values from metadata if they exist
        if meta.get("project_path"):
            path_val = meta["project_path"]
        if meta.get("latest_feature"):
            feature_val = meta["latest_feature"]
        if meta.get("latest_commit"):
            commit_val = meta["latest_commit"]
        if meta.get("next_task"):
            next_task_val = meta["next_task"]
        if meta.get("last_failed_plan"):
            failed_plan_val = meta["last_failed_plan"]

        # Check explicit keys or suffixes
        if k == "project_path" or k.endswith("_path") or k.endswith("_project_path"):
            path_val = content
        elif (
            k == "latest_feature"
            or k.endswith("_latest_feature")
            or k.endswith("_feature")
        ):
            feature_val = content
        elif (
            k == "latest_commit"
            or k.endswith("_latest_commit")
            or k.endswith("_commit")
        ):
            commit_val = content
        elif k == "next_task" or k.endswith("_next_task"):
            next_task_val = content
        elif k == "last_failed_plan" or k.endswith("_last_failed_plan"):
            failed_plan_val = content
        elif (
            k == f"proj_{clean_name}_summary"
            or k == "summary"
            or k.endswith("_summary")
        ):
            summary_val = content
        else:
            if summary_val == "N/A":
                summary_val = content

    console.print(f"📁 [bold]Project Memory: {name}[/bold]")
    console.print(f"  Summary       : {summary_val}")
    console.print(f"  Path          : {path_val}")
    console.print(f"  Latest Feature: {feature_val}")
    console.print(f"  Latest Commit : {commit_val}")
    console.print(f"  Next Task     : {next_task_val}")
    console.print(f"  Failed Plan   : {failed_plan_val}")


@memory.command(name="explain")
@click.argument("query")
@click.option("--project", "-p", default=None, help="Project name context")
def explain_cmd(query: str, project: str | None) -> None:
    """Explain why memories were matched and ranked for a query."""
    console = Console()
    svc = MemoryService.get_instance()
    explanation = svc.explain_retrieval(query, project_name=project)

    console.print(f"🔍 [bold]Memory Retrieval Explanation for '{query}'[/bold]")
    console.print(f"  Matched Count : {explanation['matched_count']}")

    for match in explanation["matches"]:
        console.print(f"\n  • Key: [cyan]{match['key']}[/cyan] ({match['category']})")
        console.print(f"    Reasons : {', '.join(match['reasons'])}")
        console.print(f"    Preview : {match['content_preview']}")


@memory.command(name="session")
@click.argument("action", type=click.Choice(["status", "clear", "promote"]))
@click.argument("key", required=False)
def session_cmd(action: str, key: str | None) -> None:
    """Manage short-term session memory."""
    console = Console()
    svc = MemoryService.get_instance()

    if action == "status":
        memories = svc.short_term.get_session_memories()
        enabled = svc.session_memory_enabled()
        console.print(
            f"⚡ [bold]Session Memory Status:[/bold] {'[green]ENABLED[/green]' if enabled else '[red]DISABLED[/red]'}"
        )
        console.print(f"  Buffered Items : {len(memories)}")
        for m in memories:
            console.print(f"  - [{m.key}] {redact_sensitive(m.content[:80])}")

    elif action == "clear":
        svc.short_term.clear()
        console.print("[green]Session memory cleared.[/green]")

    elif action == "promote":
        if not key:
            console.print(
                "[yellow]Please specify a key to promote from session memory.[/yellow]"
            )
            return
        promoted = svc.short_term.promote(key, svc.store)
        if promoted:
            console.print(
                f"[green]Session memory '{key}' promoted to long-term knowledge.[/green]"
            )
        else:
            console.print(
                f"[yellow]Key '{key}' not found in current session memory.[/yellow]"
            )


@memory.command(name="disable")
def disable_cmd() -> None:
    """Disable memory retrieval for current session."""
    console = Console()
    svc = MemoryService.get_instance()
    svc.set_session_memory_enabled(False)
    console.print("🛑 [yellow]Memory retrieval DISABLED for current session.[/yellow]")


@memory.command(name="enable")
def enable_cmd() -> None:
    """Enable memory retrieval for current session."""
    console = Console()
    svc = MemoryService.get_instance()
    svc.set_session_memory_enabled(True)
    console.print("✅ [green]Memory retrieval ENABLED for current session.[/green]")
