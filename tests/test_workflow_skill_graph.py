from __future__ import annotations

import json
import sqlite3
import time

from grandpa import smart_automation
from grandpa.skills.runtime import SkillResult


def test_old_raw_workflow_still_loads_and_safe_step_converts(tmp_path):
    db_path = tmp_path / "workflows.db"
    store = smart_automation.WorkflowStore(db_path)
    now = time.time()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO workflows(created_at, updated_at, name, trigger_json, steps_json, enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                "legacy",
                json.dumps({"type": "manual", "value": "run_on_request"}),
                json.dumps([{"action": "desktop summary"}, {"action": "open chrome"}]),
                1,
            ),
        )

    workflow = store.get("legacy")
    assert workflow is not None
    assert workflow["steps"][0]["schema_version"] == smart_automation.SKILL_GRAPH_V2
    assert workflow["steps"][0]["skill"] == "desktop.summary"
    assert workflow["steps"][1]["schema_version"] == smart_automation.RAW_ACTION_V1

    simulated = smart_automation.simulate_workflow("legacy", store=store)
    assert simulated.status == "handled"
    assert simulated.data["simulation"][0]["execution_source"] == "skill_runtime"
    assert simulated.data["simulation"][1]["execution_source"] == "legacy"


def test_planner_workflow_creates_skill_graph_steps(tmp_path):
    store = smart_automation.WorkflowStore(tmp_path / "workflows.db")
    created = smart_automation.create_workflow_from_text("start my coding workspace", store=store)

    assert created.status == "handled"
    steps = created.data["workflow"]["steps"]
    assert {step["schema_version"] for step in steps} == {smart_automation.SKILL_GRAPH_V2}
    assert [step["skill"] for step in steps] == ["desktop.summary", "automation.workflow_status"]

    simulated = smart_automation.simulate_workflow(created.data["workflow"]["name"], store=store)
    assert simulated.data["dry_run"] is True
    assert all(item["execution_source"] == "skill_runtime" for item in simulated.data["simulation"])


def test_skill_execution_failure_marks_step_failed_truthfully(tmp_path, monkeypatch):
    import grandpa.skills.registry as registry

    def fail_skill(*_args, **_kwargs):
        return SkillResult(ok=False, status="failed", message="Injected failure.", error="Injected")

    monkeypatch.setattr(registry, "execute_skill", fail_skill)
    store = smart_automation.WorkflowStore(tmp_path / "workflows.db")
    store.save(
        "diagnostics",
        {"type": "manual", "value": "run_on_request"},
        [{"schema_version": smart_automation.SKILL_GRAPH_V2, "skill": "desktop.summary", "params": {}, "action": "desktop summary"}],
    )

    simulated = smart_automation.simulate_workflow("diagnostics", store=store)
    assert simulated.data["status"] == "failed"
    assert simulated.data["simulation"][0]["status"] == "failed"
    assert simulated.data["simulation"][0]["message"] == "Injected failure."


def test_approval_required_skill_pauses_workflow(tmp_path):
    store = smart_automation.WorkflowStore(tmp_path / "workflows.db")
    store.save(
        "approval_needed",
        {"type": "manual", "value": "run_on_request"},
        [
            {
                "schema_version": smart_automation.SKILL_GRAPH_V2,
                "skill": "desktop.keyboard_type",
                "params": {"text": "hello"},
                "action": "type hello",
                "risk_level": "MEDIUM",
                "approval_required": True,
            }
        ],
    )

    simulated = smart_automation.simulate_workflow("approval_needed", store=store)
    assert simulated.data["status"] == "waiting_approval"
    assert simulated.data["simulation"][0]["status"] == "approval_required"
    assert simulated.data["simulation"][0]["approval_required"] is True


def test_workflow_schema_diagnostics_counts_skill_and_legacy(tmp_path):
    store = smart_automation.WorkflowStore(tmp_path / "workflows.db")
    smart_automation.create_workflow_from_text("start my coding workspace", store=store)
    store.save("legacy", {"type": "manual", "value": "run_on_request"}, [{"action": "open chrome"}])

    info = smart_automation.diagnostics(store)
    assert info["schema_versions"][smart_automation.SKILL_GRAPH_V2] >= 2
    assert info["schema_versions"][smart_automation.RAW_ACTION_V1] >= 1
    assert info["skill_backed_workflow_count"] >= 1
    assert info["legacy_workflow_count"] >= 1
