"""``Grandpa vault`` — the encrypted credential store.

Backed by :mod:`grandpa.security.secret_store` (Windows DPAPI on Windows).
The old ``vault.enc`` kept its Fernet key in ``.vault_key`` right beside it,
which protected nothing; its entries are moved into the store the first time
any vault command runs on a machine with an encrypted store, and both old files
are removed after every entry reads back.
"""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console
from rich.table import Table

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.security.secret_store import SecretStore, SecretStoreError

#: Legacy files, read once for migration only.
_VAULT_FILE = DEFAULT_CONFIG_DIR / "vault.enc"
_VAULT_KEY_FILE = DEFAULT_CONFIG_DIR / ".vault_key"


def _legacy_entries() -> dict | None:
    """Entries from the old Fernet vault, or None if there is nothing to read."""
    if not _VAULT_FILE.exists() or not _VAULT_KEY_FILE.exists():
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    try:
        key = _VAULT_KEY_FILE.read_bytes().strip()
        data = json.loads(Fernet(key).decrypt(_VAULT_FILE.read_bytes()).decode())
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def migrate_legacy_vault(store: SecretStore) -> int:
    """Move old vault.enc entries into *store*. Returns how many moved."""
    if not store.secure:
        return 0
    entries = _legacy_entries()
    if entries is None:
        return 0
    moved = 0
    for name, value in entries.items():
        try:
            store.set(str(name), str(value))
        except SecretStoreError:
            return moved  # keep the old files; nothing is lost
        if store.get(str(name)) != str(value):
            return moved
        moved += 1
    for path in (_VAULT_FILE, _VAULT_KEY_FILE):
        try:
            path.unlink()
        except OSError:
            pass
    return moved


def plaintext_leftovers() -> list[str]:
    """Credentials still in plain text on disk (names/paths only)."""
    from grandpa.calendar.auth import CALENDAR_TOKEN_PATH
    from grandpa.core.config import load_config
    from grandpa.gmail.auth import GMAIL_TOKEN_PATH

    found: list[str] = []
    try:
        if load_config().server.auth.api_key.strip():
            found.append("config.toml [server.auth] api_key")
    except Exception:
        pass
    for path in (GMAIL_TOKEN_PATH, CALENDAR_TOKEN_PATH, _VAULT_FILE):
        if path.exists():
            found.append(str(path))
    return found


def migrate_all(store: SecretStore, console: Console) -> list[str]:
    """Move every known plaintext credential into *store*. Returns what moved."""
    if not store.secure:
        return []
    from grandpa.calendar.auth import CalendarAuthManager
    from grandpa.cli.serve import _resolve_api_key
    from grandpa.core.config import load_config
    from grandpa.gmail.auth import GmailAuthManager

    moved: list[str] = []
    config = load_config()
    if config.server.auth.api_key.strip():
        _resolve_api_key(config, console)
        if not load_config().server.auth.api_key.strip():
            moved.append("server API key")
    for label, manager in (
        ("Gmail token", GmailAuthManager()),
        ("Calendar token", CalendarAuthManager()),
    ):
        legacy = manager.token_path.exists()
        manager._token.exists()  # noqa: SLF001 - exists() performs the one-time move
        if legacy and not manager.token_path.exists():
            moved.append(label)
    count = migrate_legacy_vault(store)
    if count:
        moved.append(f"{count} vault credential(s)")
    return moved


def _store(console: Console) -> SecretStore:
    store = SecretStore()
    moved = migrate_legacy_vault(store)
    if moved:
        console.print(
            f"[green]Moved {moved} credential(s) from the old vault.enc into the "
            f"{store.describe()} store.[/green]"
        )
    return store


@click.group()
def vault() -> None:
    """Manage encrypted credentials."""


@vault.command("set")
@click.argument("key")
@click.argument("value")
def vault_set(key: str, value: str) -> None:
    """Store a credential in the vault."""
    console = Console(stderr=True)
    try:
        store = _store(console)
        store.set(key, value)
        console.print(f"[green]Stored credential: {key}[/green] ({store.describe()})")
    except SecretStoreError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)


@vault.command("get")
@click.argument("key")
def vault_get(key: str) -> None:
    """Retrieve a credential from the vault."""
    console = Console(stderr=True)
    try:
        value = _store(console).get(key)
    except SecretStoreError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    if value is None:
        console.print(f"[yellow]Key not found: {key}[/yellow]")
    else:
        console.print(value, markup=False, highlight=False)


@vault.command("list")
def vault_list() -> None:
    """List stored credential names (never their values)."""
    console = Console(stderr=True)
    store = _store(console)
    names = store.names()
    if not names:
        console.print(f"[dim]Vault is empty.[/dim] Storage: {store.describe()}")
        return
    table = Table(title=f"Vault keys — {store.describe()}")
    table.add_column("Key", style="cyan")
    for name in names:
        table.add_row(name)
    console.print(table)


@vault.command("remove")
@click.argument("key")
def vault_remove(key: str) -> None:
    """Remove a credential from the vault."""
    console = Console(stderr=True)
    try:
        removed = _store(console).delete(key)
    except SecretStoreError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    if removed:
        console.print(f"[green]Removed: {key}[/green]")
    else:
        console.print(f"[yellow]Key not found: {key}[/yellow]")


@vault.command("migrate")
def vault_migrate() -> None:
    """Move plain-text credentials (API key, Google tokens, old vault) into the store."""
    console = Console(stderr=True)
    store = SecretStore()
    if not store.secure:
        console.print(
            f"[yellow]Storage is {store.describe()}; nothing was moved.[/yellow]\n"
            "  On Linux, install a keyring backend: uv pip install keyring secretstorage"
        )
        sys.exit(1)
    try:
        moved = migrate_all(store, console)
    except SecretStoreError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    left = plaintext_leftovers()
    console.print(
        f"Storage: {store.describe()}\n"
        f"Moved: {', '.join(moved) if moved else 'nothing (already done)'}\n"
        f"Still in plain text: {', '.join(left) if left else 'none'}"
    )
    if left:
        sys.exit(1)


__all__ = ["migrate_all", "migrate_legacy_vault", "plaintext_leftovers", "vault"]
