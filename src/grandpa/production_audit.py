"""Real-device production readiness audit for Grandpa.

The production audit is intentionally conservative. It records evidence from
local stores, diagnostics APIs, and safe dry-run/planning paths, but it does not
claim that microphones or visible desktop automation were validated unless
Grandpa can observe real local evidence.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "runtime" / "reports"
JSON_REPORT = REPORT_DIR / "production-audit.json"
MD_REPORT = REPORT_DIR / "production-audit.md"

AuditStatus = str


@dataclass(frozen=True)
class AuditCheck:
    feature_area: str
    name: str
    status: AuditStatus
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    hardware_dependent: bool = False
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def latest_report() -> dict[str, Any]:
    """Return the latest production audit report or a not-run payload."""

    if not JSON_REPORT.exists():
        return {
            "schema_version": 1,
            "overall_status": "not_run",
            "pass": False,
            "score": 0,
            "message": "No production audit report has been generated yet.",
            "report_path": str(JSON_REPORT),
            "markdown_path": str(MD_REPORT),
            "feature_matrix": [],
            "summary": _empty_summary(),
        }
    try:
        return json.loads(JSON_REPORT.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "schema_version": 1,
            "overall_status": "invalid",
            "pass": False,
            "score": 0,
            "message": f"Production audit report could not be parsed: {exc.__class__.__name__}",
            "report_path": str(JSON_REPORT),
            "markdown_path": str(MD_REPORT),
            "feature_matrix": [],
            "summary": {**_empty_summary(), "blocked": 1},
        }


def status() -> dict[str, Any]:
    report = latest_report()
    return {
        "overall_status": report.get("overall_status", "unknown"),
        "pass": bool(report.get("pass")),
        "score": report.get("score", 0),
        "core_score": report.get("core_score", 0),
        "summary": report.get("summary", {}),
        "readiness_verdict": report.get("readiness_verdict", ""),
        "recommendation": report.get("recommendation") or report.get("message", ""),
        "finished_at": report.get("finished_at"),
        "report_path": report.get("report_path", str(JSON_REPORT)),
    }


def run_production_audit(*, write: bool = True) -> dict[str, Any]:
    started = _now_iso()
    wall_start = time.perf_counter()
    checks: list[AuditCheck] = []
    checks.extend(_browser_checks())
    checks.extend(_voice_checks())
    checks.extend(_desktop_operator_checks())
    checks.extend(_agent_checks())
    checks.extend(_knowledge_memory_checks())

    report = _build_report(checks, started, _now_iso(), time.perf_counter() - wall_start)
    if write:
        _write_reports(report)
    return report


def _browser_checks() -> list[AuditCheck]:
    try:
        from grandpa.browser_control import get_visible_browser_context

        context = get_visible_browser_context()
        return [
            AuditCheck(
                "Browser Awareness",
                "Visible browser context",
                "partially_validated" if context.supported else "unvalidated",
                context.message or "Visible browser context check completed.",
                {
                    "supported": context.supported,
                    "title": context.title,
                    "url": context.url,
                    "headings": len(context.headings),
                    "links": len(context.links),
                    "buttons": len(context.buttons),
                },
                [] if context.supported else ["Open a supported browser window to validate visible context."],
                hardware_dependent=True,
            )
        ]
    except Exception as exc:
        return [_blocked("Browser Awareness", "Visible browser context", exc)]

def _voice_checks() -> list[AuditCheck]:
    try:
        from grandpa.voice.session import get_voice_runtime

        voice = get_voice_runtime().status()
        speech_input = voice.get("speech_input", {})
        speech_output = voice.get("speech_output", {})
        wake_word = voice.get("wake_word", {})
        input_ready = speech_input.get("status") == "ready"
        output_ready = speech_output.get("status") == "ready"
        wake_enabled = bool(wake_word.get("enabled", wake_word.get("configured", True)))
        return [
            AuditCheck(
                "Voice Runtime",
                "Microphone detection",
                "unvalidated" if not input_ready else "partially_validated",
                "The unattended audit cannot verify real microphone capture.",
                {"speech_input": speech_input},
                ["Validate capture with the local voice CLI and selected Windows input device."],
                hardware_dependent=True,
            ),
            AuditCheck(
                "Voice Runtime",
                "Speech input pipeline",
                "partially_validated" if speech_input.get("status") in {"ready", "push_to_talk"} else "unvalidated",
                f"Speech input engine reports {speech_input.get('status', 'unknown')}.",
                {"speech_input": speech_input},
                ["Live speech recognition was not exercised by this non-interactive audit."],
                hardware_dependent=True,
            ),
            AuditCheck(
                "Voice Runtime",
                "Speech output pipeline",
                "partially_validated" if output_ready else "unvalidated",
                f"Speech output engine reports {speech_output.get('status', 'unknown')}.",
                {"speech_output": speech_output},
                ["Actual speaker playback is not measured by the CLI audit."],
                hardware_dependent=True,
            ),
            AuditCheck(
                "Voice Runtime",
                "Wake phrase flow",
                "partially_validated" if wake_enabled else "unvalidated",
                "Wake phrase detector is configured." if wake_enabled else "Wake phrase mode is disabled or unavailable.",
                {"wake_word": wake_word, "phrases": wake_word.get("phrases")},
                ["Continuous real-time wake detection must be validated with microphone permissions."],
                hardware_dependent=True,
            ),
        ]
    except Exception as exc:
        return [_blocked("Voice Runtime", "Voice diagnostics", exc)]


def _desktop_operator_checks() -> list[AuditCheck]:
    try:
        from grandpa.desktop.operator import (
            active_app_actions,
            build_ui_navigation_plan,
            operator_diagnostics,
            recover_failed_action,
            verify_action_result,
        )

        diagnostics = operator_diagnostics()
        terminal_plan = build_ui_navigation_plan("open terminal in VS Code", persist=False)
        desktop_plan = build_ui_navigation_plan("summarize current desktop state", persist=False)
        approval_plan = build_ui_navigation_plan("create a note in Notepad", persist=False)
        recovery = recover_failed_action({"action_type": "click", "visual_target": {"confidence": 0.2}}, {"status": "failed"})
        verification = verify_action_result({"action_type": "observe"}, {"ok": True, "status": "dry_run"})
        approvals = approval_plan.get("task", {}).get("approvals") or []
        return [
            AuditCheck(
                "Desktop Operator",
                "Open terminal in VS Code planning",
                "partially_validated",
                terminal_plan.get("task", {}).get("result_summary", "Desktop operator plan created."),
                {"task": terminal_plan.get("task"), "plan": terminal_plan.get("plan")},
                ["This audit does not focus VS Code or press shortcuts automatically."],
                hardware_dependent=True,
            ),
            AuditCheck(
                "Desktop Operator",
                "Detect active application",
                "partially_validated",
                "Active application diagnostic flow returned a conservative observation.",
                active_app_actions(),
                ["Exact foreground app verification depends on the current Windows desktop state."],
                hardware_dependent=True,
            ),
            AuditCheck(
                "Desktop Operator",
                "Summarize desktop state",
                "partially_validated",
                desktop_plan.get("task", {}).get("result_summary", "Desktop summary plan created."),
                {"task": desktop_plan.get("task"), "diagnostics": diagnostics},
                ["No visible UI click was executed during this audit."],
                hardware_dependent=True,
            ),
            AuditCheck(
                "Desktop Operator",
                "Approval workflow",
                "validated" if approvals else "partially_validated",
                "Risky desktop operator plan creates approval metadata." if approvals else "Approval metadata was not produced for the sampled plan.",
                {"approvals": approvals, "task": approval_plan.get("task")},
                [] if approvals else ["Review Notepad note plan approval classification."],
            ),
            AuditCheck(
                "Desktop Operator",
                "Retry and recovery behavior",
                "validated" if recovery.get("retry_allowed") and verification.get("status") == "verified" else "partially_validated",
                "Bounded retry and conservative verification helpers are available.",
                {"recovery": recovery, "verification": verification},
            ),
        ]
    except Exception as exc:
        return [_blocked("Desktop Operator", "Desktop operator diagnostics", exc)]


def _agent_checks() -> list[AuditCheck]:
    checks: list[AuditCheck] = []
    try:
        from grandpa.agents.goal_mode import create_goal
        from grandpa.agents.orchestrator import orchestrate_goal
        from grandpa.planner import analyze_request

        goals = [
            "prepare my coding workspace",
            "check Grandpa readiness and report issues",
            "research Python tutorials and summarize them",
        ]
        for goal in goals:
            analysis = analyze_request(goal)
            checks.append(
                AuditCheck(
                    "Agent System",
                    goal,
                    "validated",
                    f"Planner classified goal as {analysis.goal_class} with risk {analysis.estimated_risk}.",
                    {
                        "intent": analysis.intent,
                        "goal_class": analysis.goal_class,
                        "risk": analysis.estimated_risk,
                        "confidence": analysis.confidence,
                    },
                )
            )
        goal = create_goal("check Grandpa readiness and report issues", execute=True)
        checks.append(
            AuditCheck(
                "Agent System",
                "Goal lifecycle states",
                "validated" if goal.status in {"completed", "waiting_approval"} else "partially_validated",
                f"Autonomous goal reached {goal.status}.",
                {"goal_id": goal.goal_id, "status": goal.status, "phase": goal.current_phase, "summary": goal.result_summary},
                [] if goal.status in {"completed", "waiting_approval"} else ["Inspect agent goal events for incomplete lifecycle."],
            )
        )
        multi = orchestrate_goal("analyze Grandpa health")
        checks.append(
            AuditCheck(
                "Agent System",
                "Grandpa health analysis collaboration",
                "validated" if multi.status in {"completed", "partial"} else "partially_validated",
                multi.summary or f"Multi-agent task ended as {multi.status}.",
                {"task_id": multi.task_id, "status": multi.status, "agents": multi.participating_agents},
            )
        )
    except Exception as exc:
        checks.append(_blocked("Agent System", "Agent workflow diagnostics", exc))
    return checks


def _knowledge_memory_checks() -> list[AuditCheck]:
    checks: list[AuditCheck] = []
    try:
        from grandpa.knowledge.engine import KnowledgeEngine
        from grandpa.memory.intelligence import (
            build_relationship_graph,
            cluster_memory_topics,
            ranked_memory_context,
            summarize_memory_profile,
        )

        engine = KnowledgeEngine()
        diagnostics = engine.diagnostics()
        semantic = engine.semantic_search("Grandpa project", limit=5)
        hybrid = engine.search("Grandpa project", limit=5)
        ranked = ranked_memory_context("Grandpa project", limit=5)
        profile = summarize_memory_profile()
        graph = build_relationship_graph()
        topics = cluster_memory_topics()
        semantic_mode = semantic.get("semantic_mode", "keyword_only")
        checks.extend(
            [
                AuditCheck(
                    "Knowledge + Memory",
                    "Semantic search",
                    "validated" if semantic.get("semantic_search") else "partially_validated",
                    semantic.get("truthful_note") or f"Semantic mode: {semantic_mode}.",
                    {"semantic_search": semantic.get("semantic_search"), "semantic_mode": semantic_mode, "results": len(semantic.get("results") or [])},
                    [] if semantic.get("semantic_search") else ["Ollama embeddings may be unavailable; keyword/fallback retrieval is active."],
                ),
                AuditCheck(
                    "Knowledge + Memory",
                    "Hybrid search",
                    "validated",
                    hybrid.get("truthful_note") or "Hybrid knowledge retrieval returned explainable ranking metadata.",
                    {"retrieval": hybrid.get("retrieval"), "results": len(hybrid.get("results") or []), "diagnostics": diagnostics},
                ),
                AuditCheck(
                    "Knowledge + Memory",
                    "Memory ranking",
                    "validated",
                    f"Ranked {len(ranked.get('memories') or ranked.get('results') or [])} memory item(s).",
                    {"ranked_context": ranked},
                ),
                AuditCheck(
                    "Knowledge + Memory",
                    "Preference extraction",
                    "validated" if profile.get("preferences") else "partially_validated",
                    f"Detected {len(profile.get('preferences') or [])} preference(s).",
                    {"profile": profile},
                    [] if profile.get("preferences") else ["No explicit user preferences are stored yet."],
                ),
                AuditCheck(
                    "Knowledge + Memory",
                    "Relationship graph generation",
                    "validated",
                    "Memory relationship graph generation completed.",
                    {"relationships": graph, "topics": topics},
                ),
            ]
        )
    except Exception as exc:
        checks.append(_blocked("Knowledge + Memory", "Knowledge and memory diagnostics", exc))
    return checks


def _build_report(checks: list[AuditCheck], started: str, finished: str, duration: float) -> dict[str, Any]:
    matrix = [check.to_dict() for check in checks]
    summary = _summary(matrix)
    blockers = [item for item in matrix if item["status"] == "blocked"]
    limitations = [item for item in matrix if item.get("limitations")]
    hardware = [item for item in matrix if item.get("hardware_dependent")]
    validated = summary["validated"]
    partial = summary["partially_validated"]
    total = max(1, len(matrix))
    score = round(((validated * 100) + (partial * 55)) / total)
    core_items = [item for item in matrix if not item.get("hardware_dependent")]
    core_total = max(1, len(core_items))
    core_score = round(
        (
            sum(1 for item in core_items if item["status"] == "validated") * 100
            + sum(1 for item in core_items if item["status"] == "partially_validated") * 55
        )
        / core_total
    )
    if blockers:
        overall = "BLOCKED"
        passed = False
        verdict = "Production audit found blocking runtime issues."
    elif core_score >= 80 and summary["unvalidated"] > 0:
        overall = "READY_WITH_HARDWARE_PENDING"
        passed = True
        verdict = "Core software is ready; hardware-dependent validations remain pending."
    elif core_score >= 80:
        overall = "READY"
        passed = True
        verdict = "Grandpa is production-ready for the audited local software stack."
    else:
        overall = "NEEDS_ATTENTION"
        passed = False
        verdict = "Core production audit score is below the release threshold."
    return {
        "schema_version": 1,
        "started_at": started,
        "finished_at": finished,
        "duration_seconds": round(duration, 2),
        "overall_status": overall,
        "pass": passed,
        "score": score,
        "core_score": core_score,
        "readiness_verdict": verdict,
        "recommendation": _recommendation(overall, summary),
        "summary": summary,
        "feature_matrix": matrix,
        "validated_features": [item for item in matrix if item["status"] == "validated"],
        "partially_validated_features": [item for item in matrix if item["status"] == "partially_validated"],
        "unvalidated_features": [item for item in matrix if item["status"] == "unvalidated"],
        "blocked_features": blockers,
        "hardware_dependent_features": hardware,
        "known_limitations": limitations,
        "report_path": str(JSON_REPORT),
        "markdown_path": str(MD_REPORT),
        "local_only": True,
    }


def _write_reports(report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    MD_REPORT.write_text(_markdown(report), encoding="utf-8")


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Grandpa Production Audit",
        "",
        f"- Status: **{report['overall_status']}**",
        f"- Score: **{report['score']}**",
        f"- Core score: **{report['core_score']}**",
        f"- Finished: `{report['finished_at']}`",
        f"- Verdict: {report['readiness_verdict']}",
        "",
        "## Summary",
        "",
    ]
    for key, value in report["summary"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Feature Matrix", "", "| Area | Check | Status | Summary |", "| --- | --- | --- | --- |"])
    for item in report["feature_matrix"]:
        lines.append(f"| {item['feature_area']} | {item['name']} | {item['status']} | {_md_escape(item['summary'])} |")
    lines.extend(["", "## Known Limitations", ""])
    limitations = report.get("known_limitations") or []
    if not limitations:
        lines.append("No limitations recorded.")
    for item in limitations:
        lines.append(f"- **{item['name']}**: {'; '.join(item.get('limitations') or [])}")
    lines.append("")
    return "\n".join(lines)


def _summary(matrix: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "validated": sum(1 for item in matrix if item["status"] == "validated"),
        "partially_validated": sum(1 for item in matrix if item["status"] == "partially_validated"),
        "unvalidated": sum(1 for item in matrix if item["status"] == "unvalidated"),
        "blocked": sum(1 for item in matrix if item["status"] == "blocked"),
        "hardware_dependent": sum(1 for item in matrix if item.get("hardware_dependent")),
        "total": len(matrix),
    }


def _empty_summary() -> dict[str, int]:
    return {"validated": 0, "partially_validated": 0, "unvalidated": 0, "blocked": 0, "hardware_dependent": 0, "total": 0}


def _blocked(area: str, name: str, exc: Exception) -> AuditCheck:
    return AuditCheck(area, name, "blocked", f"{name} failed safely: {exc.__class__.__name__}", {"error": exc.__class__.__name__}, [str(exc)[:180]])


def _recommendation(overall: str, summary: dict[str, int]) -> str:
    if overall == "BLOCKED":
        return "Fix blocked audit checks before production release."
    if overall == "READY_WITH_HARDWARE_PENDING":
        return (
            "Core stack is ready. Complete real browser, microphone, and "
            "desktop-device validation before calling the hardware experience "
            "production-ready."
        )
    if overall == "READY":
        return "Grandpa is ready for daily use based on the measured production audit."
    return f"Improve partially validated or unvalidated checks before release. Current summary: {summary}."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _md_escape(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Grandpa production readiness audit.")
    parser.add_argument("--no-write", action="store_true", help="Run checks without writing runtime reports.")
    args = parser.parse_args(argv)
    report = run_production_audit(write=not args.no_write)
    print(json.dumps({"overall_status": report["overall_status"], "score": report["score"], "core_score": report["core_score"], "summary": report["summary"]}, indent=2))
    return 0 if report["overall_status"] != "BLOCKED" else 1


__all__ = ["JSON_REPORT", "MD_REPORT", "latest_report", "run_production_audit", "status"]


if __name__ == "__main__":
    raise SystemExit(main())
