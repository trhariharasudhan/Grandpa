"""Default runtime skill registration."""

from __future__ import annotations

from typing import Any

from grandpa.skills.registry.core import register_skill
from grandpa.skills.runtime import (
    RuntimeSkill,
    SkillExecutionContext,
    SkillParameter,
    SkillResult,
)

_REGISTERED = False


def _pc_action(action_type: str, target: str = ""):
    def _execute(params: dict[str, Any], context: SkillExecutionContext) -> SkillResult:
        from grandpa.pc_control import run_local_action

        payload = {
            "action_type": params.get("action_type", action_type),
            "target": params.get("target", params.get("text", target)),
            "args": params.get("args", {}),
            "dry_run": bool(params.get("dry_run", context.dry_run)),
        }
        response = run_local_action(payload)
        return SkillResult(
            ok=response.ok,
            status="dry_run" if response.status == "dry_run" else "completed" if response.ok else response.status,
            message=response.message,
            data={"evidence": response.evidence, "action_id": response.action_id},
            risk_level=response.risk_level,
            approval_required=response.approval_required,
            error=response.error,
        )

    return _execute


def _browser_diagnostics(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.browser_control import execute_browser_action

    result = execute_browser_action("diagnostics", "browser")
    return SkillResult(
        ok=result.status in {"handled", "ready"},
        status="completed" if result.status in {"handled", "ready"} else "unsupported",
        message=result.message,
        data={"details": result.target, "context": result.context.to_dict() if result.context else {}},
        risk_level=getattr(result, "risk_level", "LOW"),
        approval_required=bool(getattr(result, "approval_required", False)),
    )


def _visual_diagnostics(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    try:
        from grandpa.visual_targeting import visual_diagnostics
    except ModuleNotFoundError:
        try:
            from grandpa.vision.visual_targeting import visual_diagnostics
        except ModuleNotFoundError:
            return SkillResult(
                ok=False,
                status="unsupported",
                message="Visual targeting diagnostics are unavailable in this environment.",
                data={"local_only": True, "opencv_available": False},
                risk_level="LOW",
            )

    info = visual_diagnostics()
    message = (
        "Visual targeting diagnostics:\n"
        f"- OpenCV: {'ready' if info.get('opencv_available') else 'not installed'}\n"
        f"- Pillow: {'ready' if info.get('pillow_available') else 'not installed'}\n"
        f"- Tesseract: {'ready' if info.get('tesseract_available') else 'not installed'}\n"
        f"- PyAutoGUI: {'ready' if info.get('pyautogui_available') else 'not installed'}\n"
        f"- Confidence threshold: {info.get('confidence_threshold')}\n"
        "- Local only: yes"
    )
    return SkillResult(
        ok=True,
        status="completed",
        message=message,
        data=info,
        risk_level="LOW",
    )


def _screen_diagnostics(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.screen_awareness import screen_diagnostics

    info = screen_diagnostics()
    screenshot = info.get("screenshot", {})
    ocr = info.get("ocr", {})
    active = info.get("active_window", {})
    message = (
        "Screen awareness diagnostics:\n"
        f"- Platform: {info.get('platform')}\n"
        f"- Active window: {'ready' if active.get('supported') else 'unavailable'}\n"
        f"- Screenshot backends: {', '.join(screenshot.get('backends') or []) or 'none'}\n"
        f"- OCR backend: {ocr.get('backend') or 'unavailable'}\n"
        f"- Visible windows: {info.get('visible_window_count', 0)}\n"
        "- Local only: yes"
    )
    return SkillResult(
        ok=bool(info.get("supported", True)),
        status="completed" if info.get("supported", True) else "unsupported",
        message=message if info.get("supported", True) else "Screen awareness is unavailable.",
        data=info,
        risk_level="LOW",
    )


def _workflow_status(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.autonomous_workflows import workflow_diagnostics

    info = workflow_diagnostics()
    return SkillResult(
        ok=True,
        status="completed",
        message="Workflow runtime diagnostics are ready.",
        data=info,
        risk_level="LOW",
    )


def _memory_recall(params: dict[str, Any], context: SkillExecutionContext) -> SkillResult:
    from grandpa.memory_context import search_personal_memory

    query = str(params.get("query") or context.user_request or "").strip()
    if not query:
        return SkillResult(ok=False, status="failed", message="Memory recall needs a query.", risk_level="LOW")
    info = search_personal_memory(query)
    memories = info.get("results", [])
    if not memories:
        return SkillResult(
            ok=True,
            status="completed",
            message="I do not have a confident memory for that yet.",
            data=info,
            risk_level="LOW",
        )
    return SkillResult(
        ok=True,
        status="completed",
        message=str(memories[0].get("text") or "Memory recall found a related note."),
        data=info,
        risk_level="LOW",
    )


def ensure_default_skills_registered() -> None:
    """Register built-in runtime skills once."""
    global _REGISTERED
    if _REGISTERED:
        try:
            from grandpa.skills.registry.core import get_skill

            get_skill("desktop.summary")
            return
        except KeyError:
            _REGISTERED = False
    skills = [
        RuntimeSkill(
            name="desktop.summary",
            description="Summarize monitors, active process, clipboard status, and PC control readiness.",
            category="desktop",
            risk_level="LOW",
            approval_required=False,
            executor=_pc_action("desktop_summary", "desktop"),
            aliases=("desktop summary", "summarize desktop"),
        ),
        RuntimeSkill(
            name="desktop.monitors",
            description="List detected monitors without controlling the desktop.",
            category="desktop",
            risk_level="LOW",
            approval_required=False,
            executor=_pc_action("list_monitors", "monitors"),
            aliases=("list monitors", "show monitors", "detect monitors"),
        ),
        RuntimeSkill(
            name="desktop.diagnostics",
            description="Report PC control backend readiness.",
            category="desktop",
            risk_level="LOW",
            approval_required=False,
            executor=_pc_action("pc_diagnostics", "diagnostics"),
            aliases=("pc control diagnostics", "show pc diagnostics"),
        ),
        RuntimeSkill(
            name="browser.diagnostics",
            description="Report visible-browser adapter and extension readiness.",
            category="browser",
            risk_level="LOW",
            approval_required=False,
            executor=_browser_diagnostics,
            aliases=("browser diagnostics", "show browser diagnostics", "browser status"),
        ),
        RuntimeSkill(
            name="vision.visual_diagnostics",
            description="Report OpenCV, OCR, and visual targeting readiness.",
            category="vision",
            risk_level="LOW",
            approval_required=False,
            executor=_visual_diagnostics,
            aliases=("visual targeting diagnostics", "show visual diagnostics", "visual automation diagnostics"),
        ),
        RuntimeSkill(
            name="vision.screen_diagnostics",
            description="Report screenshot, OCR, and active-window readiness.",
            category="vision",
            risk_level="LOW",
            approval_required=False,
            executor=_screen_diagnostics,
            aliases=("screen diagnostics", "show screen diagnostics", "screen awareness diagnostics"),
        ),
        RuntimeSkill(
            name="automation.workflow_status",
            description="Report autonomous workflow runtime and worker readiness.",
            category="automation",
            risk_level="LOW",
            approval_required=False,
            executor=_workflow_status,
            aliases=("workflow status", "workflow diagnostics", "show workflow status"),
        ),
        RuntimeSkill(
            name="memory.recall",
            description="Search Grandpa's local memory for a user query.",
            category="memory",
            risk_level="LOW",
            approval_required=False,
            parameters=(SkillParameter("query", "Memory query", required=True),),
            executor=_memory_recall,
            aliases=("memory recall", "search memory"),
        ),
        RuntimeSkill(
            name="desktop.keyboard_type",
            description="Type text into the active app through the approval-gated PC control layer.",
            category="desktop",
            risk_level="MEDIUM",
            approval_required=True,
            parameters=(SkillParameter("text", "Text to type", required=True),),
            dry_run_supported=True,
            executor=_pc_action("keyboard_type"),
            aliases=("type text",),
        ),
    ]
    for skill in skills:
        register_skill(skill)
    _REGISTERED = True


__all__ = ["ensure_default_skills_registered"]
