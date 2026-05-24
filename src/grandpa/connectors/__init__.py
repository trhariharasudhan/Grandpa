"""Data source connectors for Deep Research."""

from grandpa.connectors._stubs import (
    Attachment,
    BaseConnector,
    Document,
    SyncStatus,
)
from grandpa.connectors.store import KnowledgeStore

__all__ = ["Attachment", "BaseConnector", "Document", "KnowledgeStore", "SyncStatus"]

# Auto-register built-in connectors
import grandpa.connectors.obsidian  # noqa: F401

try:
    import grandpa.connectors.gmail  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.gmail_imap  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.gdrive  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

try:
    import grandpa.connectors.notion  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.granola  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.gcontacts  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.imessage  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.apple_notes  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.apple_music  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.apple_contacts  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.slack_connector  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.outlook  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.gcalendar  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.dropbox  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

try:
    import grandpa.connectors.whatsapp  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.oura  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.apple_health  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.strava  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.spotify  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.google_tasks  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.weather  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.github_notifications  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.hackernews  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.connectors.news_rss  # noqa: F401
except ImportError:
    pass
