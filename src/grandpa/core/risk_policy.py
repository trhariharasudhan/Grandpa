"""What may run without a question when the *user* asked for it in words.

The catalogue rates ``browser_open`` and ``browser_search`` as needing a yes,
because a *model* choosing to open a web address on its own is a real risk
(a page it was tricked into visiting). When the user says "open Chrome" or
"search YouTube for Tamil songs", the user *is* the yes -- asking again only
taught Captain that Grandpa "asks for everything" and got in the way of
voice. So, for a request parsed from the user's own words:

* these run without asking: opening the browser, a search page on a known
  engine, an ``http(s)`` address the user said;
* everything else keeps its catalogue rule -- closing apps (unsaved work),
  lock, shutdown, restart, delete, send.

A model's own choice never goes through here: the tool loop keeps asking.
"""

from __future__ import annotations

from typing import Any, Mapping

USER_SAID_IT_ACTIONS = frozenset({"browser_open", "browser_search"})


def user_request_needs_no_question(action: str, parameters: Mapping[str, Any]) -> bool:
    if action not in USER_SAID_IT_ACTIONS:
        return False
    url = str(parameters.get("url") or "").strip().lower()
    return not url or url.startswith(("https://", "http://"))


__all__ = ["USER_SAID_IT_ACTIONS", "user_request_needs_no_question"]
