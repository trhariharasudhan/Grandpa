"""Generate Grandpa feature audit docs and scan identity hygiene.

This script is intentionally read-only unless ``--write`` is passed. It scans
the repository for legacy identity strings, feature evidence files, and missing
expected components, then can write:

* docs/GRANDPA_FEATURE_AUDIT.md
* docs/GRANDPA_FEATURE_TRACKER.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "docs" / "GRANDPA_FEATURE_AUDIT.md"
TRACKER_PATH = ROOT / "docs" / "GRANDPA_FEATURE_TRACKER.json"

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".venv311",
    "node_modules",
    "build",
    "cache",
    "__pycache__",
    ".pytest_cache",
}
TEXT_EXTENSIONS = {
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".lock",
    ".md",
    ".py",
    ".rs",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
GENERATED_EXCEPTION_FILES = {
    "frontend/src-tauri/Cargo.lock",
    "rust/Cargo.lock",
    "rust/crates/grandpa-python/uv.lock",
}

FORBIDDEN_PATTERNS = (
    re.compile("open" + "jar" + "vis", re.IGNORECASE),
    re.compile("jar" + "vis", re.IGNORECASE),
)


@dataclass(frozen=True)
class FeatureSpec:
    feature: str
    status: str
    percent_complete: int
    priority: str
    evidence_files: tuple[str, ...]
    missing_items: tuple[str, ...]
    next_tasks: tuple[str, ...]
    test_requirements: tuple[str, ...]


FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        feature="Core AI Brain",
        status="PARTIAL",
        percent_complete=78,
        priority="P0",
        evidence_files=(
            "src/grandpa/cli/ask.py",
            "src/grandpa/cli/chat_cmd.py",
            "src/grandpa/engine/ollama.py",
            "src/grandpa/engine/multi.py",
            "src/grandpa/server/routes.py",
            "src/grandpa/agents/_stubs.py",
            "src/grandpa/response_cleanup.py",
        ),
        missing_items=(
            "Unified deterministic routing helper shared by CLI, API, and frontend.",
            "More model-specific prompt/response conformance tests.",
            "Streaming cleanup for untagged reasoning leaks.",
        ),
        next_tasks=(
            "Extract deterministic command routing into one service.",
            "Add response-quality regression fixtures for local models.",
            "Add streaming guardrail tests at API level.",
        ),
        test_requirements=(
            "CLI ask smoke tests.",
            "API chat completion route tests.",
            "Ollama payload and response cleanup tests.",
        ),
    ),
    FeatureSpec(
        feature="Voice Assistant",
        status="PARTIAL",
        percent_complete=62,
        priority="P1",
        evidence_files=(
            "frontend/src/hooks/useSpeech.ts",
            "frontend/src/hooks/useWakeWord.ts",
            "frontend/src/components/Chat/MicButton.tsx",
            "frontend/src/components/Chat/InputArea.tsx",
            "src/grandpa/speech",
        ),
        missing_items=(
            "Automated browser permission and SpeechRecognition tests.",
            "Backend STT/TTS provider setup validation.",
            "Wake-word reliability metrics.",
        ),
        next_tasks=(
            "Add Playwright coverage for mic states where browser APIs are mocked.",
            "Add speech health details to Settings.",
            "Add explicit voice troubleshooting panel.",
        ),
        test_requirements=(
            "Frontend build.",
            "Mocked SpeechRecognition unit tests.",
            "Manual Chrome/Edge microphone permission test.",
        ),
    ),
    FeatureSpec(
        feature="PC Control",
        status="PARTIAL",
        percent_complete=74,
        priority="P0",
        evidence_files=(
            "src/grandpa/local_actions.py",
            "src/grandpa/windows_app_resolver.py",
            "src/grandpa/windows_window_control.py",
            "src/grandpa/desktop_automation.py",
            "tests/test_local_actions.py",
            "tests/test_windows_window_control.py",
            "tests/test_windows_app_resolver.py",
        ),
        missing_items=(
            "Human-in-the-loop UI for every medium-risk desktop action.",
            "More Windows API integration tests on real Windows runners.",
            "Emergency stop runtime control.",
        ),
        next_tasks=(
            "Promote approval cards into a reusable action console.",
            "Add live local-action activity feed.",
            "Add pywin32-specific focus/minimize coverage when available.",
        ),
        test_requirements=(
            "Safe command parser tests.",
            "Blocked dangerous command tests.",
            "Mocked window-control tests.",
        ),
    ),
    FeatureSpec(
        feature="Browser Control",
        status="PARTIAL",
        percent_complete=42,
        priority="P1",
        evidence_files=(
            "src/grandpa/local_actions.py",
            "src/grandpa/screen_awareness.py",
            "frontend/src/components/Chat/InputArea.tsx",
        ),
        missing_items=(
            "Browser DOM/page extraction layer.",
            "Current tab title/content integration.",
            "Safe browser automation permission model beyond URL/search actions.",
        ),
        next_tasks=(
            "Add browser page summary endpoint using accessible text only.",
            "Add tab/window detection for supported browsers.",
            "Create browser-control safety policy tests.",
        ),
        test_requirements=(
            "Open/search URL parser tests.",
            "Blocked purchase/payment browser action tests.",
            "Manual browser search smoke test.",
        ),
    ),
    FeatureSpec(
        feature="Mobile Integration",
        status="PARTIAL",
        percent_complete=24,
        priority="P3",
        evidence_files=(
            "src/grandpa/channels",
            "src/grandpa/daemon",
            "docs/user-guide/channels.md",
            "docs/tutorials/messaging-hub.md",
        ),
        missing_items=(
            "Mobile companion app.",
            "Push notification bridge.",
            "Device pairing and local network trust model.",
        ),
        next_tasks=(
            "Design mobile companion architecture.",
            "Add QR/device pairing plan.",
            "Define mobile notification permissions.",
        ),
        test_requirements=(
            "Channel gateway tests.",
            "Future mobile pairing integration tests.",
        ),
    ),
    FeatureSpec(
        feature="File & Document Intelligence",
        status="PARTIAL",
        percent_complete=66,
        priority="P1",
        evidence_files=(
            "src/grandpa/file_assistant.py",
            "frontend/src/pages/FileAssistantPage.tsx",
            "tests/test_file_assistant.py",
            "src/grandpa/tools/storage",
        ),
        missing_items=(
            "Robust PDF/document extraction test fixtures.",
            "Semantic document search.",
            "Safe edit/overwrite approval workflow.",
        ),
        next_tasks=(
            "Add fixture-based txt/md/pdf summarization tests.",
            "Add local vector index for document chunks.",
            "Add safe note editing with confirmation.",
        ),
        test_requirements=(
            "File assistant CLI command tests.",
            "Recent file tracking tests.",
            "Document extraction tests.",
        ),
    ),
    FeatureSpec(
        feature="Office Productivity",
        status="MISSING",
        percent_complete=12,
        priority="P2",
        evidence_files=(
            "src/grandpa/file_assistant.py",
            "docs/development/advanced-feature-backlog.md",
        ),
        missing_items=(
            "Word/Excel/PowerPoint automation.",
            "Calendar and email drafting workflows.",
            "Office document creation/editing UI.",
        ),
        next_tasks=(
            "Define local document generation boundaries.",
            "Add safe export workflows for notes and reports.",
            "Plan optional Microsoft/Google integrations.",
        ),
        test_requirements=(
            "Document generation fixture tests.",
            "Permission tests for external account integrations.",
        ),
    ),
    FeatureSpec(
        feature="Smart Automation",
        status="PARTIAL",
        percent_complete=71,
        priority="P0",
        evidence_files=(
            "src/grandpa/task_scheduler.py",
            "src/grandpa/scheduler_daemon.py",
            "frontend/src/pages/RoutinesPage.tsx",
            "tests/test_task_scheduler.py",
            "tests/test_scheduler_daemon.py",
        ),
        missing_items=(
            "Frontend creation/editing flows for routines.",
            "Full approval lifecycle display for scheduled risky actions.",
            "Long-running daemon resilience tests.",
        ),
        next_tasks=(
            "Add routine creation UI.",
            "Add scheduler daemon heartbeat to HUD.",
            "Add missed-run recovery policy.",
        ),
        test_requirements=(
            "Routine parser tests.",
            "Daemon due-item tests.",
            "Approval-required scheduled action tests.",
        ),
    ),
    FeatureSpec(
        feature="Screen Awareness",
        status="PARTIAL",
        percent_complete=58,
        priority="P1",
        evidence_files=(
            "src/grandpa/screen_awareness.py",
            "frontend/src/components/Chat/InputArea.tsx",
            "src/grandpa/cli/doctor_cmd.py",
        ),
        missing_items=(
            "Reliable OCR setup flow for Tesseract.",
            "Visual target detection/click planning.",
            "Privacy controls for screenshot retention.",
        ),
        next_tasks=(
            "Add screen-awareness settings and diagnostics.",
            "Add OCR fixture tests.",
            "Add explicit no-upload privacy audit.",
        ),
        test_requirements=(
            "Unsupported-platform tests.",
            "Screenshot backend detection tests.",
            "OCR optional dependency tests.",
        ),
    ),
    FeatureSpec(
        feature="Real World Task Assistance",
        status="PARTIAL",
        percent_complete=35,
        priority="P2",
        evidence_files=(
            "src/grandpa/memory_context.py",
            "src/grandpa/task_scheduler.py",
            "src/grandpa/channels",
            "docs/user-guide/morning-digest.md",
        ),
        missing_items=(
            "End-to-end task planning with confirmations.",
            "Calendar/email/reminder ecosystem integrations.",
            "Multi-step execution review UI.",
        ),
        next_tasks=(
            "Create task plan object model.",
            "Add approval checkpoints for multi-step tasks.",
            "Add daily agenda workflow.",
        ),
        test_requirements=(
            "Task decomposition tests.",
            "Approval checkpoint tests.",
            "Failure recovery tests.",
        ),
    ),
    FeatureSpec(
        feature="Chat App Integration",
        status="PARTIAL",
        percent_complete=46,
        priority="P2",
        evidence_files=(
            "src/grandpa/channels",
            "src/grandpa/connectors",
            "src/grandpa/server/channel_bridge.py",
            "docs/tutorials/messaging-hub.md",
            "tests/channels",
        ),
        missing_items=(
            "WhatsApp and Telegram daily-use setup flow.",
            "Unified message permission model.",
            "Frontend channel diagnostics.",
        ),
        next_tasks=(
            "Audit channel route coverage.",
            "Add Telegram/WhatsApp integration plan.",
            "Add inbound/outbound message approval UI.",
        ),
        test_requirements=(
            "Gateway route tests.",
            "Connector auth failure tests.",
            "Message safety tests.",
        ),
    ),
    FeatureSpec(
        feature="Developer Features",
        status="PARTIAL",
        percent_complete=69,
        priority="P1",
        evidence_files=(
            "src/grandpa/cli",
            "src/grandpa/sdk.py",
            "src/grandpa/mcp",
            "src/grandpa/workflow",
            "tests/daemon",
            "tests/a2a",
        ),
        missing_items=(
            "Stable plugin developer guide.",
            "End-to-end workflow authoring UI.",
            "Public API compatibility matrix.",
        ),
        next_tasks=(
            "Document CLI/API extension points.",
            "Add workflow fixture examples.",
            "Add SDK smoke tests to daily validation.",
        ),
        test_requirements=(
            "CLI command tests.",
            "SDK import tests.",
            "MCP/gateway tests.",
        ),
    ),
    FeatureSpec(
        feature="Advanced AI Features",
        status="PARTIAL",
        percent_complete=53,
        priority="P2",
        evidence_files=(
            "src/grandpa/agents",
            "src/grandpa/learning",
            "src/grandpa/intelligence",
            "src/grandpa/operators",
            "src/grandpa/evals",
        ),
        missing_items=(
            "Production semantic vector memory.",
            "Robust multi-agent orchestration UI.",
            "Vision planning for screen targeting.",
        ),
        next_tasks=(
            "Prioritize semantic memory architecture.",
            "Add agent orchestration dashboard tests.",
            "Add eval pack for local assistant tasks.",
        ),
        test_requirements=(
            "Agent unit tests.",
            "Learning/routing tests.",
            "Evaluation smoke tests.",
        ),
    ),
    FeatureSpec(
        feature="Security & Safety",
        status="PARTIAL",
        percent_complete=76,
        priority="P0",
        evidence_files=(
            "src/grandpa/security",
            "src/grandpa/local_action_approvals.py",
            "src/grandpa/local_actions.py",
            "frontend/src/components/Chat/MessageBubble.tsx",
            "tests/test_local_actions.py",
        ),
        missing_items=(
            "Central policy viewer in frontend.",
            "Complete audit log review UI.",
            "Formal threat model for desktop automation.",
        ),
        next_tasks=(
            "Add Safety page or panel.",
            "Add local action audit export.",
            "Write desktop automation threat model.",
        ),
        test_requirements=(
            "Blocked command tests.",
            "Approval expiry tests.",
            "Security middleware tests.",
        ),
    ),
    FeatureSpec(
        feature="IoT / Smart Home",
        status="MISSING",
        percent_complete=5,
        priority="P3",
        evidence_files=(
            "docs/development/advanced-feature-backlog.md",
        ),
        missing_items=(
            "Home Assistant/Matter integration.",
            "Device discovery.",
            "Local network permissions and safety controls.",
        ),
        next_tasks=(
            "Create IoT integration design doc.",
            "Define allowlisted smart-home actions.",
            "Plan Home Assistant connector.",
        ),
        test_requirements=(
            "Future mocked device connector tests.",
            "Permission and safety tests.",
        ),
    ),
    FeatureSpec(
        feature="Future-Level Features",
        status="MISSING",
        percent_complete=18,
        priority="P3",
        evidence_files=(
            "docs/development/advanced-feature-backlog.md",
            "src/grandpa/operators",
            "src/grandpa/learning",
        ),
        missing_items=(
            "Plugin marketplace.",
            "Offline wake-word engine.",
            "Full RAG and vision targeting.",
            "Installer/autostart service hardening.",
        ),
        next_tasks=(
            "Keep backlog scoped behind stable daily-use milestones.",
            "Choose one advanced feature only after P0 features are stable.",
            "Add feature flags for experimental modules.",
        ),
        test_requirements=(
            "Feature flag tests.",
            "Experimental module import tests.",
        ),
    ),
)


def iter_text_files() -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix.lower() in TEXT_EXTENSIONS:
                files.append(path)
    return files


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def scan_forbidden() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    active: list[dict[str, Any]] = []
    generated: list[dict[str, Any]] = []
    for path in iter_text_files():
        relative = rel(path)
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            if not any(pattern.search(line) for pattern in FORBIDDEN_PATTERNS):
                continue
            item = {"file": relative, "line": line_no}
            if relative in GENERATED_EXCEPTION_FILES:
                generated.append(item)
            else:
                active.append(item)
    return active, generated


def feature_to_dict(feature: FeatureSpec) -> dict[str, Any]:
    evidence = [path for path in feature.evidence_files if (ROOT / path).exists()]
    missing_evidence = [path for path in feature.evidence_files if not (ROOT / path).exists()]
    return {
        "feature": feature.feature,
        "status": feature.status,
        "percent_complete": feature.percent_complete,
        "priority": feature.priority,
        "evidence_files": evidence,
        "missing_evidence_files": missing_evidence,
        "missing_items": list(feature.missing_items),
        "next_tasks": list(feature.next_tasks),
        "test_requirements": list(feature.test_requirements),
    }


def tracker_data() -> dict[str, Any]:
    active, generated = scan_forbidden()
    features = [feature_to_dict(feature) for feature in FEATURES]
    avg = round(sum(item["percent_complete"] for item in features) / len(features), 1)
    return {
        "project": "GrandpaAssistant",
        "generated_by": "scripts/dev/audit_grandpa_features.py",
        "summary": {
            "feature_count": len(features),
            "average_completion": avg,
            "active_forbidden_branding_references": len(active),
            "generated_lockfile_branding_references": len(generated),
        },
        "branding_scan": {
            "active_references": active,
            "generated_lockfile_exceptions": generated,
        },
        "features": features,
    }


def render_markdown(data: dict[str, Any]) -> str:
    features = data["features"]
    lines = [
        "# Grandpa Feature Audit",
        "",
        "This audit is generated from repository evidence and is intended to keep GrandpaAssistant original, local-first, and Windows-focused.",
        "",
        "## Identity Hygiene",
        "",
        f"- Active forbidden branding references: {data['summary']['active_forbidden_branding_references']}",
        f"- Generated lockfile legacy identity references: {data['summary']['generated_lockfile_branding_references']}",
        "- Lockfile entries are generated artifacts; update them only through the relevant package manager/build tool.",
        "",
        "## Feature Status Summary",
        "",
        "| Feature Area | Status | Completion | Priority | Evidence Count |",
        "| --- | --- | ---: | --- | ---: |",
    ]
    for item in features:
        lines.append(
            f"| {item['feature']} | {item['status']} | {item['percent_complete']}% | {item['priority']} | {len(item['evidence_files'])} |"
        )
    lines.extend(["", "## Capability Details", ""])
    for item in features:
        lines.extend(
            [
                f"### {item['feature']}",
                "",
                f"- Current Status: {item['status']}",
                f"- Current Level: {item['percent_complete']}%",
                f"- Priority: {item['priority']}",
                "- Current Evidence:",
            ]
        )
        if item["evidence_files"]:
            lines.extend(f"  - `{path}`" for path in item["evidence_files"])
        else:
            lines.append("  - None found.")
        if item["missing_evidence_files"]:
            lines.append("- Missing Expected Evidence Files:")
            lines.extend(f"  - `{path}`" for path in item["missing_evidence_files"])
        lines.append("- Missing Pieces:")
        lines.extend(f"  - {entry}" for entry in item["missing_items"])
        lines.append("- Implementation Plan:")
        lines.extend(f"  - {entry}" for entry in item["next_tasks"])
        lines.append("- Tests Needed:")
        lines.extend(f"  - {entry}" for entry in item["test_requirements"])
        lines.append("")
    lines.extend(
        [
            "## Safe Migration Notes",
            "",
            "- Do not rename `src/grandpa` or `frontend` without updating imports, build configuration, Docker packaging, and tests.",
            "- Do not hand-edit Cargo or uv lockfiles; regenerate them through their package managers if stale generated names need to be refreshed.",
            "- Treat desktop automation, browser control, file operations, and scheduled routines as safety-gated features.",
            "",
        ]
    )
    return "\n".join(lines)


def print_report(data: dict[str, Any]) -> None:
    print("Grandpa feature audit")
    print(f"Features: {data['summary']['feature_count']}")
    print(f"Average completion: {data['summary']['average_completion']}%")
    print(f"Active forbidden branding references: {data['summary']['active_forbidden_branding_references']}")
    print(f"Generated lockfile legacy references: {data['summary']['generated_lockfile_branding_references']}")
    print()
    for item in data["features"]:
        missing = len(item["missing_evidence_files"])
        print(f"{item['feature']}: {item['status']} ({item['percent_complete']}%), missing expected files: {missing}")


def write_outputs(data: dict[str, Any]) -> None:
    AUDIT_PATH.write_text(render_markdown(data), encoding="utf-8")
    TRACKER_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Grandpa feature readiness and identity hygiene.")
    parser.add_argument("--write", action="store_true", help="Write docs/GRANDPA_FEATURE_AUDIT.md and tracker JSON.")
    parser.add_argument("--fail-on-active-branding", action="store_true", help="Exit non-zero if active forbidden branding references remain.")
    args = parser.parse_args()

    data = tracker_data()
    if args.write:
        write_outputs(data)
    print_report(data)
    if args.fail_on_active_branding and data["summary"]["active_forbidden_branding_references"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
