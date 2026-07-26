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


def _browser_agent_result(payload: dict[str, Any], *, default_status: str = "completed") -> SkillResult:
    status = str(payload.get("status") or default_status)
    approval = status == "requires_approval" or bool(payload.get("task", {}).get("approval_required")) if isinstance(payload.get("task"), dict) else False
    risk = str(payload.get("task", {}).get("risk_level") or ("MEDIUM" if approval else "LOW")) if isinstance(payload.get("task"), dict) else ("MEDIUM" if approval else "LOW")
    if status == "planned":
        normalized = "completed"
    elif status == "requires_approval":
        normalized = "approval_required"
    elif status in {"blocked", "unsupported", "failed"}:
        normalized = status
    else:
        normalized = "completed"
    return SkillResult(
        ok=normalized in {"completed", "approval_required"},
        status=normalized,
        message=str(payload.get("message") or payload.get("summary") or "Browser agent completed."),
        data=payload,
        risk_level=risk if risk in {"LOW", "MEDIUM", "HIGH", "BLOCKED"} else "LOW",
        approval_required=approval,
    )


def _browser_page_summary(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.browser.agent import summarize_current_page

    return _browser_agent_result(summarize_current_page())


def _browser_visible_links(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.browser.agent import extract_visible_links

    return _browser_agent_result(extract_visible_links())


def _browser_visible_buttons(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.browser.agent import extract_visible_buttons

    return _browser_agent_result(extract_visible_buttons())


def _browser_search_plan(params: dict[str, Any], context: SkillExecutionContext) -> SkillResult:
    from grandpa.browser.agent import search_web_plan

    query = str(params.get("query") or context.user_request or "").strip()
    return _browser_agent_result(search_web_plan(query), default_status="planned")


def _browser_form_fill_plan(params: dict[str, Any], context: SkillExecutionContext) -> SkillResult:
    from grandpa.browser.agent import fill_form_plan

    field = str(params.get("field") or params.get("target") or context.user_request or "").strip()
    value = str(params.get("value") or "").strip()
    return _browser_agent_result(fill_form_plan(field, value), default_status="requires_approval")


def _browser_download_plan(params: dict[str, Any], context: SkillExecutionContext) -> SkillResult:
    from grandpa.browser.agent import download_plan

    target = str(params.get("target") or context.user_request or "this file").strip()
    return _browser_agent_result(download_plan(target), default_status="requires_approval")


def _browser_agent_diagnostics(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.browser.agent import browser_agent_diagnostics

    info = browser_agent_diagnostics()
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Browser agent is ready with {info.get('task_count', 0)} tracked task(s).",
        data=info,
        risk_level="LOW",
    )


def _desktop_operator_diagnostics(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.desktop.operator import operator_diagnostics

    info = operator_diagnostics()
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Desktop operator is ready with {info.get('profile_count', 0)} app profile(s).",
        data=info,
        risk_level="LOW",
    )


def _desktop_operator_plan(params: dict[str, Any], context: SkillExecutionContext) -> SkillResult:
    from grandpa.desktop.operator import build_ui_navigation_plan

    request = str(params.get("request") or params.get("goal") or context.user_request or "").strip()
    info = build_ui_navigation_plan(request, persist=not bool(params.get("dry_run", False)))
    task = info.get("task", {})
    status = "approval_required" if task.get("status") == "waiting_approval" else "completed" if task.get("status") in {"planned", "completed"} else "blocked"
    risk = str(info.get("analysis", {}).get("risk_level") or "LOW")
    return SkillResult(
        ok=status in {"completed", "approval_required"},
        status=status,
        message=str(task.get("result_summary") or "Desktop operator plan prepared."),
        data=info,
        risk_level=risk if risk in {"LOW", "MEDIUM", "HIGH", "BLOCKED"} else "LOW",
        approval_required=status == "approval_required",
    )


def _desktop_active_app_actions(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.desktop.operator import active_app_actions

    info = active_app_actions()
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Active app actions: {', '.join(info.get('suggested_actions', [])[:5]) or 'none'}.",
        data=info,
        risk_level="LOW",
    )


def _desktop_app_profiles(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.desktop.operator import list_app_profiles

    info = list_app_profiles()
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Loaded {info.get('count', 0)} desktop operator app profile(s).",
        data=info,
        risk_level="LOW",
    )


def _desktop_operator_history(params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.desktop.operator import list_operator_tasks

    info = list_operator_tasks(limit=int(params.get("limit", 20)))
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Loaded {len(info.get('tasks', []))} desktop operator task(s).",
        data=info,
        risk_level="LOW",
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
    from grandpa.smart_automation import diagnostics

    info = diagnostics()
    return SkillResult(
        ok=True,
        status="completed",
        message="Workflow runtime diagnostics are ready.",
        data=info,
        risk_level="LOW",
    )


def _clipboard_history(params: dict[str, Any], context: SkillExecutionContext) -> SkillResult:
    from grandpa.pc_control import run_local_action

    limit = int(params.get("limit", 20))
    response = run_local_action({"action_type": "clipboard_history", "target": "clipboard", "args": {"limit": limit}})
    return SkillResult(
        ok=response.ok,
        status="completed" if response.ok else response.status if response.status in {"unsupported", "blocked"} else "failed",
        message=response.message,
        data={"evidence": response.evidence, "action_id": response.action_id},
        risk_level=response.risk_level,
        approval_required=response.approval_required,
        error=response.error,
    )


def _planner_diagnostics(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.planner import planner_diagnostics

    info = planner_diagnostics()
    return SkillResult(
        ok=True,
        status="completed",
        message="Planner diagnostics are ready.",
        data=info,
        risk_level="LOW",
    )


def _skills_diagnostics(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.skills.registry.core import registry_diagnostics

    info = registry_diagnostics()
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Skill runtime is ready with {info.get('skill_count', 0)} loaded skills.",
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


def _memory_profile(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.memory_context import memory_profile

    info = memory_profile()
    return SkillResult(
        ok=True,
        status="completed",
        message=str(info.get("summary") or "Memory profile is ready."),
        data=info,
        risk_level="LOW",
    )


def _memory_preferences(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.memory_context import memory_preferences

    info = memory_preferences()
    count = int(info.get("count", 0))
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Grandpa found {count} learned preference{'s' if count != 1 else ''}.",
        data=info,
        risk_level="LOW",
    )


def _memory_relationships(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.memory_context import memory_relationships

    info = memory_relationships()
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Memory relationship graph has {len(info.get('nodes', []))} node(s).",
        data=info,
        risk_level="LOW",
    )


def _memory_insights(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.memory_context import memory_insight_summary

    info = memory_insight_summary()
    return SkillResult(
        ok=True,
        status="completed",
        message=str(info.get("profile", {}).get("summary") or "Memory insights are ready."),
        data=info,
        risk_level="LOW",
    )


def _memory_topic_summary(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.memory_context import memory_topics

    info = memory_topics()
    topics = info.get("topics", [])
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Grandpa grouped memory into {len(topics)} topic cluster(s).",
        data=info,
        risk_level="LOW",
    )


def _knowledge_search(params: dict[str, Any], context: SkillExecutionContext) -> SkillResult:
    from grandpa.knowledge.engine import search_knowledge

    query = str(params.get("query") or context.user_request or "").strip()
    tag = str(params.get("tag") or "").strip()
    info = search_knowledge(query, tag=tag, limit=int(params.get("limit", 10)))
    count = len(info.get("results", []))
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Found {count} local knowledge document match{'es' if count != 1 else ''}.",
        data=info,
        risk_level="LOW",
    )


def _knowledge_summary(params: dict[str, Any], context: SkillExecutionContext) -> SkillResult:
    from grandpa.knowledge.engine import KnowledgeEngine

    engine = KnowledgeEngine()
    document_id = str(params.get("document_id") or "").strip()
    topic = str(params.get("topic") or context.user_request or "").strip()
    try:
        info = engine.summary(document_id=document_id, topic=topic, project=bool(params.get("project", False)))
    except KeyError:
        return SkillResult(ok=False, status="failed", message="Knowledge document was not found.", risk_level="LOW")
    return SkillResult(
        ok=True,
        status="completed",
        message=str(info.get("summary") or "Knowledge summary is ready."),
        data=info,
        risk_level="LOW",
    )


def _knowledge_recent(params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.knowledge.engine import recent_knowledge_documents

    info = recent_knowledge_documents(limit=int(params.get("limit", 10)))
    count = len(info.get("documents", []))
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Grandpa has {count} recent knowledge document{'s' if count != 1 else ''}.",
        data=info,
        risk_level="LOW",
    )


def _knowledge_projects(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.knowledge.engine import KnowledgeEngine

    info = KnowledgeEngine().projects()
    return SkillResult(
        ok=True,
        status="completed",
        message=str(info.get("summary", {}).get("summary") or "Project knowledge summary is ready."),
        data=info,
        risk_level="LOW",
    )


def _knowledge_diagnostics(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.knowledge.engine import knowledge_diagnostics

    info = knowledge_diagnostics()
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Knowledge engine is ready with {info.get('document_count', 0)} indexed document(s).",
        data=info,
        risk_level="LOW",
    )


def _knowledge_semantic_search(params: dict[str, Any], context: SkillExecutionContext) -> SkillResult:
    from grandpa.knowledge.engine import semantic_search_knowledge

    query = str(params.get("query") or context.user_request or "").strip()
    info = semantic_search_knowledge(query, limit=int(params.get("limit", 10)))
    count = len(info.get("results", []))
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Semantic knowledge retrieval returned {count} chunk match{'es' if count != 1 else ''}.",
        data=info,
        risk_level="LOW",
    )


def _knowledge_related(params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.knowledge.engine import related_knowledge

    document_id = str(params.get("document_id") or "").strip()
    if not document_id:
        return SkillResult(ok=False, status="failed", message="Related knowledge needs a document_id.", risk_level="LOW")
    try:
        info = related_knowledge(document_id, limit=int(params.get("limit", 8)))
    except KeyError:
        return SkillResult(ok=False, status="failed", message="Knowledge document was not found.", risk_level="LOW")
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Found {len(info.get('results', []))} related knowledge document(s).",
        data=info,
        risk_level="LOW",
    )


def _knowledge_context(params: dict[str, Any], context: SkillExecutionContext) -> SkillResult:
    from grandpa.knowledge.engine import knowledge_context

    query = str(params.get("query") or context.user_request or "").strip()
    info = knowledge_context(query, limit=int(params.get("limit", 5)))
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Built knowledge context with {len(info.get('chunks', []))} chunk(s).",
        data=info,
        risk_level="LOW",
    )


def _knowledge_embedding_status(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.knowledge.engine import knowledge_embedding_status

    info = knowledge_embedding_status()
    mode = "semantic" if info.get("true_semantic_available") else "fallback"
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Knowledge embeddings are in {mode} mode with {info.get('embedding_count', 0)} stored chunk vector(s).",
        data=info,
        risk_level="LOW",
    )


def _coding_project_scan(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.coding.project_scanner import scan_projects

    data = scan_projects()
    return SkillResult(ok=True, status="completed", message=f"Detected {data['count']} local project(s).", data=data, risk_level="LOW")


def _coding_project_summary(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.coding.code_summary import summarize_project

    data = summarize_project()
    return SkillResult(ok=True, status="completed", message=data["summary"], data=data, risk_level="LOW")


def _coding_architecture(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.coding.architecture_analysis import analyze_architecture

    data = analyze_architecture()
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Detected {len(data['present_layers'])} architecture layer(s).",
        data=data,
        risk_level="LOW",
    )


def _coding_dependencies(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.coding.dependency_analysis import analyze_dependencies

    data = analyze_dependencies()
    return SkillResult(
        ok=True,
        status="completed",
        message=f"Found {data['dependency_count']} declared dependenc(ies) across {data['manifest_count']} manifest(s).",
        data=data,
        risk_level="LOW",
    )


def _coding_diagnostics(_params: dict[str, Any], _context: SkillExecutionContext) -> SkillResult:
    from grandpa.coding.diagnostics import coding_diagnostics

    data = coding_diagnostics()
    return SkillResult(ok=True, status="completed", message="Coding agent diagnostics are ready.", data=data, risk_level="LOW")


def ensure_default_skills_registered() -> None:
    """Register built-in runtime skills once."""
    global _REGISTERED
    if _REGISTERED:
        try:
            from grandpa.skills.registry.core import get_skill

            get_skill("desktop.summary")
            get_skill("browser.agent_diagnostics")
            get_skill("memory.insights")
            get_skill("knowledge.diagnostics")
            get_skill("coding.diagnostics")
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
            name="desktop.operator_diagnostics",
            description="Report Desktop Operator v2 profiles, task history, and visual safety readiness.",
            category="desktop",
            risk_level="LOW",
            approval_required=False,
            executor=_desktop_operator_diagnostics,
            aliases=("desktop operator diagnostics", "operator diagnostics", "desktop operator status"),
        ),
        RuntimeSkill(
            name="desktop.operator_plan",
            description="Create a safe desktop UI navigation plan without blind clicking.",
            category="desktop",
            risk_level="MEDIUM",
            approval_required=False,
            parameters=(SkillParameter("request", "Desktop task request", required=False),),
            executor=_desktop_operator_plan,
            aliases=("desktop operator plan", "ui navigation plan"),
        ),
        RuntimeSkill(
            name="desktop.active_app_actions",
            description="Detect the active app and suggest safe operator actions.",
            category="desktop",
            risk_level="LOW",
            approval_required=False,
            executor=_desktop_active_app_actions,
            aliases=("detect active app and suggest actions", "active app actions", "suggest active app actions"),
        ),
        RuntimeSkill(
            name="desktop.app_profiles",
            description="List deterministic desktop operator app profiles.",
            category="desktop",
            risk_level="LOW",
            approval_required=False,
            executor=_desktop_app_profiles,
            aliases=("desktop app profiles", "operator app profiles"),
        ),
        RuntimeSkill(
            name="desktop.operator_history",
            description="List recent desktop operator task history.",
            category="desktop",
            risk_level="LOW",
            approval_required=False,
            parameters=(SkillParameter("limit", "Maximum task rows", required=False, type="integer"),),
            executor=_desktop_operator_history,
            aliases=("desktop operator history", "operator task history"),
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
            name="browser.page_summary",
            description="Summarize the current visible browser page snapshot.",
            category="browser",
            risk_level="LOW",
            approval_required=False,
            executor=_browser_page_summary,
            aliases=("summarize this webpage", "summarize current page", "page summary"),
        ),
        RuntimeSkill(
            name="browser.visible_links",
            description="Extract visible links from the current page snapshot.",
            category="browser",
            risk_level="LOW",
            approval_required=False,
            executor=_browser_visible_links,
            aliases=("show links on this page", "visible links", "extract links"),
        ),
        RuntimeSkill(
            name="browser.visible_buttons",
            description="Extract visible buttons from the current page snapshot.",
            category="browser",
            risk_level="LOW",
            approval_required=False,
            executor=_browser_visible_buttons,
            aliases=("what buttons are visible", "visible buttons", "extract buttons"),
        ),
        RuntimeSkill(
            name="browser.search_plan",
            description="Create a safe browser search workflow plan.",
            category="browser",
            risk_level="LOW",
            approval_required=False,
            parameters=(SkillParameter("query", "Search query", required=False),),
            executor=_browser_search_plan,
            aliases=("search web plan", "browser search plan"),
        ),
        RuntimeSkill(
            name="browser.form_fill_plan",
            description="Plan a visible safe form fill without auto-submit.",
            category="browser",
            risk_level="MEDIUM",
            approval_required=False,
            parameters=(SkillParameter("field", "Field label", required=False), SkillParameter("value", "Value to enter", required=False)),
            executor=_browser_form_fill_plan,
            aliases=("form fill plan", "fill form plan"),
        ),
        RuntimeSkill(
            name="browser.download_plan",
            description="Plan a browser download with approval required.",
            category="browser",
            risk_level="MEDIUM",
            approval_required=False,
            parameters=(SkillParameter("target", "Visible file or link", required=False),),
            executor=_browser_download_plan,
            aliases=("download plan", "browser download plan"),
        ),
        RuntimeSkill(
            name="browser.agent_diagnostics",
            description="Report browser-agent planning and task-history readiness.",
            category="browser",
            risk_level="LOW",
            approval_required=False,
            executor=_browser_agent_diagnostics,
            aliases=("browser agent diagnostics", "browser agent status"),
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
            name="desktop.clipboard_history",
            description="Show metadata-only clipboard history without exposing clipboard contents.",
            category="desktop",
            risk_level="LOW",
            approval_required=False,
            parameters=(SkillParameter("limit", "Maximum history rows", required=False, type="integer"),),
            executor=_clipboard_history,
            aliases=("clipboard history", "show clipboard history"),
        ),
        RuntimeSkill(
            name="planner.diagnostics",
            description="Report native planner and workflow handoff readiness.",
            category="planner",
            risk_level="LOW",
            approval_required=False,
            executor=_planner_diagnostics,
            aliases=("planner diagnostics", "show planner diagnostics"),
        ),
        RuntimeSkill(
            name="skills.diagnostics",
            description="Report runtime skill registry readiness.",
            category="skills",
            risk_level="LOW",
            approval_required=False,
            executor=_skills_diagnostics,
            aliases=("skills diagnostics", "skill diagnostics"),
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
            name="memory.profile",
            description="Summarize Grandpa's local user memory profile.",
            category="memory",
            risk_level="LOW",
            approval_required=False,
            executor=_memory_profile,
            aliases=("memory profile", "what do you know about me"),
        ),
        RuntimeSkill(
            name="memory.preferences",
            description="Summarize learned local user preferences.",
            category="memory",
            risk_level="LOW",
            approval_required=False,
            executor=_memory_preferences,
            aliases=("memory preferences", "summarize my preferences"),
        ),
        RuntimeSkill(
            name="memory.relationships",
            description="Build a local relationship graph from remembered facts.",
            category="memory",
            risk_level="LOW",
            approval_required=False,
            executor=_memory_relationships,
            aliases=("memory relationships", "relationship graph"),
        ),
        RuntimeSkill(
            name="memory.insights",
            description="Report memory intelligence insights, topics, and recommendations.",
            category="memory",
            risk_level="LOW",
            approval_required=False,
            executor=_memory_insights,
            aliases=("memory insights", "memory intelligence"),
        ),
        RuntimeSkill(
            name="memory.topic_summary",
            description="Group local memories by topic cluster.",
            category="memory",
            risk_level="LOW",
            approval_required=False,
            executor=_memory_topic_summary,
            aliases=("memory topics", "topic summary"),
        ),
        RuntimeSkill(
            name="knowledge.search",
            description="Search local indexed knowledge with keyword, title, and tag retrieval.",
            category="knowledge",
            risk_level="LOW",
            approval_required=False,
            parameters=(
                SkillParameter("query", "Search query", required=False),
                SkillParameter("tag", "Optional tag filter", required=False),
            ),
            executor=_knowledge_search,
            aliases=("knowledge search", "search knowledge", "search project knowledge"),
        ),
        RuntimeSkill(
            name="knowledge.summary",
            description="Summarize a local knowledge document, topic, or project knowledge.",
            category="knowledge",
            risk_level="LOW",
            approval_required=False,
            parameters=(
                SkillParameter("document_id", "Knowledge document id", required=False),
                SkillParameter("topic", "Topic to summarize", required=False),
            ),
            executor=_knowledge_summary,
            aliases=("knowledge summary", "summarize knowledge", "project knowledge summary"),
        ),
        RuntimeSkill(
            name="knowledge.recent",
            description="List recent local knowledge documents.",
            category="knowledge",
            risk_level="LOW",
            approval_required=False,
            executor=_knowledge_recent,
            aliases=("recent knowledge", "recent documents", "knowledge recent"),
        ),
        RuntimeSkill(
            name="knowledge.projects",
            description="List and summarize project-tagged knowledge documents.",
            category="knowledge",
            risk_level="LOW",
            approval_required=False,
            executor=_knowledge_projects,
            aliases=("project documents", "project knowledge", "knowledge projects"),
        ),
        RuntimeSkill(
            name="knowledge.diagnostics",
            description="Report local knowledge engine readiness.",
            category="knowledge",
            risk_level="LOW",
            approval_required=False,
            executor=_knowledge_diagnostics,
            aliases=("knowledge diagnostics", "knowledge engine status"),
        ),
        RuntimeSkill(
            name="knowledge.semantic_search",
            description="Search local knowledge chunks using local embeddings when available.",
            category="knowledge",
            risk_level="LOW",
            approval_required=False,
            parameters=(SkillParameter("query", "Search query", required=False),),
            executor=_knowledge_semantic_search,
            aliases=("semantic knowledge search", "knowledge semantic search"),
        ),
        RuntimeSkill(
            name="knowledge.related",
            description="Find local knowledge documents related to a document id.",
            category="knowledge",
            risk_level="LOW",
            approval_required=False,
            parameters=(SkillParameter("document_id", "Knowledge document id", required=True),),
            executor=_knowledge_related,
            aliases=("related knowledge", "related documents"),
        ),
        RuntimeSkill(
            name="knowledge.context",
            description="Build a compact local knowledge context packet for planning and agents.",
            category="knowledge",
            risk_level="LOW",
            approval_required=False,
            parameters=(SkillParameter("query", "Knowledge context query", required=False),),
            executor=_knowledge_context,
            aliases=("knowledge context", "build knowledge context"),
        ),
        RuntimeSkill(
            name="knowledge.embedding_status",
            description="Report local knowledge embedding backend and coverage.",
            category="knowledge",
            risk_level="LOW",
            approval_required=False,
            executor=_knowledge_embedding_status,
            aliases=("knowledge embedding status", "embedding status"),
        ),
        RuntimeSkill(
            name="coding.project_scan",
            description="Detect local software projects without executing code.",
            category="coding",
            risk_level="LOW",
            approval_required=False,
            executor=_coding_project_scan,
            aliases=("coding project scan", "scan projects", "detect local projects"),
        ),
        RuntimeSkill(
            name="coding.project_summary",
            description="Summarize the current repository using read-only metrics.",
            category="coding",
            risk_level="LOW",
            approval_required=False,
            executor=_coding_project_summary,
            aliases=("coding project summary", "summarize repository", "summarize project"),
        ),
        RuntimeSkill(
            name="coding.architecture",
            description="Inspect folder and domain-layer architecture without modifying code.",
            category="coding",
            risk_level="LOW",
            approval_required=False,
            executor=_coding_architecture,
            aliases=("coding architecture", "analyze architecture", "repository architecture"),
        ),
        RuntimeSkill(
            name="coding.dependencies",
            description="Inspect dependency manifests without installing or executing packages.",
            category="coding",
            risk_level="LOW",
            approval_required=False,
            executor=_coding_dependencies,
            aliases=("coding dependencies", "dependency analysis", "analyze dependencies"),
        ),
        RuntimeSkill(
            name="coding.diagnostics",
            description="Report Coding Agent readiness and read-only safety status.",
            category="coding",
            risk_level="LOW",
            approval_required=False,
            executor=_coding_diagnostics,
            aliases=("coding diagnostics", "developer diagnostics", "project diagnostics"),
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
    try:
        from grandpa.skill_builder.execution import register_user_skills

        register_user_skills()
    except Exception:
        # User skill loading is optional and must never block built-in skills.
        pass
    _REGISTERED = True


__all__ = ["ensure_default_skills_registered"]
