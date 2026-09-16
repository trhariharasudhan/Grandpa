"""The loop side of tiering: what the model is sent, and what load_tools does.

The scripted engine records every request, so these check the thing that
actually matters at runtime -- that the first request is small, that a deferred
action becomes callable after one round trip, and that the core block in the
payload never moves.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grandpa.action_layer.catalogue import (
    CATALOGUE,
    CORE_ACTIONS,
    get,
    loadable_domains,
)
from grandpa.action_layer.loop import run
from grandpa.action_layer.tool_schema import LOAD_TOOLS, core_tool_definitions


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))


def tool_call(name: str, arguments: dict, call_id: str = "call_0") -> dict:
    return {"id": call_id, "name": name, "arguments": json.dumps(arguments)}


class StubEngine:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests: list[dict] = []

    def supports_tools(self, model: str) -> bool:
        return True

    def generate(self, messages, *, model, tools=None, temperature=0.0, **kwargs):
        self.requests.append({"messages": list(messages), "tools": tools})
        if not self.turns:
            return {"content": "Nothing further."}
        return self.turns.pop(0)


def names(request: dict) -> list[str]:
    return [entry["function"]["name"] for entry in request["tools"]]


def _patch(monkeypatch: pytest.MonkeyPatch, action: str, returns=None) -> MagicMock:
    mock = MagicMock(return_value=returns)
    monkeypatch.setattr(get(action).implementation, mock, raising=True)
    return mock


class _Response:
    def __init__(self, message="done"):
        self.ok = True
        self.status = "completed"
        self.message = message
        self.evidence = {}
        self.error = None


# --- what the first request carries -------------------------------------------


def test_the_first_request_sends_only_core_and_the_meta_tool() -> None:
    engine = StubEngine({"content": "Nothing to do."})

    run("hello", engine=engine, model="stub")

    assert names(engine.requests[0]) == [*CORE_ACTIONS, LOAD_TOOLS]


def test_the_first_request_is_far_smaller_than_the_whole_catalogue() -> None:
    """The measurement that justifies the whole design."""
    from grandpa.action_layer.tool_schema import as_tool_definitions

    tiered = StubEngine({"content": "done"})
    run("hello", engine=tiered, model="stub")

    sent = len(json.dumps(tiered.requests[0]["tools"]))
    everything = len(json.dumps(as_tool_definitions(CATALOGUE)))

    assert sent < everything / 4, f"core {sent} chars vs all {everything}"


def test_asking_for_everything_is_still_possible() -> None:
    """A backend that does not pay per prompt token should get the lot."""
    engine = StubEngine({"content": "done"})

    run("hello", engine=engine, model="stub", tiered=False)

    assert len(names(engine.requests[0])) == len(CATALOGUE)
    assert LOAD_TOOLS not in names(engine.requests[0])


# --- loading a domain ---------------------------------------------------------


def test_load_tools_adds_a_domain_and_the_loop_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation = _patch(monkeypatch, "notes_delete", _Response("Note deleted."))
    engine = StubEngine(
        {"content": "", "tool_calls": [tool_call(LOAD_TOOLS, {"domain": "notes"})]},
        {
            "content": "",
            "tool_calls": [tool_call("notes_delete", {"title": "Old"}, "c1")],
        },
        {"content": "Deleted it."},
    )

    result = run(
        "delete my note", engine=engine, model="stub", confirm_callback=lambda *_: True
    )

    assert result.loaded_domains == ("notes",)
    assert "notes_delete" not in names(engine.requests[0]), "it was in core already?"
    assert "notes_delete" in names(engine.requests[1]), "the domain did not arrive"
    implementation.assert_called_once()
    assert result.text == "Deleted it."


def test_loading_costs_exactly_one_extra_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cost of deferring: one more request, not a restart."""
    _patch(monkeypatch, "notes_pin", _Response("Pinned."))
    engine = StubEngine(
        {"content": "", "tool_calls": [tool_call(LOAD_TOOLS, {"domain": "notes"})]},
        {"content": "", "tool_calls": [tool_call("notes_pin", {"title": "X"}, "c1")]},
        {"content": "Pinned it."},
    )

    result = run("pin my note", engine=engine, model="stub")

    # Three requests: load, act, answer. Without tiering it would be two.
    assert len(engine.requests) == 3
    assert result.steps == 3


def test_load_tools_never_reaches_the_executor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """It changes the menu, so it is not an action and must not be audited."""
    engine = StubEngine(
        {"content": "", "tool_calls": [tool_call(LOAD_TOOLS, {"domain": "notes"})]},
        {"content": "Loaded."},
    )

    result = run("what can you do", engine=engine, model="stub")

    assert result.trace == (), "load_tools was recorded as an action"
    log = tmp_path / "actions.jsonl"
    assert not log.exists() or log.read_text(encoding="utf-8").strip() == ""


