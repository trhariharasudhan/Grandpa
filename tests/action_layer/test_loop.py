"""The loop, driven by a stubbed engine so the behaviour is the model's script.

A real model is not a test fixture: it is the thing under observation in item
4. Here the turns are scripted, so what is being checked is the loop's own
rules -- that results go back, that a failure does not abort, that the step
limit says something, and that nothing reaches an implementation without
passing the executor.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grandpa.action_layer import loop
from grandpa.action_layer.catalogue import get
from grandpa.action_layer.loop import (
    DEFAULT_STEP_LIMIT,
    LoopResult,
    ToolsUnsupportedError,
    run,
)
from grandpa.action_layer.model import Origin

# Opted out of the default-deny actuation fixture (tests/actuation_guard.py):
pytestmark = pytest.mark.real_actions(
    reason="drives the real file implementation against paths the test creates"
)


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    return tmp_path / "actions.jsonl"


def tool_call(name: str, arguments: dict | str, call_id: str = "call_0") -> dict:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "name": name, "arguments": raw}


class StubEngine:
    """A scripted model. Each generate() returns the next prepared turn."""

    def __init__(self, *turns, capabilities=("completion", "tools")):
        self.turns = list(turns)
        self.capabilities = tuple(capabilities)
        self.requests: list[dict] = []

    def supports_tools(self, model: str) -> bool:
        return "tools" in self.capabilities

    def generate(self, messages, *, model, tools=None, temperature=0.0, **kwargs):
        self.requests.append(
            {"messages": list(messages), "model": model, "tools": tools}
        )
        if not self.turns:
            return {"content": "I have nothing further."}
        return self.turns.pop(0)


def _patch(monkeypatch: pytest.MonkeyPatch, action: str, returns=None) -> MagicMock:
    mock = MagicMock(return_value=returns)
    monkeypatch.setattr(get(action).implementation, mock, raising=True)
    return mock


class _Response:
    def __init__(self, ok=True, status="completed", message="done", evidence=None):
        self.ok = ok
        self.status = status
        self.message = message
        self.evidence = evidence or {}
        self.error = None if ok else "service_error"


# --- the simple path ----------------------------------------------------------


def test_one_tool_call_then_an_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    implementation = _patch(monkeypatch, "volume_up", _Response(message="Volume up."))
    engine = StubEngine(
        {"content": "", "tool_calls": [tool_call("volume_up", {})]},
        {"content": "Turned the volume up."},
    )

    result = run("turn the volume up", engine=engine, model="stub")

    assert isinstance(result, LoopResult)
    assert result.text == "Turned the volume up."
    assert result.actions_taken == ("volume_up",)
    assert result.trace[0].success is True
    assert result.stopped_at_limit is False
    implementation.assert_called_once()


def test_the_catalogue_is_offered_as_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = StubEngine({"content": "Nothing to do."})

    run("hello", engine=engine, model="stub")

    names = {tool["function"]["name"] for tool in engine.requests[0]["tools"]}
    assert "volume_up" in names
    assert "shell_run" not in names, "an excluded action was offered to the model"


def test_a_single_action_can_be_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = StubEngine({"content": "done"})

    run("hi", engine=engine, model="stub", actions=[get("volume_up")])

    assert [tool["function"]["name"] for tool in engine.requests[0]["tools"]] == [
        "volume_up"
    ]


# --- several steps ------------------------------------------------------------


def test_a_multi_step_chain_runs_in_order_and_feeds_results_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    note = tmp_path / "note.txt"
    engine = StubEngine(
        {
            "content": "",
            "tool_calls": [
                tool_call("file_create", {"path": str(note), "content": "first line"})
            ],
        },
        {"content": "", "tool_calls": [tool_call("clipboard_read", {}, "call_1")]},
        {"content": "Created the note and read the clipboard."},
    )
    _patch(monkeypatch, "clipboard_read", _Response(message="Clipboard read."))

    result = run("do two things", engine=engine, model="stub")

    assert result.actions_taken == ("file_create", "clipboard_read")
    assert result.steps == 3
    assert note.read_text(encoding="utf-8") == "first line"

    # The second request carried the first result back to the model.
    second = engine.requests[1]["messages"]
    tool_messages = [m for m in second if m.role.value == "tool"]
    assert tool_messages, second
    assert json.loads(tool_messages[0].content)["success"] is True
    assert tool_messages[0].name == "file_create"


def test_a_failing_action_goes_back_to_the_model_and_the_loop_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = StubEngine(
        {"content": "", "tool_calls": [tool_call("volume_set", {"level": 500})]},
        {"content": "", "tool_calls": [tool_call("volume_set", {"level": 50}, "c1")]},
        {"content": "Sorry about that -- volume is at 50 now."},
    )
    _patch(monkeypatch, "volume_set", _Response(message="Volume set."))

    result = run("set the volume to 500", engine=engine, model="stub")

    assert result.trace[0].success is False
    assert "must be at most 100" in result.trace[0].message
    assert result.trace[1].success is True
    assert result.text.endswith("volume is at 50 now.")

    # The model saw the failure rather than an exception ending the run.
    handed_back = json.loads(
        [m for m in engine.requests[1]["messages"] if m.role.value == "tool"][0].content
    )
    assert handed_back["success"] is False
    assert handed_back["error"] == "invalid_parameters"


def test_an_unknown_tool_name_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = StubEngine(
        {"content": "", "tool_calls": [tool_call("format_c_drive", {})]},
        {"content": "I cannot do that."},
    )

    result = run("wipe the disk", engine=engine, model="stub")

    assert result.trace[0].success is False
    assert result.trace[0].error == "unknown_action"
    assert result.text == "I cannot do that."


def test_malformed_arguments_are_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = StubEngine(
        {"content": "", "tool_calls": [tool_call("volume_set", "{not json")]},
        {"content": "Let me try that again."},
    )

    result = run("set the volume", engine=engine, model="stub")

    assert result.trace[0].error == "invalid_arguments"
    assert "not valid JSON" in result.trace[0].message


# --- confirmation -------------------------------------------------------------


def test_a_declined_confirmation_stops_the_action_not_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation = _patch(monkeypatch, "file_delete", _Response())
    engine = StubEngine(
        {
            "content": "",
            "tool_calls": [tool_call("file_delete", {"path": "C:/tmp/x.txt"})],
        },
        {"content": "I left the file alone."},
    )

    result = run(
        "delete that file",
        engine=engine,
        model="stub",
        confirm_callback=lambda *_: False,
    )

    implementation.assert_not_called()
    assert result.trace[0].error == "confirmation_declined"
    assert result.text == "I left the file alone."


def test_a_confirmable_action_with_no_callback_never_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation = _patch(monkeypatch, "file_delete", _Response())
    engine = StubEngine(
        {
            "content": "",
            "tool_calls": [tool_call("file_delete", {"path": "C:/tmp/x.txt"})],
        },
        {"content": "I could not, nobody was there to confirm."},
    )

    result = run("delete that file", engine=engine, model="stub")

    implementation.assert_not_called()
    assert result.trace[0].error == "confirmation_required"


def test_the_confirmation_carries_the_loops_origin(
    monkeypatch: pytest.MonkeyPatch, audit_log: Path
) -> None:
    _patch(monkeypatch, "file_delete", _Response())
    engine = StubEngine(
        {
            "content": "",
            "tool_calls": [tool_call("file_delete", {"path": "C:/tmp/x.txt"})],
        },
        {"content": "Deleted."},
    )

    run(
        "delete it",
        engine=engine,
        model="stub",
        origin=Origin.USER_CLI,
        confirm_callback=lambda *_: True,
    )

    record = json.loads(audit_log.read_text(encoding="utf-8").splitlines()[0])
    assert record["origin"] == "user_cli"
    assert record["confirmed"] is True


# --- the step limit -----------------------------------------------------------


def test_hitting_the_step_limit_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, "volume_up", _Response())
    forever = [
        {"content": "", "tool_calls": [tool_call("volume_up", {})]} for _ in range(10)
    ]
    engine = StubEngine(*forever)

    result = run("go forever", engine=engine, model="stub", step_limit=3)

    assert result.stopped_at_limit is True
    assert result.steps == 3
    assert len(result.trace) == 3
    assert "stopped after 3 steps" in result.text
    assert "volume_up -> ok" in result.text


def test_the_default_step_limit_is_sane() -> None:
    assert 3 <= DEFAULT_STEP_LIMIT <= 20


def test_a_silent_model_is_reported_rather_than_returning_nothing() -> None:
    engine = StubEngine({"content": "", "tool_calls": []})

    result = run("do something", engine=engine, model="stub")

    assert "without an answer" in result.text
    assert result.trace == ()


# --- models that cannot call tools --------------------------------------------


def test_a_model_without_tool_support_fails_by_name() -> None:
    engine = StubEngine({"content": "hi"}, capabilities=("completion",))

    with pytest.raises(ToolsUnsupportedError) as raised:
        run("turn the volume up", engine=engine, model="grandpa-classic:latest")

    assert "grandpa-classic:latest" in str(raised.value)
    assert "tools" in str(raised.value)
    assert engine.requests == [], "it asked the model anyway"


def test_capabilities_come_from_the_backend_not_the_model_name() -> None:
    """Ollama reports them on /api/show; guessing from the name is how you
    end up silently chatting instead of acting."""

    class _Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class _Client:
        def __init__(self, capabilities):
            self.capabilities = capabilities
            self.asked = []

        def post(self, path, json=None):
            self.asked.append((path, json))
            return _Response({"capabilities": self.capabilities})

    class _Ollamaish:
        def __init__(self, capabilities):
            self._client = _Client(capabilities)

    assert loop.supports_tools(_Ollamaish(["completion", "tools"]), "m") is True
    assert loop.supports_tools(_Ollamaish(["completion"]), "m") is False
    assert loop.supports_tools(object(), "m") is None


def test_an_engine_that_will_not_say_is_allowed_to_proceed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown is not the same as unsupported: a stub or a non-Ollama backend
    should not be refused on a question it cannot answer."""

    class _Quiet:
        def generate(self, messages, *, model, tools=None, temperature=0.0, **kwargs):
            return {"content": "done"}

    result = run("hello", engine=_Quiet(), model="mystery")

    assert result.text == "done"
