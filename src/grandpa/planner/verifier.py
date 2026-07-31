"""Postcondition verification for planner steps."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote_plus, urlparse

from grandpa.automation.windows import WindowTargetResolutionError
from grandpa.planner.models import PlanStep, StepResult


class StepVerifier:
    def __init__(
        self,
        executor,
        *,
        browser_awareness: Callable[[str], Any] | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self.executor = executor
        self._browser_awareness = browser_awareness
        self._sleep = sleep_func

    def verify(self, step: PlanStep, result: StepResult) -> StepResult:
        if result.status != "success":
            return result
        if result.data.get("dry_run"):
            return result
        try:
            return self._verify(step, result)
        except WindowTargetResolutionError as exc:
            return _failed(result, str(exc), status="target_lost")
        except Exception as exc:
            return _failed(
                result,
                f"The step result could not be verified safely ({exc.__class__.__name__}).",
            )

    def _verify(self, step: PlanStep, result: StepResult) -> StepResult:
        strategy = step.verification.strategy
        if strategy == "execution_success":
            return _verified(result, strategy)
        if strategy in {"application_window_exists", "application_window_focused"}:
            app = str(step.parameters.get("app") or "")
            window = self._pinned_or_resolved_window(app)
            if window is None:
                return _failed(
                    result,
                    f"I could not verify the {app.title()} window.",
                    status="target_lost",
                )
            if strategy == "application_window_focused":
                check = self.executor.automation_service.window_targets.verify_foreground(
                    window
                )
                if not check.ok:
                    return _failed(result, check.message, status="target_lost")
            return _verified(result, strategy)
        if strategy == "element_visible":
            name = str(step.parameters.get("name") or "")
            found = self.executor.vision_engine.find(
                name, actionable=bool(step.parameters.get("actionable", False))
            )
            return (
                _verified(result, strategy)
                if found.matches
                else _failed(result, found.message)
            )
        if strategy == "text_visible":
            expected = str(
                step.verification.parameters.get("text")
                or step.parameters.get("name")
                or ""
            )
            visible = self.executor.vision_engine.read().message.casefold()
            return (
                _verified(result, strategy)
                if expected.casefold() in visible
                else _failed(result, f'I could not verify visible text "{expected}".')
            )
        if strategy == "dialog_present":
            return (
                _verified(result, strategy)
                if self.executor.automation_service.has_pending_dialog
                else _failed(result, "The expected verified dialog did not appear.")
            )
        if strategy == "dialog_absent":
            return (
                _verified(result, strategy)
                if not self.executor.automation_service.has_pending_dialog
                else _failed(result, "The verified dialog is still open.")
            )
        if strategy == "document_closed":
            return (
                _verified(result, strategy)
                if self.executor.automation_service.target_window is None
                else _failed(result, "The target document is still open.")
            )
        if strategy == "document_open":
            target = self.executor.automation_service.target_window
            if target is not None and self._window_ready(target):
                return _verified(result, strategy)
            return _failed(result, "The original document could not be verified open.")
        if strategy in {"typed_text_present", "calculator_expression_visible"}:
            expected = str(
                step.parameters.get("text")
                or step.parameters.get("expression")
                or ""
            )
            visible = (
                self._calculator_visible_text()
                if strategy == "calculator_expression_visible"
                else self.executor.vision_engine.read().message
            )
            matched = (
                _calculator_expression_matches(expected, visible)
                if strategy == "calculator_expression_visible"
                else _normalized_visible_value(expected)
                in _normalized_visible_value(visible)
            )
            if expected and matched:
                return _verified(result, strategy)
            return _failed(
                result, "The entered text could not be observed in the verified target."
            )
        if strategy == "calculator_result":
            expected = str(step.parameters.get("expected_result") or "")
            visible = self._calculator_visible_text()
            if expected and _numeric_value(expected) in _numeric_value(visible):
                return _verified(
                    result,
                    strategy,
                    evidence={"calculator_result": expected},
                )
            return _failed(
                result,
                f"Calculator did not expose the expected result {expected}.",
            )
        if strategy == "focused_control_matches":
            focused = self.executor.vision_engine.focused()
            if focused is not None:
                return _verified(result, strategy)
            return _failed(result, "The focused control could not be verified.")
        if strategy in {"target_state_changed", "screen_changed"}:
            if result.data.get("state_changed") is True:
                return _verified(result, strategy)
            return _failed(
                result, "The visible semantic state did not change after the action."
            )
        if strategy == "browser_results_visible":
            return self._verify_browser_results(step, result)
        if strategy == "URL_matches":
            expected = str(
                step.verification.parameters.get("url")
                or step.parameters.get("url")
                or ""
            )
            actual = str(result.data.get("url") or "")
            if actual and (not expected or expected.casefold() in actual.casefold()):
                return _verified(result, strategy)
            return _failed(result, "The browser URL could not be verified.")
        if strategy in {"file_exists", "file_saved"}:
            path = step.verification.parameters.get("path") or step.parameters.get(
                "path"
            )
            if path and Path(str(path)).expanduser().is_file():
                return _verified(result, strategy)
            return _failed(result, "The expected file state was not verified.")
        return _failed(result, f"Unsupported verification strategy: {strategy}")

    def _pinned_or_resolved_window(self, app: str):
        service = self.executor.automation_service
        pinned = service.target_window
        if pinned is not None and _window_matches_app(pinned, app):
            if self._window_ready(pinned):
                return pinned
            service.clear_target()
        return service.window_targets.resolve(app)

    def _window_ready(self, window) -> bool:
        check = getattr(self.executor.automation_service.window_targets, "is_ready", None)
        return bool(check(window)) if callable(check) else True

    def _calculator_visible_text(self) -> str:
        service = self.executor.automation_service
        target = service.target_window
        read_controls = getattr(service.window_targets, "read_controls", None)
        if target is not None and callable(read_controls):
            values = read_controls(
                target,
                ("CalculatorExpression", "CalculatorResults"),
            )
            observed = "\n".join(str(value) for value in values.values() if value)
            if observed:
                return observed
        return self.executor.vision_engine.read().message

    def _verify_browser_results(
        self, step: PlanStep, result: StepResult
    ) -> StepResult:
        query = str(step.parameters.get("query") or "")
        requested_url = str(result.data.get("url") or "")
        deadline = time.monotonic() + min(max(step.timeout_seconds, 0.1), 6.0)
        last_snapshot = None
        while time.monotonic() < deadline:
            awareness = self._browser_awareness_result()
            snapshot = getattr(awareness, "snapshot", None)
            if snapshot is not None:
                last_snapshot = snapshot
                semantic_text = " ".join(
                    (
                        str(getattr(snapshot, "title", "")),
                        str(getattr(snapshot, "url", "")),
                        str(getattr(snapshot, "visible_text", ""))[:2000],
                    )
                )
                if _query_matches_text(query, semantic_text):
                    return _verified(
                        result,
                        "browser_results_visible",
                        evidence={
                            "browser_evidence": "visible_page",
                            "observed_url": str(getattr(snapshot, "url", "")),
                        },
                    )
            self._sleep(0.2)
        if requested_url and _search_url_matches(query, requested_url):
            return _verified(
                result,
                "browser_results_visible",
                status="partial_success",
                evidence={
                    "browser_evidence": "navigation_requested",
                    "requested_url": requested_url,
                    "page_observed": last_snapshot is not None,
                },
            )
        return _failed(result, "The browser results page could not be verified.")

    def _browser_awareness_result(self):
        if self._browser_awareness is None:
            from grandpa.browser_awareness import handle_browser_awareness_command

            self._browser_awareness = handle_browser_awareness_command
        try:
            return self._browser_awareness("show current url")
        except Exception:
            return None


def _window_matches_app(window: Any, app: str) -> bool:
    wanted = app.casefold().replace("_", " ")
    values = " ".join(
        (
            str(getattr(window, "target", "")),
            str(getattr(window, "title", "")),
            str(getattr(window, "process_name", "")),
        )
    ).casefold()
    aliases = {
        "calculator": ("calculator", "calculatorapp", "calculatorapp.exe"),
        "vscode": ("visual studio code", "code.exe", "vscode"),
        "chrome": ("chrome", "chrome.exe"),
    }.get(wanted, (wanted,))
    return any(alias in values for alias in aliases)


def _normalized_visible_value(value: str) -> str:
    return re.sub(r"\s+", "", value.casefold().replace("×", "*").replace("÷", "/"))


def _numeric_value(value: str) -> str:
    return re.sub(r"[^0-9.-]", "", value)


def _calculator_expression_matches(expected: str, visible: str) -> bool:
    expected_tokens = re.findall(
        r"\d+(?:\.\d+)?|[+*/-]", _normalized_visible_value(expected)
    )
    visible_tokens = re.findall(
        r"\d+(?:\.\d+)?|[+*/-]", _normalized_visible_value(visible)
    )
    if not expected_tokens:
        return False
    position = 0
    for token in visible_tokens:
        if token == expected_tokens[position]:
            position += 1
            if position == len(expected_tokens):
                return True
    return False


def _query_matches_text(query: str, text: str) -> bool:
    terms = re.findall(r"[a-z0-9]+", query.casefold())
    normalized = " ".join(re.findall(r"[a-z0-9]+", text.casefold()))
    return bool(terms) and all(term in normalized for term in terms)


def _search_url_matches(query: str, url: str) -> bool:
    try:
        parsed = urlparse(url)
        values = parse_qs(parsed.query)
        observed = " ".join(
            values.get("q", []) + values.get("query", []) + values.get("search_query", [])
        )
        return _query_matches_text(query, unquote_plus(observed))
    except (TypeError, ValueError):
        return False


def _verified(
    result: StepResult,
    strategy: str,
    *,
    semantic: bool = True,
    status: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> StepResult:
    return StepResult(
        status or result.status,
        result.message,
        result.step_id,
        {
            **result.data,
            **(evidence or {}),
            "verified": True,
            "verification_strategy": strategy,
            "semantic_verification": semantic,
        },
        result.confirmation_token,
    )


def _failed(result: StepResult, message: str, *, status: str = "verification_failed") -> StepResult:
    return StepResult(
        status,
        message,
        result.step_id,
        {**result.data, "verified": False},
        result.confirmation_token,
    )


__all__ = ["StepVerifier"]
