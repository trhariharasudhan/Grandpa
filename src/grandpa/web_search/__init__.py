"""Safe modular web search layer for Grandpa."""

from grandpa.web_search.automation import WebSearchAutomation, handle_web_search_command
from grandpa.web_search.client import WebSearchClient
from grandpa.web_search.models import (
    WebSearchAction,
    WebSearchQuery,
    WebSearchResponse,
    WebSearchResult,
)
from grandpa.web_search.parser import WebSearchParser
from grandpa.web_search.providers import WebSearchProviderConfig
from grandpa.web_search.safety import WebSearchSafetyPolicy

__all__ = [
    "WebSearchAction",
    "WebSearchAutomation",
    "WebSearchClient",
    "WebSearchParser",
    "WebSearchProviderConfig",
    "WebSearchQuery",
    "WebSearchResponse",
    "WebSearchResult",
    "WebSearchSafetyPolicy",
    "handle_web_search_command",
]
