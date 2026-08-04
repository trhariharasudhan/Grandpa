"""Strict allowlist and schemas for executive-plan actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from grandpa.planner.models import RiskLevel


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()
    risk: RiskLevel = RiskLevel.LOW
    verification_required: bool = False
    verification_strategies: frozenset[str] = frozenset({"execution_success"})
    confirmation_may_be_required: bool = False
    recovery_supported: bool = True
    vision_required: bool = False
    literal_text_parameters: frozenset[str] = frozenset()

    @property
    def parameters(self) -> frozenset[str]:
        return self.required | self.optional


def _action(
    name: str,
    *,
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
    risk: RiskLevel = RiskLevel.LOW,
    verify: tuple[str, ...] = ("execution_success",),
    mandatory: bool = False,
    confirm: bool = False,
    recovery: bool = True,
    vision: bool = False,
    literal: tuple[str, ...] = (),
) -> ActionDefinition:
    return ActionDefinition(
        name,
        frozenset(required),
        frozenset(optional),
        risk,
        mandatory,
        frozenset(verify),
        confirm,
        recovery,
        vision,
        frozenset(literal),
    )


ACTION_CATALOG: dict[str, ActionDefinition] = {
    "launch_application": _action(
        "launch_application",
        required=("app",),
        optional=("new_instance", "project_path"),
        verify=("application_window_exists",),
        mandatory=True,
    ),
    "focus_window": _action(
        "focus_window",
        required=("app",),
        verify=("application_window_focused",),
        mandatory=True,
    ),
    "close_window": _action(
        "close_window",
        required=("app",),
        risk=RiskLevel.MEDIUM,
        verify=("document_closed", "dialog_present"),
        mandatory=True,
        confirm=True,
        recovery=False,
    ),
    "open_new_application_instance": _action(
        "open_new_application_instance",
        required=("app",),
        verify=("application_window_exists",),
        mandatory=True,
    ),
    "type_text": _action(
        "type_text",
        required=("text",),
        optional=("window",),
        risk=RiskLevel.MEDIUM,
        verify=("typed_text_present", "focused_control_matches"),
        mandatory=True,
        confirm=True,
        recovery=False,
        literal=("text",),
    ),
    "press_key": _action(
        "press_key",
        required=("key",),
        optional=("window",),
        risk=RiskLevel.MEDIUM,
        verify=("target_state_changed", "execution_success"),
        mandatory=True,
        confirm=True,
        recovery=False,
    ),
    "press_hotkey": _action(
        "press_hotkey",
        required=("keys",),
        optional=("window",),
        risk=RiskLevel.MEDIUM,
        verify=("target_state_changed", "execution_success"),
        mandatory=True,
        confirm=True,
        recovery=False,
    ),
    "input_calculator_expression": _action(
        "input_calculator_expression",
        required=("expression",),
        risk=RiskLevel.MEDIUM,
        verify=("calculator_expression_visible",),
        mandatory=True,
        recovery=False,
        literal=("expression",),
    ),
    "invoke_calculator_equals": _action(
        "invoke_calculator_equals",
        required=("expected_result",),
        risk=RiskLevel.MEDIUM,
        verify=("calculator_result",),
        mandatory=True,
        recovery=False,
    ),
    "find_element": _action(
        "find_element",
        required=("name",),
        optional=("actionable",),
        verify=("element_visible",),
        vision=True,
    ),
    "click_element": _action(
        "click_element",
        required=("name",),
        optional=("window",),
        risk=RiskLevel.MEDIUM,
        verify=("target_state_changed", "element_not_visible", "text_visible"),
        mandatory=True,
        confirm=True,
        recovery=False,
        vision=True,
    ),
    "highlight_element": _action(
        "highlight_element",
        required=("name",),
        verify=("element_visible",),
        vision=True,
    ),
    "focus_element": _action(
        "focus_element",
        required=("name",),
        verify=("focused_control_matches",),
        mandatory=True,
        vision=True,
    ),
    "read_visible_text": _action(
        "read_visible_text", verify=("execution_success",), vision=True
    ),
    "describe_screen": _action(
        "describe_screen", verify=("execution_success",), vision=True
    ),
    "list_elements": _action(
        "list_elements", optional=("types",), verify=("execution_success",), vision=True
    ),
    "scroll": _action(
        "scroll",
        required=("direction",),
        optional=("amount", "window"),
        verify=("screen_changed", "execution_success"),
        mandatory=True,
    ),
    "scroll_until": _action(
        "scroll_until",
        required=("name",),
        optional=("direction", "max_attempts", "window"),
        verify=("element_visible",),
        mandatory=True,
        vision=True,
    ),
    "wait_for_window": _action(
        "wait_for_window",
        required=("app",),
        optional=("timeout_seconds",),
        verify=("application_window_exists",),
    ),
    "wait_for_element": _action(
        "wait_for_element",
        required=("name",),
        optional=("timeout_seconds",),
        verify=("element_visible",),
        vision=True,
    ),
    "navigate_url": _action(
        "navigate_url", required=("url",), verify=("URL_matches",), mandatory=True
    ),
    "browser_search": _action(
        "browser_search",
        required=("query",),
        optional=("provider",),
        verify=("browser_results_visible",),
        mandatory=True,
        literal=("query",),
    ),
    "open_file": _action(
        "open_file",
        required=("path",),
        verify=("application_window_exists",),
        mandatory=True,
    ),
    "open_folder": _action(
        "open_folder",
        required=("path",),
        verify=("application_window_exists",),
        mandatory=True,
    ),
    "save_document": _action(
        "save_document",
        optional=("path",),
        risk=RiskLevel.MEDIUM,
        verify=("file_saved",),
        mandatory=True,
        confirm=True,
        recovery=False,
    ),
    "invoke_verified_dialog_action": _action(
        "invoke_verified_dialog_action",
        required=("choice",),
        risk=RiskLevel.HIGH,
        verify=("dialog_absent", "document_closed", "document_open"),
        mandatory=True,
        confirm=True,
        recovery=False,
    ),
    "speak_response": _action(
        "speak_response", required=("text",), recovery=False, literal=("text",)
    ),
    "request_confirmation": _action(
        "request_confirmation",
        required=("message",),
        risk=RiskLevel.MEDIUM,
        confirm=True,
        recovery=False,
        literal=("message",),
    ),
    "request_clarification": _action(
        "request_clarification",
        required=("message",),
        optional=("choices",),
        recovery=False,
        literal=("message",),
    ),
    "browser_analyze_page": _action(
        "browser_analyze_page", verify=("execution_success",)
    ),
    "browser_extract_content": _action(
        "browser_extract_content",
        optional=("section", "topic"),
        verify=("execution_success",),
        literal=("section", "topic"),
    ),
    "browser_verify_source": _action(
        "browser_verify_source",
        optional=("url", "subject"),
        verify=("execution_success",),
    ),
    "browser_summarize": _action(
        "browser_summarize", optional=("type",), verify=("execution_success",)
    ),
    "browser_compare": _action(
        "browser_compare", required=("item_a", "item_b"), verify=("execution_success",)
    ),
    "browser_research": _action(
        "browser_research",
        required=("topic",),
        verify=("execution_success",),
        literal=("topic",),
    ),
    "browser_navigate_smart": _action(
        "browser_navigate_smart", required=("target",), verify=("execution_success",)
    ),
}

PROHIBITED_ACTION_NAMES = frozenset(
    {
        "shell",
        "powershell",
        "python",
        "execute_code",
        "run_command",
        "registry_write",
        "raw_click",
        "coordinate_click",
    }
)


def action_definition(name: str) -> ActionDefinition | None:
    return ACTION_CATALOG.get(str(name).strip())


def public_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "required_parameters": sorted(item.required),
            "optional_parameters": sorted(item.optional),
            "risk": item.risk.value,
            "verification_required": item.verification_required,
            "allowed_verification": sorted(item.verification_strategies),
        }
        for item in ACTION_CATALOG.values()
    ]


__all__ = [
    "ACTION_CATALOG",
    "PROHIBITED_ACTION_NAMES",
    "ActionDefinition",
    "action_definition",
    "public_catalog",
]
