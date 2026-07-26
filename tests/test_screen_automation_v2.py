from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from grandpa.automation.confirmation import ConfirmationManager
from grandpa.automation.executor import AutomationExecutor
from grandpa.automation.locator import HighlightOverlay, ScreenElementLocator
from grandpa.automation.models import (
    AutomationAction,
    BoundingBox,
    LocatedElement,
)
from grandpa.automation.mouse import mouse_payload
from grandpa.automation.planner import AutomationPlanner
from grandpa.automation.service import ScreenAutomationService
from grandpa.automation.windows import (
    WindowIdentity,
    WindowTargetController,
    WindowVerification,
)
from grandpa.screen.models import OcrBlock, OcrResult


@dataclass
class FakeResponse:
    ok: bool = True
    status: str = "completed"
    message: str = "completed"
    action_id: str | None = None


class FakeLocator:
    def __init__(self, *elements: LocatedElement) -> None:
        self.elements = elements
        self.queries: list[str] = []

    def locate(self, query: str, *, limit: int = 5):
        self.queries.append(query)
        return self.elements[:limit]


class FakeWindowTargets:
    def __init__(self, *, ok: bool = True, actual_title: str = "Notepad") -> None:
        self.ok = ok
        self.actual_title = actual_title
        self.calls: list[tuple[str, bool]] = []

    def focus_and_verify(self, target, *, dry_run: bool = False):
        label = target.target if isinstance(target, WindowIdentity) else str(target)
        self.calls.append((label, dry_run))
        expected = WindowIdentity(10, "Untitled - Notepad", 100, "notepad.exe", label)
        actual = WindowIdentity(10 if self.ok else 20, self.actual_title, 100 if self.ok else 200, "notepad.exe" if self.ok else "WindowsTerminal.exe")
        return WindowVerification(
            self.ok,
            (
                f"Focused {label}.\nVerified active window: {self.actual_title}."
                if self.ok
                else f"Target verification failed.\nExpected {label}, but {self.actual_title} is active.\nNo input was sent."
            ),
            expected,
            actual,
        )


def element(text: str = "Save", confidence: float = 0.93) -> LocatedElement:
    return LocatedElement(
        text,
        "button",
        confidence,
        BoundingBox(100, 200, 80, 30),
        window_title="Editor",
    )


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("move mouse to 20 30", "move"),
        ("click Save button", "click"),
        ("double click Chrome", "double_click"),
        ("right click Downloads", "right_click"),
        ("middle click item", "middle_click"),
        ("scroll down", "scroll"),
        ("scroll up 8", "scroll"),
        ("type Hello World", "type"),
        ("press Enter", "press"),
        ("press Ctrl+S", "press"),
        ("switch to Chrome", "focus"),
        ("maximize this window", "maximize"),
        ("find the Install button", "locate"),
        ("highlight Settings button", "highlight"),
    ],
)
def test_planner_parses_supported_actions(command: str, kind: str) -> None:
    action = AutomationPlanner().parse(command)
    assert action is not None
    assert action.kind == kind


def test_click_requires_confirmation_but_scroll_does_not() -> None:
    planner = AutomationPlanner()
    assert planner.parse("click Save").requires_confirmation is True
    assert planner.parse("scroll down").requires_confirmation is False


def test_sensitive_typing_requires_confirmation() -> None:
    action = AutomationPlanner().parse("type my password")
    assert action is not None
    assert action.requires_confirmation is True
    assert action.sensitive is True


def test_card_like_typing_requires_confirmation() -> None:
    action = AutomationPlanner().parse("type 4111 1111 1111 1111")
    assert action is not None
    assert action.requires_confirmation is True


def test_mouse_payload_preserves_click_variant_without_executing() -> None:
    payload = mouse_payload(
        AutomationAction("right_click", args={"x": 10, "y": 20})
    )
    assert payload["action_type"] == "mouse_click"
    assert payload["args"]["button"] == "right"
    assert payload["args"]["clicks"] == 1


