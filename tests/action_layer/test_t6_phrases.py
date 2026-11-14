"""V1-T6: the right tools are in front of the model on the FIRST turn.

Only a handful of the catalogued actions go to the model by default, and it
almost never calls ``load_tools`` on its own, so the goal's words pick the
domain before the first request. These are the four phrases from the task,
plus the power words that used to choose the wrong domain or none.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grandpa.action_layer.catalogue import (
    _SELECTION_KEYWORDS,
    candidate_domains,
    get,
    loadable_domains,
)
from grandpa.action_layer.loop import run


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    return tmp_path / "actions.jsonl"


class StubEngine:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests: list[dict] = []

    def supports_tools(self, model: str) -> bool:
        return True

    def generate(self, messages, *, model, tools=None, temperature=0.0, **kwargs):
        self.requests.append({"tools": tools})
        return self.turns.pop(0) if self.turns else {"content": "Done."}


def _names(tools) -> set[str]:
    return {(tool.get("function") or tool).get("name") for tool in tools or []}


def _call(name: str, arguments: dict | None = None) -> dict:
    return {"id": "call_0", "name": name, "arguments": json.dumps(arguments or {})}


class _Response:
    ok = True
    status = "completed"
    message = "done"
    evidence: dict = {}
    error = None


@pytest.mark.parametrize(
    ("goal", "action"),
    [
        ("list my notes", "notes_list"),
        ("set volume to 30", "volume_set"),
        ("what is my brightness", "brightness_get"),
        ("lock the screen", "system_lock"),
    ],
)
def test_the_needed_action_is_offered_on_the_first_turn(goal: str, action: str) -> None:
    engine = StubEngine({"content": "ok"})
    run(goal, engine=engine, model="stub")
    assert action in _names(engine.requests[0]["tools"]), goal


@pytest.mark.parametrize(
    "goal",
    [
        "lock the screen",
        "lock my pc",
        "restart my computer",
        "shut down the pc",
        "reboot",
        "put the computer to sleep",
    ],
)
def test_power_requests_select_the_system_domain(goal: str) -> None:
    assert candidate_domains(goal)[:1] == ("system",), goal


@pytest.mark.parametrize(
    "goal", ["what time is it", "turn the volume up", "open notepad"]
)
def test_core_requests_still_preload_nothing(goal: str) -> None:
    assert candidate_domains(goal) == (), goal


def test_every_keyword_names_a_real_loadable_domain() -> None:
    loadable = set(loadable_domains())
    for word, domain in _SELECTION_KEYWORDS.items():
        assert domain in loadable, (word, domain)


def test_lock_asks_for_confirmation_and_a_no_locks_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert get("system_lock").requires_confirmation
    implementation = MagicMock(return_value=_Response())
    monkeypatch.setattr(get("system_lock").implementation, implementation, raising=True)
    asked: list[str] = []

    def decline(action, parameters, risk):
        asked.append(action)
        return False

    engine = StubEngine(
        {"content": "", "tool_calls": [_call("system_lock")]},
        {"content": "I did not lock it."},
    )
    result = run(
        "lock the screen", engine=engine, model="stub", confirm_callback=decline
    )

    assert asked == ["system_lock"]
    implementation.assert_not_called()
    assert result.trace[0].success is False


def test_lock_runs_after_a_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    implementation = MagicMock(return_value=_Response())
    monkeypatch.setattr(get("system_lock").implementation, implementation, raising=True)
    engine = StubEngine(
        {"content": "", "tool_calls": [_call("system_lock")]},
        {"content": "Locked."},
    )
    run(
        "lock the screen",
        engine=engine,
        model="stub",
        confirm_callback=lambda *_: True,
    )
    implementation.assert_called_once()