def test_an_unknown_domain_is_answered_not_crashed() -> None:
    engine = StubEngine(
        {"content": "", "tool_calls": [tool_call(LOAD_TOOLS, {"domain": "teapot"})]},
        {"content": "No such subject."},
    )

    result = run("do something odd", engine=engine, model="stub")

    assert result.loaded_domains == ()
    handed_back = json.loads(
        [m for m in engine.requests[1]["messages"] if m.role.value == "tool"][0].content
    )
    assert handed_back["success"] is False
    assert handed_back["error"] == "unknown_domain"
    assert "notes" in handed_back["available"]


def test_loading_the_same_domain_twice_is_harmless() -> None:
    engine = StubEngine(
        {"content": "", "tool_calls": [tool_call(LOAD_TOOLS, {"domain": "notes"})]},
        {
            "content": "",
            "tool_calls": [tool_call(LOAD_TOOLS, {"domain": "notes"}, "c1")],
        },
        {"content": "Ready."},
    )

    result = run("notes please", engine=engine, model="stub")

    assert result.loaded_domains == ("notes",)
    assert names(engine.requests[1]) == names(engine.requests[2])


def test_two_domains_both_arrive() -> None:
    engine = StubEngine(
        {"content": "", "tool_calls": [tool_call(LOAD_TOOLS, {"domain": "notes"})]},
        {
            "content": "",
            "tool_calls": [tool_call(LOAD_TOOLS, {"domain": "downloads"}, "c1")],
        },
        {"content": "Ready."},
    )

    result = run("notes and downloads", engine=engine, model="stub")

    assert result.loaded_domains == ("notes", "downloads")
    offered = names(engine.requests[2])
    assert "notes_delete" in offered and "downloads_delete" in offered


# --- the prefix, as the model actually receives it ----------------------------


def test_the_core_block_never_moves_in_the_payload() -> None:
    """The reason tiering works at all: Ollama caches an unchanged prefix."""
    engine = StubEngine(
        {"content": "", "tool_calls": [tool_call(LOAD_TOOLS, {"domain": "notes"})]},
        {
            "content": "",
            "tool_calls": [tool_call(LOAD_TOOLS, {"domain": "input"}, "c1")],
        },
        {"content": "Ready."},
    )

    run("load things", engine=engine, model="stub")

    prefix = json.dumps(core_tool_definitions())[:-1]
    for index, request in enumerate(engine.requests):
        assert json.dumps(request["tools"]).startswith(prefix), f"request {index}"


def test_a_deferred_action_behaves_identically_once_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deferring must not change risk or confirmation."""
    implementation = _patch(monkeypatch, "notes_delete", _Response())
    engine = StubEngine(
        {"content": "", "tool_calls": [tool_call(LOAD_TOOLS, {"domain": "notes"})]},
        {
            "content": "",
            "tool_calls": [tool_call("notes_delete", {"title": "X"}, "c1")],
        },
        {"content": "I left it alone."},
    )

    result = run("delete it", engine=engine, model="stub")

    # No callback, so the HIGH action refuses exactly as it would in core.
    implementation.assert_not_called()
    assert result.trace[0].error == "confirmation_required"


# --- the system prompt tells the model the list is partial --------------------


def test_the_model_is_told_it_can_load_more() -> None:
    engine = StubEngine({"content": "done"})

    run("hello", engine=engine, model="stub")

    system = engine.requests[0]["messages"][0].content
    assert LOAD_TOOLS in system
    assert "cannot" in system.lower()


def test_the_prompt_names_every_subject_load_tools_accepts() -> None:
    """A subject the model is never told about is a subject it cannot ask for.

    The list used to be typed by hand, and four domains -- the clock, calendar,
    mail and web -- were added without it. Thirty-three catalogued actions were
    loadable in principle and unreachable in practice, because the only way to
    name the subject was to guess it.

    A core domain is deliberately not named: it is already sent whole, so asking
    for it would spend a round trip on nothing.
    """
    engine = StubEngine({"content": "done"})

    run("hello", engine=engine, model="stub")

    system = engine.requests[0]["messages"][0].content
    assert [domain for domain in loadable_domains() if domain not in system] == []


def test_the_prompt_is_the_same_bytes_every_run() -> None:
    """It is the first thing in the cached prefix, so it must not vary."""
    first, second = StubEngine({"content": "a"}), StubEngine({"content": "b"})

    run("one", engine=first, model="stub")
    run("two", engine=second, model="stub")

    assert first.requests[0]["messages"][0].content == (
        second.requests[0]["messages"][0].content
    )
