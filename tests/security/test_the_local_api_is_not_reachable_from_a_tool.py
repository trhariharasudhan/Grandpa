"""The model's HTTP tool cannot reach Grandpa's own API.

This is a named dependency, not a general SSRF test. The escalation report for
the saved-skill hole concluded that a model cannot author a user skill, and
said plainly that *that conclusion rests entirely on the SSRF guard*: nothing
else stood between `http_request` and `POST /v1/user-skills/create`. A saved
skill is deferred execution with nobody present when it runs, so the reasoning
that keeps a model from writing one has to be pinned where it can fail loudly.

``tests/security/test_ssrf.py`` already covers the guard's own behaviour
thoroughly. What it does not cover is the tool: that `http_request` consults
the guard at all, refuses before any socket is opened, and refuses the
specific endpoints that author or run a skill. Those are the properties this
file pins, so loosening the guard -- or dropping the call to it -- fails here
with the reason stated.

Defence in depth: the endpoint now validates its own params too
(tests/security/test_the_create_endpoint_validates_its_own_params.py), so this
guard is no longer the only thing standing there. Both are required.
"""

from __future__ import annotations

import pytest

LOCAL_API_URLS = [
    "http://127.0.0.1:8000/v1/user-skills/create",
    "http://localhost:8000/v1/user-skills/create",
    "http://[::1]:8000/v1/user-skills/create",
    "http://127.0.0.1:8000/v1/user-skills/abc123/run",
    "http://0.0.0.0:8000/v1/agent-runtime/goals",
]


def _tool():
    from grandpa.tools.http_request import HttpRequestTool

    return HttpRequestTool()


@pytest.mark.parametrize("url", LOCAL_API_URLS)
def test_the_tool_refuses_grandpas_own_api(url: str) -> None:
    result = _tool().execute(url=url, method="POST", body='{"name": "x"}')

    assert result.success is False
    assert "SSRF protection blocked request" in result.content


def test_the_refusal_happens_before_any_socket_is_opened(monkeypatch) -> None:
    """A guard that refuses *after* the request has gone is not a guard.

    Both backends are replaced: the Rust one, and the urllib path the pure
    Python fallback uses. If either is reached, the test says which.
    """
    import grandpa.tools.http_request as module

    def _no(*_args, **_kwargs):
        raise AssertionError("a request was sent to a loopback address")

    monkeypatch.setattr(module, "get_rust_module", _no, raising=False)
    monkeypatch.setattr("urllib.request.urlopen", _no)
    monkeypatch.setattr("urllib.request.build_opener", _no, raising=False)

    result = _tool().execute(url="http://127.0.0.1:8000/v1/user-skills/create")

    assert result.success is False
    assert "SSRF protection blocked request" in result.content


def test_the_tool_actually_consults_the_guard(monkeypatch) -> None:
    """Pins the call, not just today's outcome.

    Without this, deleting the ``check_ssrf`` call and hard-coding a refusal
    for loopback would pass every other test here while leaving every other
    private address reachable.
    """
    import grandpa.tools.http_request as module

    asked: list[str] = []

    def _record(url: str):
        asked.append(url)
        return "recorded refusal"

    monkeypatch.setattr(module, "check_ssrf", _record)

    result = _tool().execute(url="http://example.com/")

    assert asked == ["http://example.com/"]
    assert result.success is False


def test_the_guard_still_rejects_loopback() -> None:
    """The one-line property the report's conclusion rested on."""
    from grandpa.security.ssrf import check_ssrf

    for url in (
        "http://127.0.0.1:8000/",
        "http://[::1]:8000/",
        "http://0.0.0.0:8000/",
    ):
        assert check_ssrf(url) is not None, f"{url} is no longer rejected"


def test_every_tool_that_fetches_a_url_consults_the_guard() -> None:
    """The guard is only as good as the set of tools that call it.

    A new URL-fetching tool that forgets it would reopen this path, so the
    check is over the modules rather than over one of them.
    """
    import inspect

    from grandpa.tools import browser, http_request, web_search

    for module in (http_request, web_search, browser):
        assert "check_ssrf" in inspect.getsource(module), (
            f"{module.__name__} fetches URLs without consulting check_ssrf"
        )
