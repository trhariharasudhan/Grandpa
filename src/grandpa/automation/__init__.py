"""Safe visible-screen automation built on Grandpa's existing services."""

from grandpa.automation.models import (
    AutomationAction,
    AutomationResult,
    BoundingBox,
    LocatedElement,
    Point,
)
from grandpa.automation.pipeline import (
    CommandExecutionResult,
    WindowsCommandPipeline,
)
from grandpa.automation.planner import AutomationPlanner
from grandpa.automation.service import (
    ScreenAutomationService,
    get_automation_service,
    handle_automation_command,
)

__all__ = [
    "AutomationAction",
    "AutomationPlanner",
    "AutomationResult",
    "BoundingBox",
    "CommandExecutionResult",
    "LocatedElement",
    "Point",
    "ScreenAutomationService",
    "WindowsCommandPipeline",
    "get_automation_service",
    "handle_automation_command",
]