def test_locator_reuses_screen_vision_ocr(monkeypatch) -> None:
    screenshot = SimpleNamespace(
        image=object(),
        capture_region=(10, 20, 800, 600),
        active_window_title="Editor",
    )
    capture = SimpleNamespace(capture=lambda **_kwargs: screenshot)
    ocr = SimpleNamespace(
        extract_text=lambda _image: OcrResult(
            "Save Cancel",
            blocks=(
                OcrBlock("Save", 0.95, (100, 40, 60, 24)),
                OcrBlock("Cancel", 0.91, (180, 40, 80, 24)),
            ),
        )
    )
    service = SimpleNamespace(capture_backend=capture, ocr_engine=ocr)
    monkeypatch.setattr("grandpa.screen.windows.list_windows", lambda: [])

    matches = ScreenElementLocator(screen_service=service).locate("Save")

    assert matches[0].text == "Save"
    assert matches[0].bounds.left == 110
    assert matches[0].bounds.top == 60
    assert matches[0].confidence >= 0.9


def test_executor_locates_highlights_then_builds_mocked_click() -> None:
    calls: list[dict] = []
    highlights: list[LocatedElement] = []
    executor = AutomationExecutor(
        runner=lambda payload: calls.append(payload) or FakeResponse(),
        locator=FakeLocator(element()),
        highlighter=HighlightOverlay(lambda item, _duration: highlights.append(item)),
    )

    result = executor.execute(AutomationAction("click", "Save"))

    assert result.status == "handled"
    assert calls[0]["action_type"] == "mouse_click"
    assert calls[0]["args"]["x"] == 140
    assert calls[0]["args"]["y"] == 215
    assert highlights == []


def test_service_confirmation_is_single_use_and_no_real_click_occurs() -> None:
    calls: list[dict] = []
    fake_element = element("Delete")
    executor = AutomationExecutor(
        runner=lambda payload: calls.append(payload) or FakeResponse(),
        locator=FakeLocator(fake_element),
        highlighter=HighlightOverlay(lambda _item, _duration: None),
    )
    service = ScreenAutomationService(
        executor=executor,
        confirmations=ConfirmationManager(),
        window_targets=FakeWindowTargets(),
    )

    pending = service.handle("click Delete", target_window="Notepad")
    assert pending.status == "needs_confirmation"
    assert pending.confirmation_token
    assert calls == []

    completed = service.confirm(pending.confirmation_token)
    assert completed.status == "handled"
    assert len(calls) == 1

    reused = service.confirm(pending.confirmation_token)
    assert reused.status == "error"
    assert len(calls) == 1


def test_service_accepts_explicit_yes_on_next_turn() -> None:
    calls: list[dict] = []
    executor = AutomationExecutor(
        runner=lambda payload: calls.append(payload) or FakeResponse(),
        locator=FakeLocator(element("Save")),
        highlighter=HighlightOverlay(lambda _item, _duration: None),
    )
    service = ScreenAutomationService(executor=executor, window_targets=FakeWindowTargets())

    pending = service.handle("click Save", target_window="Notepad")
    completed = service.handle("yes")

    assert pending.status == "needs_confirmation"
    assert completed.status == "handled"
    assert len(calls) == 1


def test_yes_without_pending_does_not_match_automation() -> None:
    service = ScreenAutomationService()
    assert service.handle("yes").status == "no_match"


def test_automation_log_does_not_include_typed_text(caplog) -> None:
    executor = AutomationExecutor(runner=lambda _payload: FakeResponse())
    service = ScreenAutomationService(executor=executor, window_targets=FakeWindowTargets())

    with caplog.at_level(logging.INFO, logger="grandpa.automation.service"):
        result = service.handle("type private message", target_window="Notepad")

    assert result.status == "handled"
    assert "private message" not in caplog.text
    assert "target=[redacted]" in caplog.text


