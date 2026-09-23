"""File-search phrases are not claimed by screen automation or Google search.

In chat, "find files named X" was taken by Screen Automation V2 ("could not find
... on the visible screen") and "search my files for X" by local_actions, which
opened a Google search. Neither reached the file assistant.
"""

from __future__ import annotations

import pytest

from grandpa.automation.planner import AutomationPlanner
from grandpa.files.parser import FileParser
from grandpa.local.parsers import _parse_browser_action
from grandpa.local.router import _prefer_deterministic_browser_route


@pytest.mark.parametrize(
    "phrase",
    [
        "find files named quarterly",
        "find the file named quarterly",
        "find my files called quarterly",
        "find documents about taxes",
        "find files",
    ],
)
def test_screen_automation_does_not_claim_file_searches(phrase) -> None:
    assert AutomationPlanner().parse(phrase) is None


@pytest.mark.parametrize(
    ("phrase", "target"),
    [("find the file menu", "file menu"), ("find the OK button", "ok")],
)
def test_screen_automation_still_locates_visible_controls(phrase, target) -> None:
    action = AutomationPlanner().parse(phrase)

    assert action is not None and action.kind == "locate"
    assert action.target == target


@pytest.mark.parametrize(
    ("phrase", "query"),
    [
        ("find files named quarterly", "quarterly"),
        ("find the file called q3 report", "q3 report"),
        ("search for files named budget", "budget"),
        ("search my files for quarterly", "quarterly"),
        ("search all files for invoices", "invoices"),
        ("find report.pdf", "report.pdf"),
    ],
)
def test_file_parser_extracts_the_name_being_searched_for(phrase, query) -> None:
    action = FileParser().parse(phrase)

    assert action is not None and action.action == "search"
    assert action.query == query


def test_search_my_files_is_not_a_google_search() -> None:
    assert not _prefer_deterministic_browser_route("search my files for quarterly")
    assert _parse_browser_action("search my files for quarterly").status != "handled"


def test_other_search_phrases_are_still_google_searches() -> None:
    result = _parse_browser_action("search python tutorials")

    assert _prefer_deterministic_browser_route("search python tutorials")
    assert result.status == "handled"
    assert result.target == "https://www.google.com/search?q=python+tutorials"
