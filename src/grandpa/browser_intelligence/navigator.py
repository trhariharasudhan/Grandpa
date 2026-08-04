"""Smart navigator integrating DOM reading, link resolution, source verification, and browser control."""

from __future__ import annotations

from typing import Any

from grandpa.browser_control import execute_browser_action
from grandpa.browser_intelligence.link_resolver import resolve_target_link
from grandpa.browser_intelligence.page_reader import read_current_browser_page
from grandpa.browser_intelligence.source_verifier import verify_source


class SmartNavigator:
    """Intelligent navigation controller reusing safe visible-browser actions."""

    def open_url(self, url: str) -> dict[str, Any]:
        """Navigate visible browser to specified URL."""
        res = execute_browser_action("navigate", target=url)
        verification = verify_source(url)
        return {
            "status": res.status,
            "action": "navigate",
            "url": url,
            "verification": verification.to_dict(),
            "message": res.message,
        }

    def search_and_open_official(self, query: str) -> dict[str, Any]:
        """Perform search and navigate to the top verified official source result."""
        # Execute search action via browser control
        res = execute_browser_action("search", target=query)

        # Read current browser page
        page = read_current_browser_page()
        resolved = resolve_target_link(page, f"official {query}")

        if resolved and resolved.get("type") == "url":
            target_url = resolved["target"]
            nav_res = self.open_url(target_url)
            return {
                "status": "handled",
                "query": query,
                "navigated_to": target_url,
                "is_official": resolved.get("is_official", False),
                "message": f"Searched for '{query}' and navigated to official result: {target_url}",
                "details": nav_res,
            }

        return {
            "status": "handled",
            "query": query,
            "message": f"Searched for '{query}'. Visible search results ready.",
            "search_result": res.message,
        }

    def smart_navigate(self, goal_target: str) -> dict[str, Any]:
        """Intelligently resolve and execute navigation goal (e.g. 'Go to Installation')."""
        page = read_current_browser_page()
        resolved = resolve_target_link(page, goal_target)

        if not resolved:
            return {
                "status": "unsupported",
                "goal": goal_target,
                "message": f"Could not resolve target '{goal_target}' on current page.",
            }

        rtype = resolved.get("type")
        target_val = resolved.get("target", "")

        if rtype == "url":
            return self.open_url(target_val)
        elif rtype == "button":
            res = execute_browser_action("click", target=target_val)
            return {
                "status": res.status,
                "action": "click",
                "target": target_val,
                "message": res.message,
            }
        elif rtype == "heading":
            res = execute_browser_action("scroll", target="down")
            return {
                "status": res.status,
                "action": "scroll",
                "target": target_val,
                "message": f"Scrolled page towards heading '{target_val}'.",
            }

        return {
            "status": "handled",
            "goal": goal_target,
            "resolved": resolved,
            "message": f"Resolved target '{goal_target}'.",
        }

    def scroll_until_heading(
        self, heading_name: str, max_attempts: int = 5
    ) -> dict[str, Any]:
        """Scroll visible page until specified heading is reached."""
        for attempt in range(1, max_attempts + 1):
            page = read_current_browser_page()
            for h in page.headings:
                if heading_name.lower() in h.text.lower():
                    return {
                        "status": "handled",
                        "heading": h.text,
                        "attempts": attempt,
                        "message": f"Found heading '{h.text}' after {attempt} scroll(s).",
                    }
            execute_browser_action("scroll", target="down")
        return {
            "status": "partially_handled",
            "heading": heading_name,
            "attempts": max_attempts,
            "message": f"Scrolled {max_attempts} times, heading '{heading_name}' not yet visible.",
        }
