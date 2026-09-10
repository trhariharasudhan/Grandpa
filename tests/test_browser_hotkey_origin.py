"""Browser hotkeys must be attributed to whoever pressed them.

``BrowserExecutor`` sends its browser shortcuts -- new tab, close tab, refresh,
back, forward, reopen closed tab, focus address bar -- through
``_default_hotkey``, which built a ``keyboard_hotkey`` payload with no
``origin`` (``browser/executor.py:183``). ``_coerce_request`` therefore filed
every one as ``direct``, including the ones a person spoke.

``keyboard_hotkey`` is MEDIUM risk and approval-gated, so these are among the
more consequential actions to attribute correctly. This was the last payload in
the codebase built without provenance.

Truthful origins, from tracing every caller of ``handle_browser_command``:

* ``voice/operator.py`` and ``voice/assistant.py`` -- **voice**.
* ``cli/chat_cmd.py`` (three sites) -- **direct**; a person typed it, so the
  existing default is already correct and those callers are asserted rather
  than changed.
* The executive planner no longer calls it at all; its browser steps go through
  ``run_browser_action`` since the boundary slice.

Nothing here presses a key: every test substitutes the actuator.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from grandpa import pc_control
from grandpa.pc_control import ACTION_ORIGINS, _coerce_request

HOTKEY_COMMANDS = (
    ("new tab", "new_tab"),
    ("close tab", "close_tab"),
    ("reload the page", "refresh"),
    ("go back", "back"),
    ("reopen closed tab", "reopen_closed_tab"),
)


class RecordingActuator:
    """Stands in for ``run_local_action`` and records every payload."""

    def __init__(self, *, ok: bool = True) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.ok = ok

    def __call__(self, payload: dict[str, Any]):
        self.payloads.append(dict(payload))
        return pc_control.LocalActionResponse(
            ok=self.ok,
            action_id=None,
            status="completed" if self.ok else "blocked",
            message="ok",
            approval_required=False,
            risk_level="MEDIUM",
            evidence={},
        )

    @property
    def origins(self) -> list[str]:
        return [_coerce_request(payload).origin for payload in self.payloads]

    @property
    def action_types(self) -> list[str]:
        return [payload.get("action_type") for payload in self.payloads]


@pytest.fixture
def actuator(monkeypatch):
    recorder = RecordingActuator()
    monkeypatch.setattr(pc_control, "run_local_action", recorder)
    return recorder


class RecordingAutomation:
    target_window = None

    def __init__(self) -> None:
        self.commands: list[str] = []

    def has_pending_confirmation(self) -> bool:
        return False

    def has_pending_window_choice(self) -> bool:
        return False

    def has_pending_dialog(self) -> bool:
        return False

    def handle(self, command: str, dry_run: bool = False):
        from types import SimpleNamespace

        self.commands.append(command)
        return SimpleNamespace(
            status="handled", message="", data={}, confirmation_token=None
        )


# ---------------------------------------------------------------------------
# The payload
# ---------------------------------------------------------------------------


class TestHotkeyPayload:
    def test_the_default_hotkey_states_direct(self, actuator):
        from grandpa.browser.executor import _default_hotkey

        _default_hotkey(("ctrl", "t"))

        assert actuator.action_types == ["keyboard_hotkey"]
        assert actuator.origins == ["direct"]

    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_the_stated_origin_reaches_the_request(self, origin, actuator):
        from grandpa.browser.executor import _default_hotkey

        _default_hotkey(("ctrl", "t"), origin=origin)

        assert actuator.origins == [origin]

    def test_the_keys_and_target_are_unchanged(self, actuator):
        from grandpa.browser.executor import _default_hotkey

        _default_hotkey(("ctrl", "shift", "t"), origin="voice")

        payload = actuator.payloads[0]
        assert payload["target"] == "ctrl+shift+t"
        assert payload["args"] == {"keys": ["ctrl", "shift", "t"]}

    def test_an_unknown_origin_normalises_rather_than_raising(self, actuator):
        from grandpa.browser.executor import _default_hotkey

        _default_hotkey(("ctrl", "t"), origin="nonsense")

        assert actuator.origins == ["direct"]


# ---------------------------------------------------------------------------
# Through the executor and the facade
# ---------------------------------------------------------------------------


class TestExecutorAndFacade:
    def test_the_executor_defaults_to_direct(self):
        from grandpa.browser.executor import BrowserExecutor

        assert BrowserExecutor().origin == "direct"

    def test_the_executor_carries_its_origin_to_the_hotkey(self, actuator):
        from grandpa.browser.executor import BrowserExecutor
        from grandpa.browser.parser import BrowserParser

        action = BrowserParser().parse("new tab")
        BrowserExecutor(origin="voice").execute(action)

        assert actuator.action_types == ["keyboard_hotkey"]
        assert actuator.origins == ["voice"]

    @pytest.mark.parametrize(("command", "_kind"), HOTKEY_COMMANDS)
    def test_every_hotkey_command_carries_the_origin(self, command, _kind, actuator):
        from grandpa.browser import handle_browser_command

        handle_browser_command(command, origin="voice")

        assert actuator.origins == ["voice"], f"{command!r} lost its provenance"

    def test_the_facade_defaults_to_direct(self, actuator):
        from grandpa.browser import handle_browser_command

        handle_browser_command("new tab")

        assert actuator.origins == ["direct"]

    def test_the_automation_facade_carries_its_origin(self, actuator):
        """``BrowserAutomation`` builds the executor when none is passed.

        ``handle_browser_command`` always passes one, so this branch is only
        reached by a caller constructing the facade itself -- and it must not
        quietly lose the provenance it was given.
        """
        from grandpa.browser.automation import BrowserAutomation

        BrowserAutomation(origin="voice").handle("new tab")

        assert actuator.origins == ["voice"]

    def test_the_automation_facade_defaults_to_direct(self, actuator):
        from grandpa.browser.automation import BrowserAutomation

        BrowserAutomation().handle("new tab")

        assert actuator.origins == ["direct"]

    def test_an_injected_hotkey_runner_still_wins(self, actuator):
        """A caller substituting the runner keeps full control."""
        from grandpa.browser import handle_browser_command

        seen: list[tuple[str, ...]] = []
        handle_browser_command(
            "new tab",
            hotkey_runner=lambda keys: seen.append(keys) is None,
            origin="voice",
        )

        assert seen == [("ctrl", "t")]
        assert actuator.payloads == [], "the injected runner was bypassed"


# ---------------------------------------------------------------------------
# The voice surface
# ---------------------------------------------------------------------------


def _turn(text: str, monkeypatch):
    from grandpa.voice.operator import process_voice_operator_turn

    monkeypatch.setattr(
        "grandpa.planner.routing.handle_executive_goal", lambda *a, **k: None
    )
    return process_voice_operator_turn(
        text, action_runner=lambda p: None, automation_service=RecordingAutomation()
    )


class TestVoiceSurface:
    def test_a_spoken_browser_hotkey_is_attributed_to_voice(
        self, actuator, monkeypatch
    ):
        _turn("new tab", monkeypatch)

        assert actuator.action_types == ["keyboard_hotkey"]
        assert actuator.origins == ["voice"]

    def test_the_voice_assistant_path_is_attributed_to_voice(self, actuator):
        """``voice/assistant.py`` reaches the same facade."""
        import inspect as _inspect

        from grandpa.voice import assistant

        source = _inspect.getsource(assistant)
        assert 'handle_browser_command(effective_text, origin="voice")' in source

    def test_the_origin_reaches_the_audit_record(self, monkeypatch, tmp_path):
        import json

        log = tmp_path / "audit.log"
        monkeypatch.setattr(pc_control, "get_audit_log_path", lambda: log)
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="ok",
                approval_required=False,
                risk_level=risk,
                evidence={},
            ),
        )

        from grandpa.browser.executor import _default_hotkey

        _default_hotkey(("ctrl", "t"), origin="voice")

        record = json.loads(
            [line for line in log.read_text(encoding="utf-8").splitlines() if line][-1]
        )
        assert record["action_type"] == "keyboard_hotkey"
        assert record["origin"] == "voice"


# ---------------------------------------------------------------------------
# Chat stays direct
# ---------------------------------------------------------------------------


class TestChatStaysDirect:
    def test_a_typed_browser_hotkey_stays_direct(self, actuator):
        """Chat callers pass no origin, and a person typed the command."""
        from grandpa.browser import handle_browser_command

        handle_browser_command("reload the page")

        assert actuator.origins == ["direct"]


# ---------------------------------------------------------------------------
# Policy is untouched
# ---------------------------------------------------------------------------


class TestPolicyPreserved:
    def test_the_hotkey_risk_tier_is_unchanged(self):
        assert "keyboard_hotkey" in pc_control.MEDIUM_RISK_ACTIONS
        assert "keyboard_hotkey" in pc_control.APPROVAL_REQUIRED_ACTIONS

    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_origin_does_not_change_the_outcome(self, origin, monkeypatch, tmp_path):
        """Provenance is recorded, never used to gate."""
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "a.log"
        )
        seen: list[str] = []
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: (
                seen.append(risk)
                or pc_control.LocalActionResponse(
                    ok=True,
                    action_id=None,
                    status="completed",
                    message="ok",
                    approval_required=False,
                    risk_level=risk,
                    evidence={},
                )
            ),
        )

        from grandpa.browser.executor import _default_hotkey

        _default_hotkey(("ctrl", "t"), origin=origin)

        # keyboard_hotkey is approval-gated, so nothing executes for any origin.
        assert seen == []

    def test_a_refused_hotkey_is_reported_as_an_error(self, monkeypatch):
        from grandpa.browser import handle_browser_command

        monkeypatch.setattr(pc_control, "run_local_action", RecordingActuator(ok=False))

        result = handle_browser_command("new tab", origin="voice")

        assert result.status == "error"


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_the_origin_vocabulary_is_unchanged(self):
        assert ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )

    def test_the_new_configuration_is_keyword_only(self):
        from grandpa.browser.executor import BrowserExecutor

        assert (
            inspect.signature(BrowserExecutor).parameters["origin"].kind
            is inspect.Parameter.KEYWORD_ONLY
        )

    def test_the_executor_default_matches_pc_controls_own(self):
        from grandpa.browser.executor import BrowserExecutor
        from grandpa.pc_control import DEFAULT_ACTION_ORIGIN

        assert (
            inspect.signature(BrowserExecutor).parameters["origin"].default
            == DEFAULT_ACTION_ORIGIN
        )

    def test_no_payload_is_built_without_provenance(self):
        """The sweep this slice closes: every payload states who asked.

        Two callers legitimately state nothing, because ``direct`` is their
        truthful origin -- traced and asserted in
        ``tests/test_agent_provenance.py``. Anything else appearing here is a
        payload that has lost its provenance.
        """
        import pathlib as _pathlib
        import re as _re

        # Compared by module name so the check is platform-independent.
        TRUTHFULLY_DEFAULT = {"local_actions.py", "operator.py"}
        missing: list[str] = []
        pattern = _re.compile(r"run_local_action\(\s*\{(.*?)\n        \}", _re.S)

        for path in _pathlib.Path("src/grandpa").rglob("*.py"):
            if path.name in TRUTHFULLY_DEFAULT:
                continue
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                if '"origin"' not in match.group(1):
                    line = text[: match.start()].count(chr(10)) + 1
                    missing.append(f"{path.as_posix()}:{line}")

        assert missing == [], f"payloads without provenance: {missing}"
