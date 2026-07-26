"""Data source connectors with on-demand built-in registration."""

from __future__ import annotations

import importlib
import logging

from grandpa.connectors._stubs import Attachment, BaseConnector, Document, SyncStatus

logger = logging.getLogger(__name__)
_BUILTINS = (
    "obsidian", "gmail", "gmail_imap", "gdrive", "notion", "granola",
    "gcontacts", "imessage", "apple_notes", "apple_music", "apple_contacts",
    "slack_connector", "outlook", "gcalendar", "dropbox", "whatsapp", "oura",
    "apple_health", "strava", "spotify", "google_tasks", "weather",
    "github_notifications", "hackernews", "news_rss",
)
_builtins_loaded = False


def load_builtin_connectors() -> None:
    """Import connector implementations once to populate their registry."""
    global _builtins_loaded
    if _builtins_loaded:
        return
    for module in _BUILTINS:
        try:
            importlib.import_module(f"grandpa.connectors.{module}")
        except ImportError as exc:
            logger.debug("Optional connector %s unavailable: %s", module, exc)
    _builtins_loaded = True


def __getattr__(name: str):
    if name == "KnowledgeStore":
        from grandpa.connectors.store import KnowledgeStore
        return KnowledgeStore
    raise AttributeError(name)


__all__ = ["Attachment", "BaseConnector", "Document", "KnowledgeStore", "SyncStatus", "load_builtin_connectors"]
