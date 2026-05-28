from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "dev" / "audit_grandpa_features.py"
AUDIT = ROOT / "docs" / "GRANDPA_FEATURE_AUDIT.md"
TRACKER = ROOT / "docs" / "GRANDPA_FEATURE_TRACKER.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("grandpa_feature_audit", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_feature_tracker_json_is_valid_and_complete():
    data = json.loads(TRACKER.read_text(encoding="utf-8"))
    features = data["features"]

    assert data["project"] == "GrandpaAssistant"
    assert len(features) == 16
    assert data["summary"]["active_forbidden_branding_references"] == 0
    for feature in features:
        assert feature["feature"]
        assert feature["status"] in {"COMPLETE", "PARTIAL", "MISSING", "UNKNOWN"}
        assert 0 <= feature["percent_complete"] <= 100
        assert feature["priority"] in {"P0", "P1", "P2", "P3"}
        assert isinstance(feature["evidence_files"], list)
        assert isinstance(feature["missing_items"], list)
        assert isinstance(feature["next_tasks"], list)
        assert isinstance(feature["test_requirements"], list)


def test_feature_audit_doc_contains_required_sections():
    text = AUDIT.read_text(encoding="utf-8")

    for heading in (
        "Core AI Brain",
        "Voice Assistant",
        "PC Control",
        "Browser Control",
        "Mobile Integration",
        "File & Document Intelligence",
        "Office Productivity",
        "Smart Automation",
        "Screen Awareness",
        "Real World Task Assistance",
        "Chat App Integration",
        "Developer Features",
        "Advanced AI Features",
        "Security & Safety",
        "IoT / Smart Home",
        "Future-Level Features",
    ):
        assert f"### {heading}" in text
    assert "Current Status:" in text
    assert "Implementation Plan:" in text


def test_audit_script_reports_no_active_forbidden_identity_references():
    module = _load_module()
    data = module.tracker_data()

    assert data["summary"]["active_forbidden_branding_references"] == 0
    assert data["summary"]["generated_lockfile_branding_references"] >= 0
