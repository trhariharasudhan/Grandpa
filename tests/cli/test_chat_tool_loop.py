"""V1-T5: ``grandpa chat`` sends unclaimed free text through the action layer.

End to end through the real ``chat`` command with a scripted model: the turn
reaches the model *with tools*, a tool call goes through the executor, a risky
action asks first and a "no" runs nothing, a model without tools falls back to
a plain reply, and ``[tools] chat_tool_loop = false`` restores the old path.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from grandpa.action_layer.catalogue import get
from grandpa.cli.chat_cmd import chat
from grandpa.core.config import GrandpaConfig

PHRASE = "please take care of the thing we talked about earlier"


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    return tmp_path / "actions.jsonl"


def _call(name: str, arguments: dict) -> dict:
    return {"id": "call_0", "name": name, "arguments": json.dumps(arguments)}


class ScriptedModel:
    """Each generate() returns the next prepared turn and records the request."""

    engine_id = "scripted"
    supports_streaming = False

    def __init__(self, *turns, tools: bool = True):
        self.turns = list(turns)
        self.tools = tools
        self.requests: list[dict] = []

    def supports_tools(self, model: str) -> bool:
        return self.tools

    def health(self) -> bool:
        return True

    def list_models(self):
        return ["scripted-model"]

    def generate(self, messages, *, model, tools=None, temperature=0.0, **kwargs):
        self.requests.append({"messages": list(messages), "tools": tools})
        if not self.turns:
            return {"content": "Nothing further."}
        return self.turns.pop(0)


class _Response:
    def __init__(self, message: str = "done"):
        self.ok = True
        self.status = "completed"
        self.message = message
        self.evidence = {}
        self.error = None


def _run_chat(engine: ScriptedModel, typed: str, *, tool_loop: bool = True):
    config = GrandpaConfig()
    config.intelligence.default_model = "scripted-model"
    config.tools.chat_tool_loop = tool_loop
    with (
        patch("grandpa.cli.chat_cmd.load_config", return_value=config),
        patch("grandpa.engine.get_engine", return_value=("scripted", engine)),
        patch("grandpa.intelligence.register_builtin_models"),
    ):
        return CliRunner().invoke(
            chat, ["--model", "scripted-model", "--no-fullscreen"], input=typed
        )


def _patch_impl(monkeypatch: pytest.MonkeyPatch, action: str) -> MagicMock:
    mock = MagicMock(return_value=_Response(f"{action} done"))
    monkeypatch.setattr(get(action).implementation, mock, raising=True)
    return mock


def _tool_requests(engine: ScriptedModel) -> list[dict]:
    return [r for r in engine.requests if r["tools"]]


def test_free_text_reaches_the_model_with_tools_and_runs_a_low_risk_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    volume = _patch_impl(monkeypatch, "volume_up")
    engine = ScriptedModel(
        {"content": "", "tool_calls": [_call("volume_up", {})]},
        {"content": "Turned it up."},
    )

    result = _run_chat(engine, f"{PHRASE}\n/quit\n")

    assert result.exit_code == 0, result.output
    assert _tool_requests(engine), result.output
    volume.assert_called_once()
    assert "Turned it up." in result.output
    assert "volume_up" in result.output  # the action is announced


def test_a_risky_action_asks_and_a_no_runs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdown = _patch_impl(monkeypatch, "system_shutdown")
    engine = ScriptedModel(
        {"content": "", "tool_calls": [_call("system_shutdown", {})]},
        {"content": "Okay, I did not shut down."},
    )

    result = _run_chat(engine, f"{PHRASE}\nn\n/quit\n")

    assert result.exit_code == 0, result.output
    assert "system_shutdown" in result.output
    assert "[y/N]" in result.output, "a HIGH-risk action must ask first"
    shutdown.assert_not_called()


def test_a_risky_action_runs_after_a_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    shutdown = _patch_impl(monkeypatch, "system_shutdown")
    engine = ScriptedModel(
        {"content": "", "tool_calls": [_call("system_shutdown", {})]},
        {"content": "Shutting down."},
    )

    result = _run_chat(engine, f"{PHRASE}\ny\n/quit\n")

    assert result.exit_code == 0, result.output
    shutdown.assert_called_once()


def test_a_model_without_tools_answers_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = ScriptedModel({"content": "A plain answer."}, tools=False)

    result = _run_chat(engine, f"{PHRASE}\n/quit\n")

    assert result.exit_code == 0, result.output
    assert "A plain answer." in result.output
    assert "cannot call tools" in result.output
    assert not _tool_requests(engine)


def test_the_config_flag_restores_the_old_path(monkeypatch: pytest.MonkeyPatch) -> None:
    volume = _patch_impl(monkeypatch, "volume_up")
    engine = ScriptedModel({"content": "Old path reply."})

    result = _run_chat(engine, f"{PHRASE}\n/quit\n", tool_loop=False)

    assert result.exit_code == 0, result.output
    assert "Old path reply." in result.output
    assert not _tool_requests(engine)
    volume.assert_not_called()


def test_the_conversation_reaches_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = ScriptedModel({"content": "First."}, {"content": "Second."})

    result = _run_chat(
        engine, f"{PHRASE}\nand once more please, same as before\n/quit\n"
    )

    assert result.exit_code == 0, result.output
    second = _tool_requests(engine)[-1]["messages"]
    texts = [getattr(m, "content", "") for m in second]
    assert any(PHRASE in t for t in texts), "the earlier turn must be in context"
    assert any("First." in t for t in texts)
