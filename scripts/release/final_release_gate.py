"""Final release-readiness gate for Grandpa.

The gate is intentionally local-first and deterministic. It separates blocking
failures from optional environment gaps so the project can say "not packaged"
without pretending daily use is broken.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "runtime" / "reports"
JSON_REPORT = REPORT_DIR / "final-release-gate.json"
MD_REPORT = REPORT_DIR / "final-release-gate.md"

GateStatus = Literal["pass", "fail", "warn", "skipped"]

NON_BLOCKING_WARNING_HINTS = {
    "docker": "Docker daemon off is optional unless you are publishing container images.",
    "voice": "Real microphone hardware cannot be fully validated from an unattended CLI check.",
    "engine": "Optional cloud/local engines may be unavailable while the default engine works.",
}


@dataclass(frozen=True)
class GateCheck:
    name: str
    command: list[str] = field(default_factory=list)
    cwd: Path = ROOT
    timeout: int = 180
    required: bool = True
    optional_reason: str = ""
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class GateResult:
    name: str
    status: GateStatus
    required: bool
    command: str
    cwd: str
    duration_seconds: float
    summary: str
    warning_classification: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Grandpa's final release gate.")
    parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    started = _now()
    results: list[GateResult] = []

    results.append(_git_status_check())
    results.append(_tracked_artifact_check())

    checks = [
        GateCheck("dependency sanity", ["uv", "sync", "--extra", "server", "--link-mode=copy"], timeout=240),
        GateCheck(
            "doctor dashboard",
            ["uv", "run", "grandpa", "doctor"],
            timeout=300,
            env={"GRANDPA_DOCTOR_SKIP_RELEASE_GATE": "1"},
        ),
        GateCheck(
            "daily-use validator",
            ["uv", "run", "--python", "3.11", "python", "scripts\\validate_daily_use.py", "--skip-app-launch", "--skip-docker"],
            timeout=360,
        ),
        GateCheck(
            "release-grade pytest",
            [
                "uv",
                "run",
                "--python",
                "3.11",
                "python",
                "scripts\\testing\\test_suite_report.py",
                "--release-only",
            ],
            timeout=420,
        ),
    ]
    for check in checks:
        results.append(_run_check(check))

    results.append(_release_manifest_check())
    results.append(_full_suite_report_check())

    report = _build_report(started, results)
    JSON_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    MD_REPORT.write_text(_markdown_report(report), encoding="utf-8")

    print(f"Final release gate: {report['overall_status']}")
    print(f"Blockers: {len(report['blockers'])}; warnings: {len(report['warnings'])}; optional skipped: {len(report['skipped_optional'])}")
    print(f"JSON: {JSON_REPORT}")
    print(f"Markdown: {MD_REPORT}")
    return 1 if report["blockers"] else 0


def _git_status_check() -> GateResult:
    started = datetime.now()
    completed = _subprocess(["git", "status", "--short"], ROOT, 30)
    duration = (datetime.now() - started).total_seconds()
    output = completed[1]
    if completed[0] != 0:
        return GateResult("git status summary", "fail", True, "git status --short", str(ROOT), duration, _tail(output))
    if output.strip():
        return GateResult(
            "git status summary",
            "warn",
            False,
            "git status --short",
            str(ROOT),
            duration,
            f"Working tree has {len(output.splitlines())} changed/untracked item(s). Commit before pushing a release.",
        )
    return GateResult("git status summary", "pass", False, "git status --short", str(ROOT), duration, "Working tree clean.")


def _tracked_artifact_check() -> GateResult:
    started = datetime.now()
    completed = _subprocess(["git", "ls-files"], ROOT, 30)
    duration = (datetime.now() - started).total_seconds()
    if completed[0] != 0:
        return GateResult("ignored/generated artifact check", "fail", True, "git ls-files", str(ROOT), duration, _tail(completed[1]))
    tracked = completed[1].splitlines()
    bad_prefixes = (
        "runtime/logs/",
        "runtime/reports/",
    )
    bad_suffixes = (".pyc",)
    offenders = [item for item in tracked if item.startswith(bad_prefixes) or item.endswith(bad_suffixes)]
    if offenders:
        return GateResult(
            "ignored/generated artifact check",
            "fail",
            True,
            "git ls-files",
            str(ROOT),
            duration,
            "Tracked generated artifacts: " + ", ".join(offenders[:12]),
        )
    return GateResult("ignored/generated artifact check", "pass", True, "git ls-files", str(ROOT), duration, "No tracked generated artifacts found.")


def _run_check(check: GateCheck) -> GateResult:
    started = datetime.now()
    code, output = _subprocess(check.command, check.cwd, check.timeout, extra_env=check.env)
    duration = (datetime.now() - started).total_seconds()
    command = _command_text(check.command)
    if code != 0:
        status: GateStatus = "fail" if check.required else "warn"
        return GateResult(check.name, status, check.required, command, str(check.cwd), duration, _tail(output), _classify_warning(output))
    warning = _classify_warning(output)
    return GateResult(check.name, "pass", check.required, command, str(check.cwd), duration, _tail(output) or "completed", warning)


def _release_manifest_check() -> GateResult:
    releases = ROOT / "dist" / "releases"
    if not releases.exists():
        return GateResult(
            "release manifest sanity",
            "skipped",
            False,
            "read dist/releases/*/release-manifest.json",
            str(ROOT),
            0,
            "No release artifact folder exists yet.",
        )
    manifests = sorted(releases.glob("*/release-manifest.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not manifests:
        return GateResult(
            "release manifest sanity",
            "warn",
            False,
            "read dist/releases/*/release-manifest.json",
            str(ROOT),
            0,
            "Release folders exist but no release-manifest.json was found.",
        )
    try:
        json.loads(manifests[0].read_text(encoding="utf-8"))
    except Exception as exc:
        return GateResult("release manifest sanity", "warn", False, str(manifests[0]), str(ROOT), 0, f"Manifest is invalid JSON: {exc}")
    return GateResult("release manifest sanity", "pass", False, str(manifests[0]), str(ROOT), 0, f"Valid manifest: {manifests[0]}")


def _full_suite_report_check() -> GateResult:
    report_path = REPORT_DIR / "test-suite-full-report.json"
    if not report_path.exists():
        return GateResult(
            "full pytest suite status",
            "warn",
            False,
            "read runtime/reports/test-suite-full-report.json",
            str(ROOT),
            0,
            "No full-suite report found. Run `uv run --python 3.11 python scripts\\testing\\test_suite_report.py --full`.",
        )
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return GateResult(
            "full pytest suite status",
            "warn",
            False,
            str(report_path),
            str(ROOT),
            0,
            f"Full-suite report is not readable JSON: {exc}",
        )
    status = str(data.get("status") or "unknown")
    suites = data.get("suites") or []
    summary = f"Latest full-suite report status: {status}; suites recorded: {len(suites)}."
    return GateResult(
        "full pytest suite status",
        "pass" if status == "pass" else "warn",
        False,
        str(report_path),
        str(ROOT),
        0,
        summary,
    )


def _build_report(started: str, results: list[GateResult]) -> dict[str, object]:
    blockers = [asdict(item) for item in results if item.status == "fail" and item.required]
    warnings = [asdict(item) for item in results if item.status == "warn" or (item.warning_classification and item.status == "pass")]
    skipped = [asdict(item) for item in results if item.status == "skipped"]
    passed = [asdict(item) for item in results if item.status == "pass"]
    overall = "READY" if not blockers else "BLOCKED"
    recommendation = (
        "Ready for daily use and packaging checks passed. Commit intentional changes before pushing."
        if overall == "READY"
        else "Do not commit/push/package as a release until blockers are fixed."
    )
    if overall == "READY" and any(item.name == "git status summary" and item.status == "warn" for item in results):
        recommendation = "Ready after reviewing and committing intentional working-tree changes."
    return {
        "schema_version": 1,
        "started_at": started,
        "finished_at": _now(),
        "overall_status": overall,
        "pass": not blockers,
        "ready_to_commit": not blockers,
        "ready_to_push": not blockers and not any(item.name == "git status summary" and item.status == "warn" for item in results),
        "ready_to_package": not blockers,
        "recommendation": recommendation,
        "blockers": blockers,
        "warnings": warnings,
        "skipped_optional": skipped,
        "checks": [asdict(item) for item in results],
        "summary": {
            "passed": len(passed),
            "warnings": len(warnings),
            "blockers": len(blockers),
            "skipped_optional": len(skipped),
        },
    }


def _markdown_report(report: dict[str, object]) -> str:
    lines = [
        "# Grandpa Final Release Gate",
        "",
        f"- Status: **{report['overall_status']}**",
        f"- Started: `{report['started_at']}`",
        f"- Finished: `{report['finished_at']}`",
        f"- Recommendation: {report['recommendation']}",
        "",
        "## Summary",
        "",
        f"- Passed: {report['summary']['passed']}",  # type: ignore[index]
        f"- Warnings: {report['summary']['warnings']}",  # type: ignore[index]
        f"- Blockers: {report['summary']['blockers']}",  # type: ignore[index]
        f"- Optional skipped: {report['summary']['skipped_optional']}",  # type: ignore[index]
        "",
        "## Validation Matrix",
        "",
        "| Check | Status | Required | Summary |",
        "| --- | --- | --- | --- |",
    ]
    for item in report["checks"]:  # type: ignore[index]
        summary = str(item["summary"]).replace("\n", "<br>")
        lines.append(f"| {item['name']} | {item['status']} | {item['required']} | {summary} |")
    if report["blockers"]:  # type: ignore[index]
        lines.extend(["", "## Blockers", ""])
        for item in report["blockers"]:  # type: ignore[index]
            lines.append(f"- **{item['name']}**: {item['summary']}")
    if report["warnings"]:  # type: ignore[index]
        lines.extend(["", "## Warnings", ""])
        for item in report["warnings"]:  # type: ignore[index]
            extra = f" ({item['warning_classification']})" if item.get("warning_classification") else ""
            lines.append(f"- **{item['name']}**: {item['summary']}{extra}")
    return "\n".join(lines) + "\n"


def _subprocess(command: list[str], cwd: Path, timeout: int, *, extra_env: dict[str, str] | None = None) -> tuple[int, str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return 127, f"Command not found: {exc}"
    except subprocess.TimeoutExpired as exc:
        return 124, f"Timed out after {timeout}s. {exc}"
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part and part.strip())
    return completed.returncode, output


def _classify_warning(output: str) -> str:
    lower = output.lower()
    if "docker daemon" in lower or "cannot connect to the docker daemon" in lower:
        return NON_BLOCKING_WARNING_HINTS["docker"]
    if "microphone" in lower or "browser-based speech" in lower:
        return NON_BLOCKING_WARNING_HINTS["voice"]
    if "unreachable" in lower and "engine" in lower:
        return NON_BLOCKING_WARNING_HINTS["engine"]
    return ""


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _tail(text: str, max_chars: int = 2500) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return "..." + text[-max_chars:]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    sys.exit(main())
