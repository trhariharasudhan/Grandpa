"""Bridge validated plan steps into Grandpa's existing trusted services."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from grandpa.automation import ScreenAutomationService, WindowsCommandPipeline
from grandpa.automation.windows import WindowIdentity, WindowTargetResolutionError
from grandpa.planner.models import PlanStep, StepResult


class PlannerStepExecutor:
    def __init__(
        self,
        *,
        session_id: str,
        automation_service: ScreenAutomationService | None = None,
        browser_handler: Callable[[str], Any] | None = None,
        vision_engine: Any | None = None,
    ) -> None:
        self.session_id = session_id
        self.automation_service = automation_service or ScreenAutomationService()
        self.pipeline = WindowsCommandPipeline(
            automation_service=self.automation_service,
            source="planner",
            session_id=session_id,
        )
        self._browser_handler = browser_handler
        self._vision_engine = vision_engine
        self.diagnostics: list[dict[str, Any]] = []
        self._launched_apps: set[str] = set()

    def execute(
        self,
        step: PlanStep,
        *,
        dry_run: bool = False,
        confirmed: bool = False,
    ) -> StepResult:
        if step.requires_confirmation and not confirmed:
            return StepResult(
                "confirmation_required",
                _step_confirmation_message(step),
                step.step_id,
            )
        if dry_run:
            return StepResult(
                "success",
                f"Would execute: {step.description}",
                step.step_id,
                {"dry_run": True, "verified": False},
            )
        try:
            result = self._execute(step, confirmed=confirmed)
            self._record(step, result)
            return result
        except Exception as exc:
            result = StepResult(
                "failed",
                f"The step failed safely ({exc.__class__.__name__}).",
                step.step_id,
            )
            self._record(step, result, error=exc.__class__.__name__)
            return result

    def resolve_clarification(self, step: PlanStep, response: str) -> StepResult:
        """Resolve an existing automation ambiguity without replaying its action."""

        try:
            result = self.pipeline.handle(response)
            return StepResult(
                result.status,
                result.message,
                step.step_id,
                dict(result.data),
                result.confirmation_token,
            )
        except Exception as exc:
            return StepResult(
                "failed",
                f"The clarification failed safely ({exc.__class__.__name__}).",
                step.step_id,
            )

    def _execute(self, step: PlanStep, *, confirmed: bool) -> StepResult:
        action = step.action
        parameters = step.parameters
        if action == "launch_application":
            if parameters.get("project_path"):
                from grandpa.projects import handle_project_command

                command = f"open {parameters['project_path']} project in {parameters['app']}"
                result = handle_project_command(command)
                return _generic_result(step, result)
            prefix = "open another" if parameters.get("new_instance") else "open"
            return self._launch_application(
                step,
                f"{prefix} {parameters['app']}",
            )
        if action == "open_new_application_instance":
            return self._pipeline(step, f"open another {parameters['app']}")
        if action == "focus_window":
            return self._focus_application(step, str(parameters["app"]))
        if action == "close_window":
            result = self._pipeline(step, f"close {parameters['app']}", confirmed=confirmed)
            return result
        if action == "type_text":
            return self._pipeline(step, f"type {parameters['text']}")
        if action == "press_key":
            return self._pipeline(step, f"press {parameters['key']}")
        if action == "press_hotkey":
            keys = parameters["keys"]
            value = "+".join(keys) if isinstance(keys, list) else str(keys)
            return self._pipeline(step, f"press {value}")
        if action == "input_calculator_expression":
            return self._calculator_expression(step, str(parameters["expression"]))
        if action == "invoke_calculator_equals":
            return self._calculator_controls(
                step,
                ("equalButton",),
                success_message="Calculator equals was invoked.",
            )
        if action in {"find_element", "wait_for_element"}:
            return self._find(step, wait=action == "wait_for_element")
        if action == "click_element":
            return self._pipeline(step, f"click {parameters['name']}", confirmed=confirmed)
        if action == "highlight_element":
            return self._pipeline(step, f"highlight {parameters['name']}")
        if action == "focus_element":
            return self._pipeline(step, f"click {parameters['name']}", confirmed=confirmed)
        if action == "read_visible_text":
            return _vision_result(step, self.vision_engine.read())
        if action == "describe_screen":
            return _vision_result(step, self.vision_engine.describe())
        if action == "list_elements":
            types = tuple(parameters.get("types") or ("button", "edit", "hyperlink"))
            return _vision_result(step, self.vision_engine.list_elements(*types))
        if action == "scroll":
            return self._pipeline(step, f"scroll {parameters['direction']} {parameters.get('amount', 5)}")
        if action == "scroll_until":
            return self._pipeline(step, f"scroll {parameters.get('direction', 'down')} until {parameters['name']} appears")
        if action == "wait_for_window":
            return self._wait_for_window(step)
        if action == "navigate_url":
            return self._browser(step, f"open {parameters['url']}")
        if action == "browser_search":
            provider = parameters.get("provider", "google")
            return self._browser(step, f"search {provider} for {parameters['query']}")
        if action == "open_file":
            return self._pipeline(step, f"open {parameters['path']}")
        if action == "open_folder":
            return self._pipeline(step, f"open {parameters['path']}")
        if action == "save_document":
            if parameters.get("path"):
                return StepResult("clarification_required", "Saving to a new path requires the verified Save As flow.", step.step_id)
            return self._pipeline(step, "press ctrl s", confirmed=confirmed)
        if action == "invoke_verified_dialog_action":
            choice = str(parameters["choice"])
            result = self.automation_service.handle(choice)
            return _automation_result(step, result)
        if action == "speak_response":
            from grandpa.voice.speech_output import SpeechOutputEngine

            SpeechOutputEngine().speak(str(parameters["text"]), interrupt=True)
            return StepResult("success", "Response spoken.", step.step_id)
        if action == "request_confirmation":
            if confirmed:
                return StepResult(
                    "success",
                    "Confirmation received.",
                    step.step_id,
                    {"verified": True},
                )
            return StepResult("confirmation_required", str(parameters["message"]), step.step_id)
        if action == "request_clarification":
            return StepResult("clarification_required", str(parameters["message"]), step.step_id, {"choices": parameters.get("choices", [])})
        if action == "browser_analyze_page":
            from grandpa.browser_intelligence import (
                analyze_page_structure,
                format_page_analysis_cli,
                read_current_browser_page,
            )

            page = read_current_browser_page()
            analysis = analyze_page_structure(page)
            status = "success" if page.title or page.domain else "failed"
            return StepResult(status, format_page_analysis_cli(analysis), step.step_id, analysis)

        if action == "browser_extract_content":
            from grandpa.browser_intelligence import (
                extract_section_content,
                format_extracted_content_cli,
                read_current_browser_page,
            )

            section = str(parameters.get("section") or "installation")
            page = read_current_browser_page()
            # Bounded readiness polling if page content is loading
            for _ in range(6):
                if page.headings or page.paragraphs or page.visible_text:
                    break
                time.sleep(0.4)
                page = read_current_browser_page()

            extracted = extract_section_content(page, target_section=section)
            step_status = "success" if extracted.status in ("success", "partial_success") else "failed"
            return StepResult(step_status, format_extracted_content_cli(extracted), step.step_id, extracted.to_dict())

        if action == "browser_verify_source":
            from grandpa.browser_intelligence import (
                format_verification_cli,
                read_current_browser_page,
                verify_source,
            )

            page = read_current_browser_page()
            url = str(parameters.get("url") or page.url)
            subject = str(parameters.get("subject") or page.title)
            verification = verify_source(url, subject=subject)
            step_status = "success" if (verification.url and (verification.is_official or verification.trust_score >= 0.6)) else "failed"
            return StepResult(step_status, format_verification_cli(verification), step.step_id, verification.to_dict())

        if action == "browser_summarize":
            from grandpa.browser_intelligence import (
                LocalPageSummarizer,
                heuristic_summarize,
                read_current_browser_page,
            )

            summary_type = str(parameters.get("type") or "short")
            page = read_current_browser_page()

            # Check if previous step extracted section content
            extracted_text = ""
            if hasattr(self, "previous_step_results") and self.previous_step_results:
                for prev in reversed(self.previous_step_results):
                    if prev.step_id and "extract" in prev.step_id and prev.output:
                        extracted_text = prev.output
                        break

            if extracted_text and len(extracted_text.split()) > 5:
                summary = heuristic_summarize(extracted_text, summary_type=summary_type)  # type: ignore[arg-type]
            else:
                summarizer = LocalPageSummarizer()
                summary = summarizer.summarize_page(page, summary_type=summary_type)  # type: ignore[arg-type]

            step_status = "failed" if ("no active browser page" in summary.lower() or "insufficient page content" in summary.lower()) else "success"
            return StepResult(step_status, summary, step.step_id, {"summary": summary, "type": summary_type})

        if action == "browser_compare":
            from grandpa.browser_intelligence import (
                ProductComparisonEngine,
                format_comparison_cli,
            )

            item_a = str(parameters["item_a"])
            item_b = str(parameters["item_b"])
            engine = ProductComparisonEngine()
            comparison = engine.compare_items(item_a, item_b)
            return StepResult("success", format_comparison_cli(comparison), step.step_id, comparison.to_dict())

        if action == "browser_research":
            from grandpa.browser_intelligence import (
                WebResearchEngine,
                format_research_report_cli,
            )

            topic = str(parameters["topic"])
            research_engine = WebResearchEngine()
            report = research_engine.research_topic(topic)
            return StepResult("success", format_research_report_cli(report), step.step_id, report.to_dict())

        if action == "browser_navigate_smart":
            from grandpa.browser_intelligence import (
                SmartNavigator,
                read_current_browser_page,
            )

            target = str(parameters["target"])
            nav = SmartNavigator()
            nav_result = nav.smart_navigate(target)

            # Poll for page content readiness after navigation
            for _ in range(6):
                page = read_current_browser_page()
                if page.headings or page.paragraphs or page.visible_text:
                    break
                time.sleep(0.4)

            step_status = "success" if nav_result.get("status") in ("handled", "success") else "failed"
            return StepResult(step_status, nav_result.get("message", "Navigated."), step.step_id, nav_result)
        return StepResult("blocked", f"Unsupported planner action: {action}", step.step_id)

    @property
    def vision_engine(self) -> Any:
        if self._vision_engine is None:
            from grandpa.vision import VisionEngine

            self._vision_engine = VisionEngine()
        return self._vision_engine

    def _pipeline(self, step: PlanStep, command: str, *, confirmed: bool = False) -> StepResult:
        before = (
            self._vision_signature()
            if step.verification.strategy in {"screen_changed", "target_state_changed"}
            else None
        )
        result = self.pipeline.handle(command)
        if confirmed and result.status == "confirmation_required" and result.confirmation_token:
            automation = self.automation_service.confirm(result.confirmation_token)
            converted = _automation_result(step, automation)
        else:
            converted = StepResult(
                result.status,
                result.message,
                step.step_id,
                dict(result.data),
                result.confirmation_token,
            )
        if converted.status == "success" and before is not None:
            after = self._vision_signature()
            converted = StepResult(
                converted.status,
                converted.message,
                converted.step_id,
                {**converted.data, "state_changed": bool(after and after != before)},
                converted.confirmation_token,
            )
        return converted

    def _browser(self, step: PlanStep, command: str) -> StepResult:
        if self._browser_handler is None:
            from grandpa.browser import handle_browser_command

            self._browser_handler = handle_browser_command
        return _generic_result(step, self._browser_handler(command))

    def _find(self, step: PlanStep, *, wait: bool) -> StepResult:
        timeout = min(float(step.parameters.get("timeout_seconds", step.timeout_seconds)), step.timeout_seconds)
        deadline = time.monotonic() + timeout
        while True:
            result = self.vision_engine.find(
                str(step.parameters["name"]),
                actionable=bool(step.parameters.get("actionable", False)),
            )
            if result.matches:
                match = result.matches[0]
                return StepResult(
                    "success",
                    result.message,
                    step.step_id,
                    {
                        "verified": True,
                        "target": match.node.label,
                        "confidence": match.confidence,
                        "source": match.node.source,
                    },
                )
            if not wait or time.monotonic() >= deadline:
                return StepResult("failed", result.message, step.step_id)
            time.sleep(0.1)

    def _wait_for_window(self, step: PlanStep) -> StepResult:
        timeout = min(float(step.parameters.get("timeout_seconds", step.timeout_seconds)), step.timeout_seconds)
        app = str(step.parameters["app"])
        return self._wait_for_application_target(step, app, timeout=timeout)

    def _focus_application(self, step: PlanStep, app: str) -> StepResult:
        target = self.automation_service.target_window
        if target is None or not _window_matches(target, app):
            return self._pipeline(step, f"focus {app}")
        verification = self.automation_service.window_targets.focus_and_verify(target)
        if not verification.ok:
            return StepResult("target_lost", verification.message, step.step_id)
        self.automation_service.pin_target(verification.expected or target)
        return StepResult(
            "success",
            f"Focused the pinned {app.title()} target.",
            step.step_id,
            {"target_ready": True},
        )

    def _calculator_expression(self, step: PlanStep, expression: str) -> StepResult:
        control_ids = _calculator_control_ids(expression)
        if control_ids is None:
            return self._pipeline(step, f"type {expression}")
        return self._calculator_controls(
            step,
            control_ids,
            success_message="Calculator expression was entered.",
        )

    def _calculator_controls(
        self,
        step: PlanStep,
        control_ids: tuple[str, ...],
        *,
        success_message: str,
    ) -> StepResult:
        target = self.automation_service.target_window
        if target is None or not _window_matches(target, "calculator"):
            return StepResult(
                "target_lost",
                "The pinned Calculator window is unavailable. No input was sent.",
                step.step_id,
            )
        verification = self.automation_service.window_targets.focus_and_verify(target)
        if not verification.ok:
            return StepResult("target_lost", verification.message, step.step_id)
        available = getattr(
            self.automation_service.window_targets, "controls_available", None
        )
        if callable(available):
            deadline = time.monotonic() + min(step.timeout_seconds, 6.0)
            while time.monotonic() < deadline and not available(target, control_ids):
                time.sleep(0.1)
            if not available(target, control_ids):
                return StepResult(
                    "target_lost",
                    "Calculator opened, but its controls were not ready in time.",
                    step.step_id,
                )
        invoke = getattr(
            self.automation_service.window_targets, "invoke_controls", None
        )
        if not callable(invoke) or not invoke(target, control_ids):
            return StepResult(
                "failed",
                "Calculator controls could not be invoked safely.",
                step.step_id,
            )
        return StepResult(
            "success",
            success_message,
            step.step_id,
            {"calculator_controls_invoked": len(control_ids)},
        )

    def _launch_application(self, step: PlanStep, command: str) -> StepResult:
        app = str(step.parameters["app"])
        prelaunch = self._window_candidates(app)
        ready_existing = tuple(item for item in prelaunch if self._window_ready(item))
        if not step.parameters.get("new_instance") and ready_existing:
            if len(ready_existing) == 1:
                selected = ready_existing[0]
                self.automation_service.pin_target(selected)
                return StepResult(
                    "success",
                    f"{app.title()} is already open and ready.",
                    step.step_id,
                    {
                        "verified": True,
                        "target_ready": True,
                        "candidate_windows": [selected.title],
                        "reused_existing": True,
                    },
                )
            ambiguity = self.automation_service.handle(f"focus {app}")
            converted = _automation_result(step, ambiguity)
            if converted.status == "clarification_required":
                return converted
            return StepResult(
                "clarification_required",
                _window_choice_message(app, ready_existing),
                step.step_id,
                {"choices": [item.title for item in ready_existing]},
            )
        if app in self._launched_apps:
            return self._wait_for_application_target(
                step,
                app,
                timeout=_application_timeout(app, step.timeout_seconds),
                prelaunch=prelaunch,
            )
        launch = self._pipeline(step, command)
        if launch.status not in {"success", "partial_success"}:
            return launch
        self._launched_apps.add(app)
        pinned = self.automation_service.target_window
        if pinned is not None and self._window_ready(pinned):
            return StepResult(
                "success",
                f"{app.title()} is open and ready.",
                step.step_id,
                {
                    **launch.data,
                    "verified": True,
                    "target_ready": True,
                    "candidate_windows": [pinned.title],
                    "reused_existing": pinned.handle in {item.handle for item in prelaunch},
                },
            )
        return self._wait_for_application_target(
            step,
            app,
            timeout=_application_timeout(app, step.timeout_seconds),
            prelaunch=prelaunch,
            require_new=bool(step.parameters.get("new_instance")),
            launch_data=launch.data,
        )

    def _wait_for_application_target(
        self,
        step: PlanStep,
        app: str,
        *,
        timeout: float,
        prelaunch: tuple[WindowIdentity, ...] = (),
        require_new: bool = False,
        launch_data: dict[str, Any] | None = None,
    ) -> StepResult:
        deadline = time.monotonic() + max(0.1, timeout)
        previous_handles = {item.handle for item in prelaunch}
        previous_identities = {
            (item.handle, item.document_id) for item in prelaunch
        }
        last_candidates: tuple[WindowIdentity, ...] = ()
        while time.monotonic() < deadline:
            candidates = tuple(
                item
                for item in self._window_candidates(app)
                if self._window_ready(item)
            )
            if require_new and candidates:
                new_candidates = tuple(
                    item
                    for item in candidates
                    if (item.handle, item.document_id) not in previous_identities
                )
                if new_candidates:
                    candidates = new_candidates
            last_candidates = candidates or last_candidates
            if len(candidates) == 1:
                selected = candidates[0]
                self.automation_service.pin_target(selected)
                return StepResult(
                    "success",
                    f"{app.title()} is open and ready.",
                    step.step_id,
                    {
                        **(launch_data or {}),
                        "verified": True,
                        "target_ready": True,
                        "candidate_windows": [selected.title],
                        "reused_existing": selected.handle in previous_handles,
                    },
                )
            time.sleep(0.1)
        if len(last_candidates) > 1:
            ambiguity = self.automation_service.handle(f"focus {app}")
            converted = _automation_result(step, ambiguity)
            if converted.status == "clarification_required":
                return converted
            return StepResult(
                "clarification_required",
                _window_choice_message(app, last_candidates),
                step.step_id,
                {"choices": [item.title for item in last_candidates]},
            )
        return StepResult(
            "target_lost",
            f"{app.title()} launched, but its usable window was not ready before the timeout.",
            step.step_id,
            {
                **(launch_data or {}),
                "verified": False,
                "target_ready": False,
                "candidate_windows": [item.title for item in last_candidates],
            },
        )

    def _window_candidates(self, app: str) -> tuple[WindowIdentity, ...]:
        controller = self.automation_service.window_targets
        candidates = getattr(controller, "candidates", None)
        if callable(candidates):
            try:
                return tuple(candidates(app))
            except Exception:
                return ()
        try:
            window = controller.resolve(app)
        except WindowTargetResolutionError as exc:
            return exc.candidates
        except Exception:
            return ()
        return (window,) if window is not None else ()

    def _window_ready(self, window: WindowIdentity) -> bool:
        check = getattr(self.automation_service.window_targets, "is_ready", None)
        return bool(check(window)) if callable(check) else True

    def _record(
        self,
        step: PlanStep,
        result: StepResult,
        *,
        error: str = "",
    ) -> None:
        self.diagnostics.append(
            {
                "step_id": step.step_id,
                "action": step.action,
                "parameters": dict(step.parameters),
                "dependencies": [item.step_id for item in step.dependencies],
                "verification": step.verification.strategy,
                "status": result.status,
                "message": result.message,
                "candidate_windows": list(result.data.get("candidate_windows", [])),
                "target_ready": result.data.get("target_ready"),
                "error": error,
            }
        )

    def _vision_signature(self) -> tuple[tuple[str, str, int, int], ...] | None:
        try:
            graph = self.vision_engine.inspect().graph
            if graph is None:
                return None
            return tuple(
                sorted(
                    (
                        node.type,
                        node.label.casefold()[:120],
                        node.bounds.left,
                        node.bounds.top,
                    )
                    for node in graph.nodes
                    if node.visible and node.label
                )
            )
        except Exception:
            return None


def _automation_result(step: PlanStep, result: Any) -> StepResult:
    status = {
        "handled": "success",
        "needs_confirmation": "confirmation_required",
        "dialog_pending": "success",
        "not_found": "failed",
        "ambiguous": "clarification_required",
        "error": "failed",
        "cancelled": "success"
        if str(step.parameters.get("choice") or "").casefold() == "cancel"
        else "cancelled",
    }.get(str(result.status), str(result.status))
    return StepResult(status, str(result.message), step.step_id, dict(getattr(result, "data", {}) or {}), getattr(result, "confirmation_token", None))


def _application_timeout(app: str, requested: float) -> float:
    minimum = 10.0 if app in {"calculator", "settings", "chrome", "edge"} else 6.0
    return max(minimum, min(float(requested), 20.0))


def _window_matches(window: WindowIdentity, app: str) -> bool:
    values = " ".join(
        (window.target, window.title, window.process_name)
    ).casefold()
    aliases = {
        "calculator": ("calculator", "calculatorapp.exe"),
        "notepad": ("notepad", "notepad.exe"),
        "chrome": ("chrome", "chrome.exe"),
        "edge": ("edge", "msedge.exe"),
    }.get(app.casefold(), (app.casefold(),))
    return any(alias in values for alias in aliases)


def _calculator_control_ids(expression: str) -> tuple[str, ...] | None:
    mapping = {
        **{str(number): f"num{number}Button" for number in range(10)},
        "+": "plusButton",
        "-": "minusButton",
        "*": "multiplyButton",
        "/": "divideButton",
        ".": "decimalSeparatorButton",
    }
    try:
        return tuple(mapping[character] for character in expression)
    except KeyError:
        return None


def _window_choice_message(
    app: str, candidates: tuple[WindowIdentity, ...]
) -> str:
    choices = "\n".join(
        f"{index}. {item.title}" for index, item in enumerate(candidates[:5], 1)
    )
    return f"I found multiple {app.title()} windows. Choose one:\n{choices}"


def _step_confirmation_message(step: PlanStep) -> str:
    if step.action == "invoke_verified_dialog_action":
        choice = str(step.parameters.get("choice") or "").casefold()
        if choice == "discard":
            return (
                "Notepad has unsaved changes. The plan requests Don't Save. "
                "Do you want me to discard this document?"
            )
        if choice == "save":
            return "Notepad has unsaved changes. Do you want me to save this document?"
    return f"This step needs confirmation: {step.description}"


def _generic_result(step: PlanStep, result: Any) -> StepResult:
    status = {"handled": "success", "found": "success", "no_match": "unsupported", "needs_confirmation": "confirmation_required", "ambiguous": "clarification_required", "error": "failed"}.get(str(getattr(result, "status", "failed")), str(getattr(result, "status", "failed")))
    return StepResult(
        status,
        str(getattr(result, "message", "")),
        step.step_id,
        {
            "verified": status == "success",
            "url": str(getattr(result, "url", "") or ""),
        },
    )


def _vision_result(step: PlanStep, result: Any) -> StepResult:
    status = "success" if result.status == "handled" else "failed"
    return StepResult(status, result.message, step.step_id, {"verified": status == "success", **dict(result.data)})


__all__ = ["PlannerStepExecutor"]
