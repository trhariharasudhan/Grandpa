"""V1-T10: one request, three dependent steps, through the action-layer loop.

"open Chrome, search for the weather in Chennai, and save the result to my
notes" needs three domains' tools on the first turn (apps, web, notes), a
confirmation before a browser starts, a search whose answer is carried into
the note, and a trace saying what was done. The model is a script and every
actuator is a mock, so nothing starts, searches or writes for real.

What blocked it: the whole request scored notes highest and web fell under the
runner-up ratio, so the first turn had no search tool. Each step of a compound
request now gets its own say in domain selection (``candidate_domains``).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grandpa.action_layer.catalogue import candidate_domains, get
from grandpa.action_layer.loop import run
from grandpa.action_layer.model import ActionResult

GOAL = "open Chrome, search for the weather in Chennai, and save the result to my notes"
WEATHER = "Chennai: 31 C, humid, light rain in the evening."


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    return tmp_path / "actions.jsonl"


class ScriptedModel:
    """Plays the plan a tool-using model makes, and records what it was shown."""

    def __init__(self, *turns: dict):
        self.turns = list(turns)
        self.requests: list[dict] = []

    def supports_tools(self, model: str) -> bool:
        return True

    def generate(self, messages, *, model, tools=None, temperature=0.0, **kwargs):
        self.requests.append({"tools": tools, "messages": list(messages)})
        return self.turns.pop(0) if self.turns else {"content": "Done."}


def _call(index: int, name: str, arguments: dict) -> dict:
    return {"id": f"call_{index}", "name": name, "arguments": json.dumps(arguments)}


def _plan() -> ScriptedModel:
    return ScriptedModel(
        {"content": "", "tool_calls": [_call(0, "open_app", {"app": "chrome"})]},
        {
            "content": "",
            "tool_calls": [_call(1, "web_search", {"query": "weather in Chennai"})],
        },
        {
            "content": "",
            "tool_calls": [
                _call(
                    2,
                    "notes_create",
                    {"title": "Weather in Chennai", "content": WEATHER},
                )
            ],
        },
        {
            "content": "I opened Chrome, searched for the weather in Chennai and "
            "saved it to a note called 'Weather in Chennai'."
        },
    )


class FakeLauncher:
    """Stands in for ApplicationControlService.execute.

    The real service asks before starting a browser, through the ``confirm``
    the layer hands it. This one does the same, and records whether it would
    have launched.
    """

    def __init__(self) -> None:
        self.launched: list[str] = []
        self.asked: list[str] = []

    def __call__(self, instance, request, action, *, confirm=None, confirmed=False):
        app = request.target
        if not confirmed:
            if confirm is None:
                return ActionResult.failed("confirmation_required")
            self.asked.append(app)
            if not confirm(f"start {app}"):
                return ActionResult.failed("declined", f"Did not start {app}.")
        self.launched.append(app)
        return ActionResult.ok(f"Started {app}.")


@pytest.fixture
def actuators(monkeypatch: pytest.MonkeyPatch) -> dict:
    launcher = FakeLauncher()
    search = MagicMock(return_value=ActionResult.ok(WEATHER))
    notes = MagicMock(return_value=ActionResult.ok("Saved note: Weather in Chennai."))
    monkeypatch.setattr(get("open_app").implementation, launcher, raising=True)
    monkeypatch.setattr(get("web_search").implementation, search, raising=True)
    monkeypatch.setattr(get("notes_create").implementation, notes, raising=True)
    return {"launcher": launcher, "search": search, "notes": notes}


def _offered(request: dict) -> set[str]:
    return {(tool.get("function") or tool).get("name") for tool in request["tools"]}


def test_each_step_of_the_goal_picks_its_domain() -> None:
    chosen = candidate_domains(GOAL)
    assert set(chosen) == {"notes", "web"}, chosen


def test_every_step_has_its_tool_on_the_first_turn(actuators: dict) -> None:
    model = _plan()
    run(GOAL, engine=model, model="stub", confirm_callback=lambda *_: True)

    assert {"open_app", "web_search", "notes_create"} <= _offered(model.requests[0])


def test_the_whole_plan_runs_in_order_after_one_yes(actuators: dict) -> None:
    asked: list[tuple[str, str]] = []

    def approve(action, parameters, risk):
        asked.append((action, str(parameters.get("_plan", ""))))
        return True

    model = _plan()
    result = run(GOAL, engine=model, model="stub", confirm_callback=approve)

    # plan -> confirmation -> execution
    assert result.actions_taken == ("open_app", "web_search", "notes_create")
    assert asked == [("open_app", "start chrome")]
    assert actuators["launcher"].launched == ["chrome"]
    # the search's answer is what the model saw, and what it saved
    search_result = model.requests[2]["messages"][-1]
    assert WEATHER in str(getattr(search_result, "content", search_result))
    assert actuators["notes"].call_count == 1
    (notes_action,) = actuators["notes"].call_args.args[1:2]
    assert notes_action.title == "Weather in Chennai"
    assert WEATHER in notes_action.content

    # the report of what was done
    assert all(entry.success for entry in result.trace)
    assert [entry.summary() for entry in result.trace] == [
        "open_app -> ok",
        "web_search -> ok",
        "notes_create -> ok",
    ]
    assert "saved it to a note" in result.text
    assert result.stopped_at_limit is False


def test_a_no_to_the_browser_starts_nothing_and_is_reported(actuators: dict) -> None:
    model = _plan()
    result = run(GOAL, engine=model, model="stub", confirm_callback=lambda *_: False)

    assert actuators["launcher"].asked == ["chrome"]
    assert actuators["launcher"].launched == []
    assert result.trace[0].action == "open_app"
    assert result.trace[0].success is False


def test_with_no_one_to_ask_the_browser_never_starts(actuators: dict) -> None:
    model = _plan()
    result = run(GOAL, engine=model, model="stub", confirm_callback=None)

    assert actuators["launcher"].launched == []
    assert result.trace[0].success is False