def test_highlight_never_executes_input() -> None:
    calls: list[dict] = []
    highlighted: list[str] = []
    executor = AutomationExecutor(
        runner=lambda payload: calls.append(payload) or FakeResponse(),
        locator=FakeLocator(element()),
        highlighter=HighlightOverlay(
            lambda item, _duration: highlighted.append(item.text)
        ),
    )

    result = executor.execute(AutomationAction("highlight", "Save"))

    assert result.status == "handled"
    assert highlighted == ["Save"]
    assert calls == []


def test_ambiguous_match_does_not_click() -> None:
    calls: list[dict] = []
    executor = AutomationExecutor(
        runner=lambda payload: calls.append(payload) or FakeResponse(),
        locator=FakeLocator(element("Save", 0.91), element("Save As", 0.89)),
        highlighter=HighlightOverlay(lambda _item, _duration: None),
    )

    result = executor.execute(AutomationAction("click", "Save"))

    assert result.status == "ambiguous"
    assert calls == []


def test_chat_natural_router_handles_automation_without_llm(monkeypatch) -> None:
    from grandpa.automation.models import AutomationResult
    from grandpa.cli.chat_cmd import _handle_natural_assistant_intent

    monkeypatch.setattr(
        "grandpa.automation.handle_automation_command",
        lambda _text: AutomationResult("handled", "Scrolled down."),
    )

    assert _handle_natural_assistant_intent("scroll down") == "Scrolled down."


def test_voice_operator_routes_screen_automation() -> None:
    from grandpa.voice.operator import parse_voice_operator_command

    intent = parse_voice_operator_command("click Save")
    assert intent.kind == "screen_automation"
    assert intent.requires_confirmation is True


def test_unrelated_chat_does_not_match() -> None:
    assert AutomationPlanner().parse("tell me a joke") is None


def test_explicit_target_is_verified_before_typing() -> None:
    calls: list[dict] = []
    targets = FakeWindowTargets()
    service = ScreenAutomationService(
        executor=AutomationExecutor(runner=lambda payload: calls.append(payload) or FakeResponse()),
        window_targets=targets,
    )

    result = service.handle("type Hello", target_window="Notepad")

    assert result.status == "handled"
    assert targets.calls == [("Notepad", False)]
    assert calls[0]["action_type"] == "keyboard_type"
    assert "Verified active window" in result.message


def test_press_enter_and_coordinate_move_use_existing_pc_control_payloads() -> None:
    calls: list[dict] = []
    service = ScreenAutomationService(
        executor=AutomationExecutor(runner=lambda payload: calls.append(payload) or FakeResponse()),
        window_targets=FakeWindowTargets(),
    )

    pressed = service.handle("press enter", target_window="Notepad")
    moved = service.handle("move mouse to 300 300")

    assert pressed.status == "handled"
    assert moved.status == "handled"
    assert calls[0]["action_type"] == "keyboard_hotkey"
    assert calls[0]["args"]["keys"] == ["enter"]
    assert calls[1]["action_type"] == "mouse_move"
    assert calls[1]["args"]["x"] == 300
    assert calls[1]["args"]["y"] == 300


def test_focus_failure_and_terminal_focus_prevent_typing() -> None:
    calls: list[dict] = []
    targets = FakeWindowTargets(ok=False, actual_title="Windows Terminal")
    service = ScreenAutomationService(
        executor=AutomationExecutor(runner=lambda payload: calls.append(payload) or FakeResponse()),
        window_targets=targets,
    )

    result = service.handle("type Hello", target_window="Notepad")

    assert result.status == "blocked"
    assert "Windows Terminal" in result.message
    assert "No input was sent" in result.message
    assert calls == []


