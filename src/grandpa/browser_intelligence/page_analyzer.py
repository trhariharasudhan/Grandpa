"""Page analyzer for extracting structured components and search results."""

from __future__ import annotations

import re
from typing import Any

from grandpa.browser_intelligence.models import (
    PageContent,
    SearchEngineResult,
    SearchEngineType,
)
from grandpa.browser_intelligence.source_verifier import extract_domain, verify_source


def detect_search_engine(url: str, title: str = "", text: str = "") -> SearchEngineType:
    """Detect search engine provider from URL, title, or visible text."""
    combined = f"{url} {title} {text}".lower()
    if "google.com" in url or "google search" in combined:
        return "google"
    if "bing.com" in url or "bing search" in combined:
        return "bing"
    if "duckduckgo.com" in url or "duckduckgo" in combined:
        return "duckduckgo"
    if "search.brave.com" in url or "brave search" in combined:
        return "brave"
    return "unknown"


def extract_search_results_from_page(
    page: PageContent,
    search_subject: str = "",
) -> tuple[SearchEngineResult, ...]:
    """Extract search engine results from parsed page content."""
    engine = detect_search_engine(page.url, page.title, page.visible_text)
    results: list[SearchEngineResult] = []

    # 1. Inspect nav_sections / links for result items
    ranking = 1
    for nav in page.nav_sections:
        if not nav.url or not nav.text:
            continue
        # Skip search engine navigation links (e.g., images, news, settings, maps)
        if any(
            k in nav.text.lower()
            for k in (
                "images",
                "videos",
                "news",
                "maps",
                "shopping",
                "books",
                "finance",
                "settings",
                "tools",
                "privacy",
                "terms",
                "sign in",
                "log in",
            )
        ):
            continue
        domain = extract_domain(nav.url)

        # Skip search engine self domains
        if domain in (
            "google.com",
            "bing.com",
            "duckduckgo.com",
            "brave.com",
            "microsoft.com/bing",
        ):
            continue

        verification = verify_source(nav.url, subject=search_subject or page.title)

        result_item = SearchEngineResult(
            title=nav.text,
            url=nav.url,
            snippet=f"Result from {domain} for {search_subject or page.title}",
            domain=domain,
            ranking=ranking,
            engine=engine,
            trust_score=verification.trust_score,
            official_score=verification.official_score,
            confidence=verification.confidence,
            is_official=verification.is_official,
        )
        results.append(result_item)
        ranking += 1
        if ranking > 15:
            break

    # 2. Fallback heuristic parsing from visible text paragraphs if no nav links found
    if not results and page.paragraphs:
        ranking = 1
        for p in page.paragraphs:
            # Look for lines formatted like: Title - https://domain.com/path - Snippet
            match = re.search(r"^(.*?)\s*[-–—|]\s*(https?://[^\s]+)(?:\s*[-–—|]\s*(.*))?$", p)
            if match:
                title = match.group(1).strip()
                url = match.group(2).strip()
                snippet = (match.group(3) or "").strip() or p
                domain = extract_domain(url)
                verification = verify_source(url, subject=search_subject)

                results.append(
                    SearchEngineResult(
                        title=title,
                        url=url,
                        snippet=snippet,
                        domain=domain,
                        ranking=ranking,
                        engine=engine,
                        trust_score=verification.trust_score,
                        official_score=verification.official_score,
                        confidence=verification.confidence,
                        is_official=verification.is_official,
                    )
                )
                ranking += 1

    return tuple(results)


def analyze_page_structure(page: PageContent) -> dict[str, Any]:
    """Analyze high-level structure and components of a parsed page."""
    search_results = extract_search_results_from_page(page)

    return {
        "title": page.title,
        "url": page.url,
        "domain": page.domain,
        "heading_count": len(page.headings),
        "heading_titles": [h.text for h in page.headings],
        "paragraph_count": len(page.paragraphs),
        "button_count": len(page.buttons),
        "buttons": list(page.buttons),
        "form_count": len(page.forms),
        "table_count": len(page.tables),
        "code_block_count": len(page.code_blocks),
        "search_result_count": len(search_results),
        "search_results": [sr.to_dict() for sr in search_results],
        "has_official_sources": any(sr.is_official for sr in search_results),
    }
