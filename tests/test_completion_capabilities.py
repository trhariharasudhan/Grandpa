from __future__ import annotations

import csv
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa import (
    developer_assistant,
    document_intelligence,
    office_productivity,
    security_safety,
    smart_automation,
)
from grandpa.server.routes import router


def _make_docx(path: Path, text: str) -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>"
        + text
        + "</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)


def _make_pptx(path: Path, text: str) -> None:
    xml = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", xml)


def _make_xlsx(path: Path) -> None:
    shared = (
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<si><t>Date</t></si><si><t>Amount</t></si><si><t>Tools</t></si></sst>"
    )
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>'
        '<row><c><v>20260501</v></c><c><v>42</v></c><c t="s"><v>2</v></c></row>'
        "</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def test_docx_pptx_csv_extraction_and_summary(tmp_path):
    docx = tmp_path / "resume.docx"
    pptx = tmp_path / "plan.pptx"
    xlsx = tmp_path / "expenses.xlsx"
    csv_path = tmp_path / "expenses.csv"
    _make_docx(docx, "Resume Project Grandpa Python automation impact metrics.")
    _make_pptx(pptx, "Grandpa roadmap automation memory browser safety.")
    _make_xlsx(xlsx)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Date", "Amount", "Category"])
        writer.writerow(["2026-05-01", "42.5", "Tools"])

    assert "Resume Project Grandpa" in document_intelligence.extract_document_text(docx)
    assert "Grandpa roadmap" in document_intelligence.extract_document_text(pptx)
    assert "Amount" in document_intelligence.extract_document_text(xlsx)
    tables = document_intelligence.extract_tables(csv_path)
    assert tables[0]["row_count"] == 2
    xlsx_tables = document_intelligence.extract_tables(xlsx)
    assert xlsx_tables[0]["row_count"] == 2
    summary = document_intelligence.summarize_document(docx)
    assert summary.status == "handled"
    assert "Summary of resume.docx" in summary.message


def test_document_index_semantic_like_search_and_organization(tmp_path, monkeypatch):
    db = tmp_path / "docs.db"
    path = tmp_path / "invoice-may.csv"
    path.write_text("Invoice,Amount\nGrandpa Tools,55\n", encoding="utf-8")
    index = document_intelligence.DocumentIndex(db)
    index.upsert(document_intelligence.document_metadata(path))

    found = index.search("invoice")
    assert found
    monkeypatch.setattr(document_intelligence, "DocumentIndex", lambda: index)
    plan = document_intelligence.organization_plan("invoice", dry_run=True)
    assert plan.data["dry_run"] is True
    assert plan.data["moves"]


def test_office_productivity_helpers(tmp_path):
    csv_path = tmp_path / "expenses.csv"
    csv_path.write_text("Date,Amount\n2026-05-01,10\n2026-05-02,20\n", encoding="utf-8")

    analysis = office_productivity.analyze_spreadsheet(csv_path)
    assert analysis.status == "handled"
    assert analysis.data["numeric_stats"]["Amount"]["sum"] == 30
    assert office_productivity.suggest_formulas(["Date", "Amount"])
    assert office_productivity.create_presentation_outline("Grandpa").data["outline"]
    assert office_productivity.generate_report("Weekly Report", "Grandpa improved automation.").data["report"]
    assert office_productivity.review_resume("Python developer").data["suggestions"]
    assert office_productivity.draft_email("project update").data["draft"].startswith("Subject:")


def test_smart_automation_workflow_simulation(tmp_path):
    store = smart_automation.WorkflowStore(tmp_path / "workflows.db")
    created = smart_automation.create_workflow_from_text(
        "workflow called morning then open chrome then open vs code",
        store=store,
    )
    assert created.status == "handled"
    simulated = smart_automation.simulate_workflow(created.data["workflow"]["name"], store=store)
    assert simulated.status == "handled"
    assert simulated.data["dry_run"] is True
    assert smart_automation.diagnostics(store)["workflow_count"] == 1


def test_developer_safety_and_diagnostics():
    assert developer_assistant.classify_command("git status")["allowed"] is True
    assert developer_assistant.classify_command("git reset --hard")["risk"] == "BLOCKED"
    plan = developer_assistant.terminal_plan("python script.py")
    assert plan.status == "requires_confirmation"
    logs = developer_assistant.analyze_log_text("warning deprecated\nerror failed")
    assert logs.data["errors"]


def test_security_sensitive_memory_policy_and_redaction(tmp_path):
    store = security_safety.SecurityStore(tmp_path / "security.db")
    store.store_sensitive("api_key", "secret-value", "1234")
    assert store.load_sensitive("api_key", "1234") == "secret-value"
    assert security_safety.redact_sensitive({"api_key": "secret-value"})["api_key"] == "[redacted]"
    assert security_safety.suspicious_action_score("delete passwords")["suspicious"] is True
    assert security_safety.set_admin_pin("1234", store=store).status == "handled"
    assert security_safety.verify_admin_pin("1234", store=store)
    assert security_safety.diagnostics(store)["health"]["score"] >= 70


def test_completion_diagnostics_routes():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    assert client.get("/v1/file-intelligence/diagnostics").status_code == 200
    assert client.get("/v1/office/diagnostics").status_code == 200
    assert client.get("/v1/automation/diagnostics").status_code == 200
    assert client.get("/v1/developer/diagnostics").status_code == 200
    assert client.get("/v1/security/diagnostics").status_code == 200
    response = client.post("/v1/security/suspicious-action", json={"text": "shutdown computer"})
    assert response.json()["suspicious"] is True
