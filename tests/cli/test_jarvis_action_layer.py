"""V1-T7: ``grandpa jarvis`` routes the eight ordinary phrases it used to refuse.

docs/product/MVP-STATUS.md §4.4 measured 0 of 8: open notepad, set volume to 30, lock
the screen, what is the time, take a screenshot, scroll down, close the window,
mute the volume. Each now reaches the action layer's tool loop with its action
on the first turn's tool list, and the action goes through the executor: the
plain ones run, the ones that need confirming are refused when there is no
terminal to ask, and asked when there is.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from grandpa.action_layer.catalogue import get
from grandpa.cli import cli
from grandpa.core.config import GrandpaConfig

PHRASES = {
    "open notepad": ("open_app", {"app": "notepad"}),
    "set volume to 30": ("volume_set", {"level": 30}),
    "lock the screen": ("system_lock", {}),
    "what is the time": ("datetime_now", {}),
    "take a screenshot": ("screen_capture", {}),
    "scroll down": ("mouse_scroll", {"amount": -3}),
    "close the window": ("close_window", {}),
    "mute the volume": ("volume_mute", {}),
}


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    return tmp_path / "actions.jsonl"


class ScriptedModel:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests: list[dict] = []

    def supports_tools(self, model: str) -> bool:
        return True

    def generate(self, messages, *, model, tools=None, temperature=0.0, **kwargs):
        self.requests.append({"tools": tools})
        return self.turns.pop(0) if self.turns else {"content": "Done."}


class _Response:
    ok = True
    status = "completed"
    message = "done"
    evidence: dict = {}
    error = None


def _offered(request: dict) -> set[str]:
    return {(t.get("function") or t).get("name") for t in request["tools"] or []}


def _jarvis(phrase: str, engine: ScriptedModel, *, typed: str = ""):
    config = GrandpaConfig()
    config.intelligence.default_model = "scripted-model"
    with (
        patch("grandpa.core.config.load_config", return_value=config),
        patch("grandpa.engine.get_engine", return_value=("scripted", engine)),
    ):
        return CliRunner().invoke(cli, ["jarvis", *phrase.split()], input=typed)


def _patch_impl(monkeypatch: pytest.MonkeyPatch, action: str) -> MagicMock:
    mock = MagicMock(return_value=_Response())
    monkeypatch.setattr(get(action).implementation, mock, raising=True)
    return mock


@pytest.mark.parametrize("phrase", list(PHRASES))
def test_each_phrase_reaches_the_action_layer_with_its_action(
    phrase: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    action, arguments = PHRASES[phrase]
    implementation = _patch_impl(monkeypatch, action)
    engine = ScriptedModel(
        {
            "content": "",
            "tool_calls": [
                {"id": "c0", "name": action, "arguments": json.dumps(arguments)}
            ],
        },
        {"content": "Done."},
    )

    result = _jarvis(phrase, engine)

    assert "don't know how to route" not in result.output
    assert engine.requests, result.output
    assert action in _offered(engine.requests[0]), (phrase, action)
    if get(action).requires_confirmation:
        # CliRunner has no terminal, so nobody can be asked: refused, not run.
        implementation.assert_not_called()
        assert "Traceback" not in result.output
    else:
        implementation.assert_called_once()
        assert result.exit_code == 0, result.output


def test_lock_asks_at_a_terminal_and_a_no_locks_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("grandpa.cli._tty.stdin_is_interactive", lambda: True)
    implementation = _patch_impl(monkeypatch, "system_lock")
    engine = ScriptedModel(
        {
            "content": "",
            "tool_calls": [{"id": "c0", "name": "system_lock", "arguments": "{}"}],
        },
        {"content": "Not locked."},
    )

    result = _jarvis("lock the screen", engine, typed="n\n")

    assert "Run it? [y/N]" in result.output
    implementation.assert_not_called()


def test_the_project_phrase_still_uses_jarvis_own_router(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "grandpa.jarvis.context_resolver.default_approved_roots", lambda: [tmp_path]
    )
    (tmp_path / "Grandpa").mkdir()
    loop = MagicMock(return_value=0)
    monkeypatch.setattr("grandpa.cli._tool_loop.run_tool_loop", loop)

    result = CliRunner().invoke(
        cli, ["jarvis", "--dry-run", "open my Grandpa project in VS Code"]
    )

    assert result.exit_code == 0, result.output
    loop.assert_not_called()


def test_dry_run_sends_nothing_to_the_model() -> None:
    engine = ScriptedModel()
    config = GrandpaConfig()
    with (
        patch("grandpa.core.config.load_config", return_value=config),
        patch("grandpa.engine.get_engine", return_value=("scripted", engine)),
    ):
        result = CliRunner().invoke(cli, ["jarvis", "--dry-run", "lock the screen"])

    assert result.exit_code == 0, result.output
    assert "Would send this to the action layer" in result.output
    assert "system" in result.output
    assert engine.requests == []
