"""Local document storage and retrieval primitives."""

from __future__ import annotations

from grandpa.connectors._stubs import Attachment, BaseConnector, Document, SyncStatus


def __getattr__(name: str):
    if name == "KnowledgeStore":
        from grandpa.connectors.store import KnowledgeStore

        return KnowledgeStore
    raise AttributeError(name)


__all__ = ["Attachment", "BaseConnector", "Document", "KnowledgeStore", "SyncStatus"]
