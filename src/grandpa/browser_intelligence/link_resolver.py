"""Link resolver for semantic target resolution on browser pages."""

from __future__ import annotations

from typing import Any

from grandpa.browser_intelligence.models import PageContent
from grandpa.browser_intelligence.page_analyzer import extract_search_results_from_page
from grandpa.browser_intelligence.source_verifier import _KNOWN_OFFICIAL_DOMAINS


def resolve_target_link(
    page: PageContent,
    goal_target: str,
) -> dict[str, Any] | None:
    """Resolve a semantic goal target (e.g. 'Installation', 'official FastAPI docs') to a URL or element name."""
    target_clean = goal_target.strip().lower()

    if target_clean.startswith("http://") or target_clean.startswith("https://"):
        return {
            "type": "url",
            "target": goal_target.strip(),
            "title": goal_target.strip(),
            "domain": goal_target.split("/")[2] if "/" in goal_target else "",
            "is_official": True,
        }

    # 1. Check if target matches known official domain registry directly
    for key, official_domains in _KNOWN_OFFICIAL_DOMAINS.items():
        if key in target_clean:
            official_url = "https://" + official_domains[0]
            return {
                "type": "url",
                "target": official_url,
                "title": f"Official {key.title()} Documentation",
                "domain": official_domains[0],
                "is_official": True,
            }

    # 2. Direct search result request on search engine pages ("first official result", "official docs", etc.)
    if (
        "official" in target_clean
        or "result" in target_clean
        or "first" in target_clean
    ):
        search_results = extract_search_results_from_page(
            page, search_subject=goal_target
        )
        if search_results:
            if "official" in target_clean:
                official_results = [r for r in search_results if r.is_official]
                if official_results:
                    top_official = official_results[0]
                    return {
                        "type": "url",
                        "target": top_official.url,
                        "title": top_official.title,
                        "domain": top_official.domain,
                        "is_official": True,
                    }
            top = search_results[0]
            return {
                "type": "url",
                "target": top.url,
                "title": top.title,
                "domain": top.domain,
                "is_official": top.is_official,
            }

    # 3. Match navigation sections / links
    for nav in page.nav_sections:
        if not nav.text or not nav.url:
            continue
        nav_lower = nav.text.lower()
        if target_clean in nav_lower or any(
            word in nav_lower for word in target_clean.split() if len(word) > 3
        ):
            return {
                "type": "url",
                "target": nav.url,
                "title": nav.text,
                "domain": page.domain,
                "is_official": False,
            }

    # 4. Match buttons
    for btn in page.buttons:
        if target_clean in btn.lower() or any(
            word in btn.lower() for word in target_clean.split() if len(word) > 3
        ):
            return {
                "type": "button",
                "target": btn,
                "title": btn,
                "domain": page.domain,
                "is_official": False,
            }

    # 5. Match headings (for scrolling target)
    for heading in page.headings:
        if target_clean in heading.text.lower() or any(
            word in heading.text.lower()
            for word in target_clean.split()
            if len(word) > 3
        ):
            return {
                "type": "heading",
                "target": heading.text,
                "title": heading.text,
                "domain": page.domain,
                "is_official": False,
            }

    return None
