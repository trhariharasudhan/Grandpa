"""Generate Grandpa test-suite health reports.

This script is intentionally conservative: it does not hide pytest failures.
It records command status, parses the terminal summary when available, and
writes machine/human-readable reports under ``runtime/reports``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "runtime" / "reports"
JSON_REPORT = REPORT_DIR / "test-suite-report.json"
MD_REPORT = REPORT_DIR / "test-suite-report.md"
FULL_JSON_REPORT = REPORT_DIR / "test-suite-full-report.json"
FULL_MD_REPORT = REPORT_DIR / "test-suite-full-report.md"
RELEASE_JSON_REPORT = REPORT_DIR / "test-suite-release-report.json"
RELEASE_MD_REPORT = REPORT_DIR / "test-suite-release-report.md"
PYTEST_COMMAND = [
    "uv",
    "run",
    "--extra",
    "dev",
    "--python",
    "3.11",
    "python",
    "-m",
    "pytest",
]


@dataclass
class SuiteResult:
    name: str
    command: str
    status: str
    exit_code: int
    duration_seconds: float
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    xfailed: int = 0
    errors: int = 0
    warnings: int = 0
    summary: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Grandpa pytest health suites.")
    parser.add_argument("--full", action="store_true", help="Run full pytest tests.")
    parser.add_argument("--release", action="store_true", help="Run release-marked tests.")
    parser.add_argument(
        "--release-only",
        action="store_true",
        help="Run only the release-marked suite.",
    )
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)

    suites: list[SuiteResult] = []
    run_release = args.release or args.release_only or not args.full
    run_full = args.full and not args.release_only

    if run_release:
        suites.append(
            _run_suite(
                "release",
                [*PYTEST_COMMAND, "-m", "release", "-q", "--tb=short"],
                args.timeout,
            )
        )
    if run_full:
        suites.append(
            _run_suite(
                "full",
                [*PYTEST_COMMAND, "tests", "-q", "--tb=short"],
                args.timeout,
            )
        )

    blockers = [suite for suite in suites if suite.exit_code != 0]
    json_report, md_report = _report_paths(run_full=run_full, run_release=run_release)
    report = {
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "fail" if blockers else "pass",
        "blockers": [asdict(item) for item in blockers],
        "suites": [asdict(item) for item in suites],
        "classification": {
            "core": "Deterministic local tests that should pass in ordinary development.",
            "release": "Curated release blockers used by the final release gate.",
            "integration": "Cross-module tests; may be core or optional depending on resources.",
            "optional": "Requires opt-in dependency, credential, external service, or live device.",
            "environment": "Requires a platform/backend such as a browser, microphone, or Rust extension.",
            "slow": "Long-running tests excluded from quick loops unless explicitly selected.",
        },
    }
    report_json = json.dumps(report, indent=2)
    report_markdown = _markdown(report)
    json_report.write_text(report_json, encoding="utf-8")
    md_report.write_text(report_markdown, encoding="utf-8")
    JSON_REPORT.write_text(report_json, encoding="utf-8")
    MD_REPORT.write_text(report_markdown, encoding="utf-8")
    print(f"Test suite report: {report['status']}")
    print(f"JSON: {json_report}")
    print(f"Markdown: {md_report}")
    return 1 if blockers else 0


def _report_paths(*, run_full: bool, run_release: bool) -> tuple[Path, Path]:
    if run_full:
        return FULL_JSON_REPORT, FULL_MD_REPORT
    if run_release:
        return RELEASE_JSON_REPORT, RELEASE_MD_REPORT
    return JSON_REPORT, MD_REPORT


def _run_suite(command_name: str, command: list[str], timeout: int) -> SuiteResult:
    started = datetime.now(timezone.utc)
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".uv-cache"))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    duration = (datetime.now(timezone.utc) - started).total_seconds()
    output = completed.stdout or ""
    counts = _parse_counts(output)
    return SuiteResult(
        name=command_name,
        command=" ".join(command),
        status="pass" if completed.returncode == 0 else "fail",
        exit_code=completed.returncode,
        duration_seconds=duration,
        summary=_tail(output),
        **counts,
    )


def _parse_counts(output: str) -> dict[str, int]:
    counts = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "xfailed": 0,
        "errors": 0,
        "warnings": 0,
    }
    summary_lines = [line for line in output.splitlines() if " in " in line and any(k in line for k in counts)]
    if not summary_lines:
        return counts
    summary = summary_lines[-1]
    patterns = {
        "passed": r"(\d+) passed",
        "failed": r"(\d+) failed",
        "skipped": r"(\d+) skipped",
        "xfailed": r"(\d+) xfailed",
        "errors": r"(\d+) error",
        "warnings": r"(\d+) warning",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, summary)
        if match:
            counts[key] = int(match.group(1))
    return counts


def _tail(output: str, lines: int = 12) -> str:
    return "\n".join(output.strip().splitlines()[-lines:])


def _markdown(report: dict[str, object]) -> str:
    suites = report.get("suites", [])
    lines = [
        "# Grandpa Test Suite Report",
        "",
        f"Status: **{report['status']}**",
        f"Finished: `{report['finished_at']}`",
        "",
        "| Suite | Status | Passed | Failed | Skipped | XFailed | Errors | Duration |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for suite in suites:
        lines.append(
            "| {name} | {status} | {passed} | {failed} | {skipped} | {xfailed} | {errors} | {duration_seconds:.1f}s |".format(
                **suite
            )
        )
    lines.extend(
        [
            "",
            "## Marker Classes",
            "",
            "- `core`: deterministic local test.",
            "- `release`: release-blocking curated test.",
            "- `optional`: requires opt-in dependency/service/device.",
            "- `environment`: platform-specific or external runtime.",
            "- `slow`: intentionally long-running.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