def test_confirmation_revalidates_target_before_click() -> None:
    calls: list[dict] = []
    targets = FakeWindowTargets()
    service = ScreenAutomationService(
        executor=AutomationExecutor(
            runner=lambda payload: calls.append(payload) or FakeResponse(),
            locator=FakeLocator(element("Save")),
            highlighter=HighlightOverlay(lambda _item, _duration: None),
        ),
        window_targets=targets,
    )

    pending = service.handle("click Save", target_window="Notepad")
    result = service.confirm(pending.confirmation_token or "")

    assert result.status == "handled"
    assert targets.calls == [("Notepad", False), ("Notepad", False)]
    assert len(calls) == 1


def test_pinned_target_is_session_local() -> None:
    calls: list[dict] = []
    targets = FakeWindowTargets()
    service = ScreenAutomationService(
        executor=AutomationExecutor(runner=lambda payload: calls.append(payload) or FakeResponse()),
        window_targets=targets,
    )

    assert service.handle("focus Notepad").status == "handled"
    assert service.handle("type Hello").status == "handled"
    assert targets.calls == [("notepad", False), ("notepad", False)]
    service.clear_target()
    assert service.handle("press enter").status == "blocked"

    fresh = ScreenAutomationService(
        executor=AutomationExecutor(runner=lambda payload: calls.append(payload) or FakeResponse()),
        window_targets=targets,
    )
    assert fresh.handle("type leaked").status == "blocked"


def test_chat_retains_target_within_one_session() -> None:
    from grandpa.cli.chat_cmd import _handle_natural_assistant_intent

    calls: list[dict] = []
    service = ScreenAutomationService(
        executor=AutomationExecutor(runner=lambda payload: calls.append(payload) or FakeResponse()),
        window_targets=FakeWindowTargets(),
    )

    assert "pinned target" in (
        _handle_natural_assistant_intent(
            "Focus Notepad", automation_service=service
        )
        or ""
    )
    assert "Text typed" in (
        _handle_natural_assistant_intent(
            "Type Hello from chat", automation_service=service
        )
        or ""
    )
    assert calls[0]["action_type"] == "keyboard_type"


def test_voice_retains_target_within_one_session() -> None:
    from grandpa.voice.operator import (
        execute_voice_operator_intent,
        parse_voice_operator_command,
    )

    calls: list[dict] = []
    def runner(payload):
        calls.append(payload)
        return FakeResponse()
    service = ScreenAutomationService(
        executor=AutomationExecutor(runner=runner),
        window_targets=FakeWindowTargets(),
    )

    focused = execute_voice_operator_intent(
        parse_voice_operator_command("focus Notepad"),
        action_runner=runner,
        automation_service=service,
    )
    typed = execute_voice_operator_intent(
        parse_voice_operator_command("type Hello from voice"),
        action_runner=runner,
        automation_service=service,
    )

    assert focused.status == "handled"
    assert typed.status == "handled"
    assert calls[0]["action_type"] == "keyboard_type"


def test_window_controller_uses_handle_identity_and_protects_terminals() -> None:
    expected = WindowIdentity(10, "Notepad", 100, "notepad.exe", "Notepad")
    terminal = WindowIdentity(20, "Windows Terminal", 200, "WindowsTerminal.exe")
    focused: list[int] = []
    controller = WindowTargetController(
        resolve_func=lambda _target: expected,
        foreground_func=lambda: terminal,
        focus_func=focused.append,
        sleep_func=lambda _seconds: None,
        timeout=0,
    )

    result = controller.focus_and_verify("Notepad")

    assert result.ok is False
    assert focused == [10]
    assert "Windows Terminal" in result.message


def test_locator_formats_exactly_one_pair_of_quotes() -> None:
    executor = AutomationExecutor(
        locator=FakeLocator(element('"Save"')),
        highlighter=HighlightOverlay(lambda _item, _duration: None),
    )

    result = executor.execute(AutomationAction("locate", "Save"))

    assert 'Found "Save"' in result.message
    assert '""Save""' not in result.message
