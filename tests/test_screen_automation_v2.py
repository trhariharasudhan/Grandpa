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
    DialogIdentity,
    WindowCloseResult,
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


class TrackingWindowTargets(FakeWindowTargets):
    def __init__(self, *, drift_after_action: bool = False) -> None:
        super().__init__()
        self.raw_targets: list[object] = []
        self.drift_after_action = drift_after_action

    def focus_and_verify(self, target, *, dry_run: bool = False):
        self.raw_targets.append(target)
        return super().focus_and_verify(target, dry_run=dry_run)

    def verify_foreground(self, expected: WindowIdentity):
        actual = (
            WindowIdentity(20, "Windows Terminal", 200, "WindowsTerminal.exe")
            if self.drift_after_action
            else expected
        )
        return WindowVerification(
            not self.drift_after_action,
            (
                f"Verified active window: {actual.title}."
                if not self.drift_after_action
                else "The target window changed during the action. "
                "Expected Notepad, but Windows Terminal is active."
            ),
            expected,
            actual,
        )


class DialogWindowTargets:
    def __init__(
        self,
        close_status: str = "dialog_pending",
        response_status: str = "closed",
    ) -> None:
        self.window = WindowIdentity(
            10,
            "Untitled - Notepad",
            101,
            "notepad.exe",
            "notepad",
        )
        self.dialog = DialogIdentity(
            20,
            "Notepad",
            101,
            10,
            "notepad_unsaved",
        )
        self.save_as = DialogIdentity(
            30,
            "Save As",
            101,
            10,
            "save_as",
        )
        self.close_status = close_status
        self.response_status = response_status
        self.responses: list[tuple[DialogIdentity, str]] = []
        self.saved_paths: list[tuple[str, bool]] = []

    def focus_and_verify(self, target, *, dry_run: bool = False):
        return WindowVerification(True, "Focused.", self.window, self.window)

    def close_and_verify(self, target, *, dry_run: bool = False):
        if self.close_status == "dialog_pending":
            return WindowCloseResult(
                "dialog_pending",
                "Notepad has unsaved changes.",
                self.window,
                self.dialog,
            )
        if self.close_status == "closed":
            return WindowCloseResult("closed", "Closed Notepad.", self.window)
        return WindowCloseResult("failed", "Notepad did not close.", self.window)

    def respond_to_dialog(self, window, dialog, choice):
        self.responses.append((dialog, choice))
        if self.response_status == "save_as_pending":
            return WindowCloseResult(
                "save_as_pending",
                "A Save As dialog is open.",
                self.window,
                self.save_as,
            )
        if self.response_status == "cancelled":
            return WindowCloseResult(
                "cancelled",
                "Close cancelled. Notepad remains open.",
                self.window,
            )
        if self.response_status == "closed":
            return WindowCloseResult(
                "closed",
                "Closed Notepad without saving.",
                self.window,
            )
        return WindowCloseResult(
            "failed",
            "The dialog action timed out.",
            self.window,
            dialog,
        )

    def save_as_and_verify(
        self,
        window,
        dialog,
        path,
        *,
        allow_overwrite: bool = False,
    ):
        self.saved_paths.append((path, allow_overwrite))
        return WindowCloseResult(
            "closed",
            "Saved and closed Notepad.",
            self.window,
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
        ("select all", "press"),
        ("copy this", "press"),
        ("paste this", "press"),
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


@pytest.mark.parametrize(
    "command, expected_text",
    [
        ("Type unsaved close test", "unsaved close test"),
        ("Type delete all files", "delete all files"),
        ("Type shutdown the computer", "shutdown the computer"),
        ("Type send payment", "send payment"),
    ],
)
def test_literal_typing_is_not_reinterpreted_as_destructive_command(
    command: str, expected_text: str
) -> None:
    action = AutomationPlanner().parse(command)

    assert action is not None
    assert action.kind == "type"
    assert action.args["text"] == expected_text
    assert action.requires_confirmation is False
    assert action.sensitive is False


def test_literal_typing_still_applies_sensitive_data_policy() -> None:
    action = AutomationPlanner().parse("Type my password is example")

    assert action is not None
    assert action.kind == "type"
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
    from types import SimpleNamespace

    from grandpa.cli.chat_cmd import _handle_natural_assistant_intent

    monkeypatch.setattr(
        "grandpa.automation.WindowsCommandPipeline.handle",
        lambda _self, _text, **_kwargs: SimpleNamespace(
            should_fallback=False,
            message="Scrolled down.",
        ),
    )

    assert _handle_natural_assistant_intent("scroll down") == "Scrolled down."


def test_voice_operator_routes_screen_automation() -> None:
    from grandpa.voice.operator import parse_voice_operator_command

    intent = parse_voice_operator_command("click Save")
    assert intent.kind == "screen_automation"
    assert intent.requires_confirmation is True


def test_voice_operator_confirmation_state_is_explicit_and_session_local() -> None:
    from grandpa.voice.operator import parse_voice_operator_command

    without_pending = parse_voice_operator_command("yes")
    with_pending = parse_voice_operator_command(
        "yes",
        has_pending_confirmation=True,
    )

    assert without_pending.kind != "screen_automation"
    assert with_pending.kind == "screen_automation"
    assert with_pending.action == "confirmation"


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


def test_pinned_target_reuses_window_handle_instead_of_title_lookup() -> None:
    targets = TrackingWindowTargets()
    service = ScreenAutomationService(
        executor=AutomationExecutor(runner=lambda _payload: FakeResponse()),
        window_targets=targets,
    )

    assert service.handle("focus Notepad").status == "handled"
    result = service.handle("type Hello")

    assert result.status == "handled"
    assert isinstance(targets.raw_targets[1], WindowIdentity)
    assert result.data["verified"] is True
    assert result.data["window_handle"] == 10
    assert result.data["process_id"] == 100


def test_foreground_change_after_typing_returns_target_lost_and_clears_target() -> None:
    targets = TrackingWindowTargets(drift_after_action=True)
    calls: list[dict] = []
    service = ScreenAutomationService(
        executor=AutomationExecutor(
            runner=lambda payload: calls.append(payload) or FakeResponse()
        ),
        window_targets=targets,
    )

    assert service.handle("focus Notepad").status == "handled"
    result = service.handle("type Hello")

    assert result.status == "target_lost"
    assert "stopped" in result.message
    assert service.target_window is None
    assert len(calls) == 1


def test_closed_pinned_window_stops_before_sending_more_input() -> None:
    expected = WindowIdentity(10, "Untitled - Notepad", 100, "notepad.exe", "notepad")
    available = True
    calls: list[dict] = []

    def focus(handle: int) -> None:
        if not available:
            raise OSError("window handle is gone")

    controller = WindowTargetController(
        resolve_func=lambda _target: expected,
        foreground_func=lambda: expected,
        focus_func=focus,
        sleep_func=lambda _seconds: None,
        timeout=0,
    )
    service = ScreenAutomationService(
        executor=AutomationExecutor(
            runner=lambda payload: calls.append(payload) or FakeResponse()
        ),
        window_targets=controller,
    )

    assert service.handle("focus Notepad").status == "handled"
    available = False
    result = service.handle("press enter")

    assert result.status == "target_lost"
    assert "no longer available" in result.message
    assert calls == []


def test_multiple_similar_windows_return_friendly_ambiguity(monkeypatch) -> None:
    from grandpa.automation.windows import resolve_window
    from grandpa.windows_window_control import WindowControlResult, WindowInfo

    monkeypatch.setattr("grandpa.automation.windows.sys.platform", "win32")
    monkeypatch.setattr(
        "grandpa.windows_window_control._resolve_window",
        lambda _target: WindowControlResult(
            "multiple_matches",
            "focus",
            "notepad",
            "I found multiple Notepad windows. Please clarify:\n- First.txt - Notepad\n- Second.txt - Notepad",
            (
                WindowInfo(10, "First.txt - Notepad", process_id=101),
                WindowInfo(20, "Second.txt - Notepad", process_id=202),
            ),
        ),
    )
    service = ScreenAutomationService(
        window_targets=WindowTargetController(resolve_func=resolve_window)
    )

    result = service.handle("focus Notepad")

    assert result.status == "ambiguous"
    assert result.message.splitlines() == [
        "I found multiple matching windows. Which one?",
        "1. First.txt - Notepad",
        "2. Second.txt - Notepad",
    ]
    assert result.data["window_choices"] == [
        {"title": "First.txt - Notepad", "hwnd": 10, "pid": 101},
        {"title": "Second.txt - Notepad", "hwnd": 20, "pid": 202},
    ]
    assert "101" not in result.message
    assert "202" not in result.message


def test_ambiguity_followups_select_by_ordinal_or_exact_title() -> None:
    first = WindowIdentity(10, "First.txt - Notepad", 101, "notepad.exe", "notepad")
    second = WindowIdentity(20, "Second.txt - Notepad", 202, "notepad.exe", "notepad")

    class AmbiguousTargets:
        def __init__(self) -> None:
            self.focused: list[WindowIdentity] = []

        def focus_and_verify(self, target, *, dry_run: bool = False):
            if isinstance(target, str):
                return WindowVerification(
                    False,
                    "Multiple windows.",
                    candidates=(first, second),
                )
            self.focused.append(target)
            return WindowVerification(True, "Focused.", target, target)

    targets = AmbiguousTargets()
    service = ScreenAutomationService(window_targets=targets)

    assert service.handle("focus Notepad").status == "ambiguous"
    chosen = service.handle("focus option two")
    assert chosen.status == "handled"
    assert targets.focused == [second]
    assert service.target_window == second

    service.clear_target()
    assert service.handle("focus Notepad").status == "ambiguous"
    exact = service.handle("First.txt - Notepad")
    assert exact.status == "handled"
    assert targets.focused[-1] == first


def test_window_ambiguity_is_isolated_per_session() -> None:
    choice = WindowIdentity(10, "First.txt - Notepad", 101, "notepad.exe", "notepad")

    class AmbiguousTargets:
        def focus_and_verify(self, target, *, dry_run: bool = False):
            if isinstance(target, str):
                return WindowVerification(False, "Multiple windows.", candidates=(choice,))
            return WindowVerification(True, "Focused.", target, target)

    first_session = ScreenAutomationService(window_targets=AmbiguousTargets())
    second_session = ScreenAutomationService(window_targets=AmbiguousTargets())

    assert first_session.handle("focus Notepad").status == "ambiguous"
    assert second_session.handle("choose the first one").status == "no_match"
    assert first_session.handle("choose the first one").status == "handled"


def test_close_uses_pinned_hwnd_requires_confirmation_and_verifies() -> None:
    target = WindowIdentity(10, "Untitled - Notepad", 101, "notepad.exe", "notepad")

    class CloseTargets:
        def __init__(self, *, closes: bool = True) -> None:
            self.closes = closes
            self.closed: list[WindowIdentity] = []

        def focus_and_verify(self, selected, *, dry_run: bool = False):
            return WindowVerification(True, "Focused.", target, target)

        def close_and_verify(self, selected, *, dry_run: bool = False):
            self.closed.append(selected)
            return WindowVerification(
                self.closes,
                "Closed Notepad." if self.closes else "Notepad did not close.",
                selected,
            )

    targets = CloseTargets()
    service = ScreenAutomationService(window_targets=targets)

    assert service.handle("focus Notepad").status == "handled"
    pending = service.handle("Close Notepad")
    assert pending.status == "needs_confirmation"
    assert targets.closed == []

    closed = service.handle("yes")
    assert closed.status == "handled"
    assert closed.message == "Closed Notepad."
    assert closed.data["verified"] is True
    assert targets.closed == [target]
    assert service.target_window is None


def test_close_failure_is_not_reported_as_success() -> None:
    target = WindowIdentity(10, "Untitled - Notepad", 101, "notepad.exe", "notepad")

    class CloseTargets:
        def focus_and_verify(self, selected, *, dry_run: bool = False):
            return WindowVerification(True, "Focused.", target, target)

        def close_and_verify(self, selected, *, dry_run: bool = False):
            return WindowVerification(False, "Notepad did not close.", selected)

    service = ScreenAutomationService(window_targets=CloseTargets())
    assert service.handle("focus Notepad").status == "handled"
    pending = service.handle("close Notepad")

    result = service.confirm(pending.confirmation_token or "")

    assert result.status == "failed"
    assert result.message == "Notepad did not close."
    assert result.data["verified"] is False


def test_unsaved_notepad_returns_verified_pending_dialog() -> None:
    targets = DialogWindowTargets()
    service = ScreenAutomationService(window_targets=targets)
    assert service.handle("focus Notepad").status == "handled"

    pending = service.handle("close Notepad")
    result = service.confirm(pending.confirmation_token or "")

    assert result.status == "dialog_pending"
    assert result.message == (
        "Notepad has unsaved changes. Save, don't save, or cancel?"
    )
    assert result.data["dialog"] == {
        "title": "Notepad",
        "kind": "notepad_unsaved",
        "hwnd": 20,
        "pid": 101,
        "owner_hwnd": 10,
    }
    assert service.has_pending_dialog is True


def test_dont_save_closes_verified_notepad_and_clears_target() -> None:
    targets = DialogWindowTargets(response_status="closed")
    service = ScreenAutomationService(window_targets=targets)
    service.handle("focus Notepad")
    pending = service.handle("close Notepad")
    service.confirm(pending.confirmation_token or "")

    result = service.handle("don't save")

    assert result.status == "handled"
    assert result.message == "Closed Notepad without saving."
    assert result.data["verified"] is True
    assert targets.responses == [(targets.dialog, "discard")]
    assert service.target_window is None
    assert service.has_pending_dialog is False


def test_save_transitions_to_save_as_pending_state() -> None:
    targets = DialogWindowTargets(response_status="save_as_pending")
    service = ScreenAutomationService(window_targets=targets)
    service.handle("focus Notepad")
    pending = service.handle("close Notepad")
    service.confirm(pending.confirmation_token or "")

    result = service.handle("save changes")

    assert result.status == "dialog_pending"
    assert result.message == (
        "A Save As dialog is open. What filename or path should I use?"
    )
    assert result.data["dialog"]["kind"] == "save_as"
    assert service.target_window == targets.window
    assert service.has_pending_dialog is True


def test_save_as_accepts_path_and_avoids_unconfirmed_overwrite(tmp_path) -> None:
    targets = DialogWindowTargets(response_status="save_as_pending")
    service = ScreenAutomationService(window_targets=targets)
    service.handle("focus Notepad")
    pending = service.handle("close Notepad")
    service.confirm(pending.confirmation_token or "")
    service.handle("save")

    path = tmp_path / "note.txt"
    saved = service.handle(str(path))

    assert saved.status == "handled"
    assert targets.saved_paths == [(str(path), False)]
    assert service.target_window is None

    path.write_text("existing", encoding="utf-8")
    second_targets = DialogWindowTargets(response_status="save_as_pending")
    second = ScreenAutomationService(window_targets=second_targets)
    second.handle("focus Notepad")
    close_pending = second.handle("close Notepad")
    second.confirm(close_pending.confirmation_token or "")
    second.handle("save")

    overwrite = second.handle(str(path))
    assert overwrite.status == "needs_confirmation"
    assert second_targets.saved_paths == []

    completed = second.handle("yes")
    assert completed.status == "handled"
    assert second_targets.saved_paths == [(str(path), True)]


def test_cancel_dialog_preserves_pinned_notepad() -> None:
    targets = DialogWindowTargets(response_status="cancelled")
    service = ScreenAutomationService(window_targets=targets)
    service.handle("focus Notepad")
    pending = service.handle("close Notepad")
    service.confirm(pending.confirmation_token or "")

    result = service.handle("cancel")

    assert result.status == "cancelled"
    assert result.message == "Close cancelled. Notepad remains open."
    assert service.target_window == targets.window
    assert service.has_pending_dialog is False


def test_failed_dialog_action_never_reports_success() -> None:
    targets = DialogWindowTargets(response_status="failed")
    service = ScreenAutomationService(window_targets=targets)
    service.handle("focus Notepad")
    pending = service.handle("close Notepad")
    service.confirm(pending.confirmation_token or "")

    result = service.handle("discard changes")

    assert result.status == "failed"
    assert result.data["verified"] is False
    assert "timed out" in result.message


def test_pending_dialog_state_is_session_local() -> None:
    first = ScreenAutomationService(window_targets=DialogWindowTargets())
    second = ScreenAutomationService(window_targets=DialogWindowTargets())
    first.handle("focus Notepad")
    pending = first.handle("close Notepad")
    first.confirm(pending.confirmation_token or "")

    assert first.has_pending_dialog is True
    assert second.has_pending_dialog is False
    assert second.handle("don't save").status == "no_match"


def test_window_controller_dialog_choices_verify_expected_outcomes() -> None:
    window = WindowIdentity(
        10, "Untitled - Notepad", 101, "notepad.exe", "notepad"
    )
    unsaved = DialogIdentity(
        20, "Notepad", 101, 10, "notepad_unsaved"
    )
    save_as = DialogIdentity(30, "Save As", 101, 10, "save_as")
    invoked: list[str] = []

    discard_controller = WindowTargetController(
        dialog_choice_func=lambda _dialog, _window, choice: (
            invoked.append(choice) or True
        ),
        dialog_detect_func=lambda _window: None,
        exists_func=lambda _handle: False,
    )
    discarded = discard_controller.respond_to_dialog(
        window, unsaved, "discard"
    )

    assert discarded.status == "closed"
    assert invoked == ["discard"]

    save_controller = WindowTargetController(
        dialog_choice_func=lambda *_args: True,
        dialog_detect_func=lambda _window: save_as,
        exists_func=lambda _handle: True,
    )
    saved = save_controller.respond_to_dialog(window, unsaved, "save")

    assert saved.status == "save_as_pending"
    assert saved.dialog == save_as


def test_window_controller_rejects_dialog_from_wrong_process_or_owner() -> None:
    window = WindowIdentity(
        10, "Untitled - Notepad", 101, "notepad.exe", "notepad"
    )
    wrong = DialogIdentity(
        20, "Notepad", 999, 77, "notepad_unsaved"
    )
    invoked: list[str] = []
    controller = WindowTargetController(
        dialog_choice_func=lambda _dialog, _window, choice: (
            invoked.append(choice) or True
        )
    )

    result = controller.respond_to_dialog(window, wrong, "discard")

    assert result.status == "failed"
    assert "no longer belongs" in result.message
    assert invoked == []


def test_dialog_discard_verifies_document_removed_while_notepad_window_remains() -> None:
    window = WindowIdentity(
        10,
        "Second - Notepad",
        101,
        "notepad.exe",
        "notepad",
        "doc-second",
        "Second",
    )
    dialog = DialogIdentity(10, "Notepad", 101, 10, "notepad_unsaved")
    controller = WindowTargetController(
        dialog_choice_func=lambda *_args: True,
        dialog_detect_func=lambda _window: None,
        exists_func=lambda _handle: True,
        document_exists_func=lambda _window: False,
    )

    result = controller.respond_to_dialog(window, dialog, "discard")

    assert result.status == "closed"
    assert result.message == "Closed Notepad without saving."


def test_dialog_cancel_preserves_verified_notepad_document() -> None:
    window = WindowIdentity(
        10,
        "Second - Notepad",
        101,
        "notepad.exe",
        "notepad",
        "doc-second",
        "Second",
    )
    dialog = DialogIdentity(10, "Notepad", 101, 10, "notepad_unsaved")
    controller = WindowTargetController(
        dialog_choice_func=lambda *_args: True,
        dialog_detect_func=lambda _window: None,
        exists_func=lambda _handle: True,
        document_exists_func=lambda _window: True,
    )

    result = controller.respond_to_dialog(window, dialog, "cancel")

    assert result.status == "cancelled"
    assert result.window.document_id == "doc-second"


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
