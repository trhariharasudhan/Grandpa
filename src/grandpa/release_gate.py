"""Read-only helpers for the latest final release gate report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "runtime" / "reports" / "final-release-gate.json"


def latest_release_gate_report() -> dict[str, Any]:
    """Return the latest gate report, or a not-run status."""
    if not REPORT_PATH.exists():
        return {
            "status": "not_run",
            "overall_status": "NOT RUN",
            "pass": False,
            "message": "Final release gate has not been run yet.",
            "report_path": str(REPORT_PATH),
        }
    try:
        data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "invalid",
            "overall_status": "INVALID",
            "pass": False,
            "message": f"Final release gate report could not be parsed: {exc.__class__.__name__}",
            "report_path": str(REPORT_PATH),
        }
    data.setdefault("status", "ready")
    data.setdefault("report_path", str(REPORT_PATH))
    return data


def release_gate_status() -> dict[str, Any]:
    """Return compact status suitable for dashboards and doctor."""
    report = latest_release_gate_report()
    return {
        "status": report.get("status", "ready"),
        "overall_status": report.get("overall_status", "UNKNOWN"),
        "pass": bool(report.get("pass", False)),
        "ready_to_commit": bool(report.get("ready_to_commit", False)),
        "ready_to_push": bool(report.get("ready_to_push", False)),
        "ready_to_package": bool(report.get("ready_to_package", False)),
        "recommendation": report.get("recommendation") or report.get("message", ""),
        "finished_at": report.get("finished_at"),
        "summary": report.get("summary", {}),
        "report_path": report.get("report_path", str(REPORT_PATH)),
    }


__all__ = ["latest_release_gate_report", "release_gate_status"]
