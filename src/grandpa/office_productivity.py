"""Office productivity helpers for local documents and communication drafts."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.document_intelligence import (
    extract_tables,
    smart_summary,
)


@dataclass(frozen=True)
class ProductivityResult:
    status: str
    message: str
    data: dict[str, Any]


TEMPLATES: dict[str, str] = {
    "report": "# Report\n\n## Summary\n\n## Key Findings\n\n## Recommendations\n",
    "meeting_notes": "# Meeting Notes\n\n## Attendees\n\n## Decisions\n\n## Action Items\n",
    "invoice_summary": "# Invoice Summary\n\n## Vendor\n\n## Amounts\n\n## Due Dates\n",
    "resume_review": "# Resume Review\n\n## Strengths\n\n## Gaps\n\n## Suggested Improvements\n",
    "email_draft": "Subject: \n\nHi,\n\n\n\nBest,\n",
}


def analyze_spreadsheet(path: Path | str) -> ProductivityResult:
    path = Path(path)
    tables = extract_tables(path)
    if not tables:
        return ProductivityResult("unsupported", f"I could not read spreadsheet data from {path.name}.", {"path": str(path)})
    first = tables[0]
    rows = first.get("rows", [])
    headers = rows[0] if rows else []
    numeric_columns: dict[int, list[float]] = {}
    for row in rows[1:]:
        for idx, value in enumerate(row):
            try:
                numeric_columns.setdefault(idx, []).append(float(str(value).replace(",", "")))
            except ValueError:
                continue
    stats = {
        str(headers[idx] if idx < len(headers) and headers[idx] else f"Column {idx + 1}"): {
            "count": len(values),
            "sum": round(sum(values), 2),
            "average": round(sum(values) / len(values), 2) if values else 0,
        }
        for idx, values in numeric_columns.items()
        if values
    }
    return ProductivityResult(
        "handled",
        f"Spreadsheet summary for {path.name}: {len(rows)} rows, {len(headers)} columns, {len(stats)} numeric column(s).",
        {"path": str(path), "rows": len(rows), "columns": len(headers), "numeric_stats": stats},
    )


def suggest_formulas(headers: list[str]) -> list[str]:
    formulas = []
    lower = [header.lower() for header in headers]
    for idx, header in enumerate(headers, start=1):
        if any(word in header.lower() for word in ("amount", "total", "price", "cost", "expense")):
            col = _excel_col(idx)
            formulas.append(f"=SUM({col}2:{col}1000)  // total {header}")
            formulas.append(f"=AVERAGE({col}2:{col}1000)  // average {header}")
    if "date" in " ".join(lower):
        formulas.append("=TEXT(A2,\"mmm yyyy\")  // month grouping helper")
    return formulas or ["=COUNTA(A:A)  // count populated rows"]


def create_presentation_outline(topic: str, *, slides: int = 6) -> ProductivityResult:
    topic = topic.strip() or "Grandpa Assistant"
    base = [
        ("Title", topic),
        ("Context", f"Why {topic} matters"),
        ("Current State", "What exists today"),
        ("Opportunities", "Where to improve"),
        ("Plan", "Next steps and owners"),
        ("Close", "Decision and follow-up"),
    ]
    outline = [{"slide": idx + 1, "title": title, "notes": notes} for idx, (title, notes) in enumerate(base[:slides])]
    return ProductivityResult("handled", f"Prepared a {len(outline)}-slide outline for {topic}.", {"outline": outline})


def generate_report(title: str, source_text: str = "") -> ProductivityResult:
    summary = smart_summary(source_text) if source_text else "Add source material to generate detailed findings."
    report = f"# {title.strip() or 'Report'}\n\n## Executive Summary\n{summary}\n\n## Recommendations\n- Review the source material.\n- Confirm facts before sharing.\n"
    return ProductivityResult("handled", "Prepared a local report draft.", {"report": report})


def summarize_meeting_notes(text: str) -> ProductivityResult:
    actions = re.findall(r"(?im)^(?:[-*]\s*)?(?:todo|action|follow up|next):?\s*(.+)$", text)
    summary = smart_summary(text)
    return ProductivityResult("handled", "Summarized meeting notes.", {"summary": summary, "action_items": actions[:20]})


def review_resume(text: str) -> ProductivityResult:
    lower = text.lower()
    suggestions = []
    for keyword in ("impact", "metrics", "projects", "skills", "experience"):
        if keyword not in lower:
            suggestions.append(f"Add clearer {keyword} evidence.")
    if not re.search(r"\d+%|\$\d+|\b\d+\+?\b", text):
        suggestions.append("Add measurable outcomes where possible.")
    return ProductivityResult("handled", "Prepared resume review suggestions.", {"suggestions": suggestions or ["Resume looks structurally complete."]})


def draft_email(purpose: str, tone: str = "professional") -> ProductivityResult:
    purpose = purpose.strip() or "follow up"
    body = f"Subject: {purpose.title()}\n\nHi,\n\nI wanted to follow up about {purpose}. Please let me know what works best.\n\nBest,\n"
    if tone == "friendly":
        body = body.replace("Hi,", "Hi there,")
    return ProductivityResult("handled", "Prepared an email draft.", {"draft": body, "tone": tone})


def export_plan(name: str, content_type: str) -> ProductivityResult:
    safe = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "grandpa-export"
    return ProductivityResult(
        "requires_confirmation",
        f"Export/download workflow prepared for {safe}.{content_type}; approval is required before writing files.",
        {"filename": f"{safe}.{content_type}", "approval_required": True},
    )


def diagnostics() -> dict[str, Any]:
    return {
        "status": "ready",
        "templates": sorted(TEMPLATES),
        "features": {
            "csv_xlsx_analysis": True,
            "formula_suggestions": True,
            "presentation_outlines": True,
            "report_generation": True,
            "meeting_notes": True,
            "resume_review": True,
            "email_drafts": True,
            "export_requires_approval": True,
        },
        "safety": {"local_only": True, "overwrites_require_approval": True, "cloud_upload": False},
    }


def _excel_col(index: int) -> str:
    label = ""
    while index:
        index, rem = divmod(index - 1, 26)
        label = chr(65 + rem) + label
    return label


def analyze_csv_text(text: str) -> ProductivityResult:
    rows = list(csv.reader(text.splitlines()))
    headers = rows[0] if rows else []
    return ProductivityResult(
        "handled",
        f"CSV summary: {len(rows)} rows, {len(headers)} columns.",
        {"rows": len(rows), "columns": len(headers), "formula_suggestions": suggest_formulas(headers)},
    )


__all__ = [
    "ProductivityResult",
    "TEMPLATES",
    "analyze_csv_text",
    "analyze_spreadsheet",
    "create_presentation_outline",
    "diagnostics",
    "draft_email",
    "export_plan",
    "generate_report",
    "review_resume",
    "suggest_formulas",
    "summarize_meeting_notes",
]
