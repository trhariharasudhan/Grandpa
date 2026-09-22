"""Web search, Jarvis routing and the automation click confirmation."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

import pytest

from tests.e2e.harness import CouldNotRun

# ...and out of the default-deny actuation fixture (tests/actuation_guard.py).
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.real_actions(
        reason="runs the real CLI as a subprocess in a throwaway sandbox, which is what this suite is for; the sandbox has its own HOME and the harness records launches and window actions instead of performing them"
    ),
]


# 18 --------------------------------------------------------------------------
def test_search_web_returns_live_results_and_caches_them(cli) -> None:
    try:
        urllib.request.urlopen("https://duckduckgo.com/", timeout=10).close()
    except (urllib.error.URLError, OSError) as exc:
        raise CouldNotRun(f"duckduckgo.com is unreachable from this machine: {exc}")

    status = cli("search", "status")
    assert "duckduckgo" in status.text.lower(), status.text

    ran = cli("search", "web", "python packaging user guide")

    if re.search(r"rate limit|timed out|unreachable", ran.text, re.I):
        raise CouldNotRun(f"the search provider did not answer: {ran.tail()}")
    assert ran.returncode == 0, ran.text
    urls = re.findall(r"^\s+(https?://\S+)$", ran.stdout, re.M)
    assert urls, f"no result URLs printed: {ran.tail(600)}"
    match = re.search(r"Found (\d+) relevant source", ran.text)
    assert match and int(match.group(1)) == len(urls), ran.text
    cached = [
        path.read_text(encoding="utf-8")
        for path in (cli.grandpa_home / "cache" / "web_search").glob("*.json")
    ]
    assert cached, "search printed results but wrote no cache entry"
    assert all(url in "".join(cached) for url in urls), (
        "printed URLs are not the ones the provider returned"
    )


# 19 --------------------------------------------------------------------------
def test_jarvis_routes_its_one_intent_and_refuses_everything_else(cli) -> None:
    """PARTIAL: the router knows exactly one intent. Everything else must fail loudly."""
    routed = cli(
        "jarvis", "--dry-run", "open", "my", "Grandpa", "project", "in", "vscode"
    )

    assert routed.returncode == 0, routed.text
    action = json.loads(routed.stdout[routed.stdout.index("{") :])
    assert action["action_type"] == "open_app" and action["target"] == "vscode", action
    assert action["dry_run"] is True

    for phrase in ("turn up the volume", "shut down the computer"):
        refused = cli("jarvis", "--dry-run", *phrase.split())
        assert refused.returncode == 1, (
            f"{phrase!r} exited {refused.returncode}: {refused.text}"
        )
        assert "I don't know how to route that Jarvis command" in refused.text, (
            refused.text
        )
        assert "{" not in refused.stdout, (
            f"{phrase!r} produced an action: {refused.text}"
        )


# 20 --------------------------------------------------------------------------
@pytest.mark.skipif(os.name != "nt", reason="Screen automation is Windows-only")
def test_automation_click_prompts_and_sends_nothing_when_declined(cli) -> None:
    import ctypes
    from ctypes import wintypes

    def cursor() -> tuple[int, int]:
        point = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            raise CouldNotRun("GetCursorPos failed: no interactive desktop")
        return point.x, point.y

    # A sent click leaves the cursor exactly on its target. Equality with the
    # starting position is not asserted: a person may be using the mouse.
    start = cursor()
    x, y = (
        (start[0] + 37, start[1] + 29)
        if start[0] < 400
        else (start[0] - 37, start[1] - 29)
    )

    # Answer "n" even here: a regression must never click on the real desktop.
    unfocused = cli("automation", "click", "--x", str(x), "--y", str(y), stdin="n\n")
    assert "No input was sent" in unfocused.text or "cancelled" in unfocused.text, (
        unfocused.text
    )
    assert cursor() != (x, y), "the cursor is on the click target: input was sent"

    # "Program Manager" is the desktop shell window, present on any Windows desktop.
    declined = cli(
        "automation",
        "click",
        "--x",
        str(x),
        "--y",
        str(y),
        "--window",
        "Program Manager",
        stdin="n\n",
    )

    # Two ways this machine's desktop can refuse to host the probe: the shell
    # window is not there at all, or something else has focus so the CLI will
    # not confirm it as active. Neither says anything about the confirmation
    # prompt, which is what the test is here to check.
    unreachable = (
        "could not find an open",
        "could not be confirmed as the active window",
    )
    if any(reason in declined.text.lower() for reason in unreachable):
        raise CouldNotRun(
            f"no focusable desktop shell window to target: {declined.tail()}"
        )
    assert "Continue? [y/N]" in declined.text, (
        f"no confirmation prompt: {declined.text}"
    )
    assert "Automation action cancelled" in declined.text, declined.text
    assert cursor() != (x, y), "the cursor is on the click target: input was sent"
