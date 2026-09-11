"""Voice passes an explicit confirm callback to ``handle_local_action``.

The voice layer has no synchronous spoken yes/no helper — its confirmation is
turn-based (the next utterance) and cannot answer inside
``desktop_automation.execute_automation``. So voice hands down
``local_actions.refuse_confirmation``: the confirm-required tier refuses
explicitly instead of depending on an omitted argument.
"""

from __future__ import annotations

import ast
import importlib.util
from types import SimpleNamespace

import grandpa.local_actions as local_actions
from grandpa.local_actions import LocalActionResult, refuse_confirmation

_EXPECTED_CALL_SITES = {
    "grandpa.voice.assistant": 3,
    "grandpa.voice.session": 1,
}


def _handle_local_action_calls(module_name: str) -> list[ast.Call]:
    path = importlib.util.find_spec(module_name).origin
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "handle_local_action"
    ]


def test_every_voice_call_site_passes_a_confirm_callback() -> None:
    for module_name, expected in _EXPECTED_CALL_SITES.items():
        calls = _handle_local_action_calls(module_name)
        assert len(calls) == expected, (
            f"{module_name}: expected {expected} handle_local_action call(s), "
            f"found {len(calls)}; update this test if call sites moved"
        )
        for call in calls:
            confirm = next((k.value for k in call.keywords if k.arg == "confirm"), None)
            assert confirm is not None, (
                f"{module_name}:{call.lineno} calls handle_local_action without confirm="
            )
            assert not (isinstance(confirm, ast.Constant) and confirm.value is None), (
                f"{module_name}:{call.lineno} passes confirm=None"
            )


def test_refuse_confirmation_refuses_confirm_required_input() -> None:
    assert refuse_confirmation("type|hello", "confirm_required") is False
    assert refuse_confirmation("press|enter", "confirm_required") is False


def test_voice_http_route_passes_non_none_refusing_callback(monkeypatch) -> None:
    import grandpa.automation as automation
    import grandpa.voice.session as session

    seen: dict = {}

    def fake_handle_local_action(text: str, **kwargs):
        seen["text"] = text
        seen.update(kwargs)
        return LocalActionResult(
            status="handled", kind="time", message="It is noon.", tts_text="It is noon."
        )

    class _FallbackPipeline:
        def __init__(self, **kwargs) -> None:
            pass

        def handle(self, text: str, spoken: bool = False):
            return SimpleNamespace(should_fallback=True)

    monkeypatch.setattr(local_actions, "handle_local_action", fake_handle_local_action)
    monkeypatch.setattr(automation, "WindowsCommandPipeline", _FallbackPipeline)
    for helper in (
        "_safe_planner",
        "_safe_knowledge_context",
        "_safe_memory_context",
        "_safe_agent_goal",
    ):
        monkeypatch.setattr(session, helper, lambda _text: None)

    session._route_voice_request("type hello")

    assert seen.get("text") == "type hello", "voice route never reached local actions"
    assert seen.get("confirm") is not None
    assert seen["confirm"]("type|hello", "confirm_required") is False
