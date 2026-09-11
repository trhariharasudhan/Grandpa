"""Keyless DuckDuckGo search through the ``ddgs`` package.

The single place Grandpa calls ``ddgs``. Used by ``WebSearchClient`` (the
``grandpa search`` and chat path) and by the ``web_search`` agent tool.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_ddgs_whitespace_fix_applied = False


def _keep_whitespace_between_tags() -> None:
    """Stop ``ddgs`` gluing words together in titles and snippets.

    ddgs 9.x (``ddgs/base.py``) parses result pages with
    ``remove_blank_text=True``, which drops the whitespace-only text between
    tags, then strips every text node and joins them with "". Search engines
    wrap query words in tags, so "the <b>Python</b> <b>Packaging</b>" comes back
    as "thePythonPackaging". Nothing downstream can put the spaces back.

    This replaces those two ddgs methods with versions that keep the page's own
    whitespace. It only runs while ddgs still has its original methods; if a
    ddgs release changes them, it does nothing. Remove it once ddgs keeps
    whitespace itself.
    """
    global _ddgs_whitespace_fix_applied
    if _ddgs_whitespace_fix_applied:
        return
    try:
        from ddgs.base import BaseSearchEngine
        from lxml import html
        from lxml.etree import HTMLParser
    except ImportError:
        return
    originals = (BaseSearchEngine.extract_tree, BaseSearchEngine.extract_results)
    if any(getattr(method, "__module__", None) != "ddgs.base" for method in originals):
        logger.debug("ddgs extraction changed; not applying the whitespace fix")
        return

    parser = HTMLParser(remove_comments=True, remove_pis=True, collect_ids=False)

    def extract_tree(self: Any, html_text: str) -> Any:
        return html.fromstring(html_text, parser=parser)

    def extract_results(self: Any, html_text: str) -> list[Any]:
        tree = self.extract_tree(self.pre_process_html(html_text))
        results = []
        for item in tree.xpath(self.items_xpath):
            result = self.result_type()
            for key, xpath in self.elements_xpath.items():
                text = "".join(str(part) for part in item.xpath(xpath))
                setattr(result, key, " ".join(text.split()))
            results.append(result)
        return results

    BaseSearchEngine.extract_tree = extract_tree
    BaseSearchEngine.extract_results = extract_results
    _ddgs_whitespace_fix_applied = True


def duckduckgo_text_search(
    query: str, *, max_results: int, timelimit: str | None = None
) -> list[dict[str, str]]:
    """Return DuckDuckGo results as ``{"title", "url", "snippet"}`` dicts.

    ``timelimit`` is ddgs' recency filter (``"d"``, ``"w"``, ``"m"`` or
    ``"y"``). Raises ``ImportError`` if ``ddgs`` is missing and lets ddgs'
    own exceptions propagate so callers can map them.
    """
    from ddgs import DDGS

    _keep_whitespace_between_tags()
    kwargs: dict[str, Any] = {"max_results": max_results}
    if timelimit:
        kwargs["timelimit"] = timelimit
    raw = DDGS().text(query, **kwargs) or []
    return [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("href") or ""),
            "snippet": str(item.get("body") or ""),
        }
        for item in raw
    ]


__all__ = ["duckduckgo_text_search"]
