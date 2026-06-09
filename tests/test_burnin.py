from __future__ import annotations

import json

from grandpa import burnin
from grandpa.burnin import BurnInResult


def test_burnin_report_preserves_pending_without_blocking() -> None:
    report = burnin._build_report(
        [
            BurnInResult("desktop summary", "desktop", "pass", 0.1, "ok"),
            BurnInResult(
                "mobile device",
                "mobile",
                "pending",
                0.0,
                "No phone connected.",
                required=True,
                measured=False,
            ),
        ],
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:00:01+00:00",
        1.0,
    )

    assert report["pass"] is True
    assert report["overall_status"] == "READY_WITH_PENDING_VALIDATION"
    assert report["summary"]["pending"] == 1
    assert report["blockers"] == []
    assert "pending" in report["recommendation"].lower()


def test_burnin_planner_workflow_scenarios_use_execution_route() -> None:
    scenarios = {scenario.name: scenario for scenario in burnin._scenario_pack(timeout_seconds=30)}

    assert scenarios["desktop diagnostics"].runner == "local_action_execute"
    assert scenarios["start coding workspace"].runner == "local_action_execute"
    assert scenarios["organize downloads"].runner == "local_action_execute"
    assert scenarios["planner research"].runner == "local_action_execute"
    assert scenarios["desktop summary"].runner == "local_action"


def test_latest_report_handles_missing_report(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(burnin, "BURNIN_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(burnin, "BURNIN_MD", tmp_path / "missing.md")

    report = burnin.latest_report()

    assert report["overall_status"] == "not_run"
    assert report["pass"] is False


def test_write_and_read_burnin_report(tmp_path, monkeypatch) -> None:
    json_path = tmp_path / "burnin-report.json"
    md_path = tmp_path / "burnin-report.md"
    monkeypatch.setattr(burnin, "BURNIN_DIR", tmp_path)
    monkeypatch.setattr(burnin, "BURNIN_JSON", json_path)
    monkeypatch.setattr(burnin, "BURNIN_MD", md_path)

    report = burnin._build_report(
        [BurnInResult("memory", "memory", "pass", 0.1, "ok")],
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:00:01+00:00",
        1.0,
    )
    burnin._write_reports(report)

    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["passed"] == 1
    assert "Grandpa Daily-Use Burn-In Report" in md_path.read_text(encoding="utf-8")
