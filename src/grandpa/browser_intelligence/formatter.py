"""Formatting utilities for CLI, Chat, and Voice responses."""

from __future__ import annotations

from typing import Any

from grandpa.browser_intelligence.models import (
    ComparisonResult,
    ExtractedContent,
    ResearchReport,
    SourceVerificationResult,
)


def format_page_analysis_cli(analysis: dict[str, Any]) -> str:
    """Format page analysis for CLI output."""
    lines = [
        "🌐 **Page Analysis Summary**",
        f"- **Title**: {analysis.get('title')}",
        f"- **URL**: {analysis.get('url')}",
        f"- **Domain**: {analysis.get('domain')}",
        f"- **Headings**: {analysis.get('heading_count')}",
        f"- **Paragraphs**: {analysis.get('paragraph_count')}",
        f"- **Buttons**: {analysis.get('button_count')}",
        f"- **Forms**: {analysis.get('form_count')}",
        f"- **Tables**: {analysis.get('table_count')}",
        f"- **Code Blocks**: {analysis.get('code_block_count')}",
        f"- **Search Results**: {analysis.get('search_result_count')}",
    ]
    if analysis.get("search_results"):
        lines.append("\n**Top Search Results:**")
        for sr in analysis["search_results"][:5]:
            off = " [OFFICIAL]" if sr.get("is_official") else ""
            lines.append(
                f"  #{sr.get('ranking')} {sr.get('title')}{off} ({sr.get('domain')}) - Trust: {sr.get('trust_score')}"
            )
    return "\n".join(lines)


def format_extracted_content_cli(extracted: ExtractedContent) -> str:
    """Format extracted section for CLI output."""
    badge = {
        "success": "✅ SUCCESS",
        "partial_success": "⚠️ PARTIAL SUCCESS",
        "not_found": "🔍 NOT FOUND",
        "unavailable": "❌ UNAVAILABLE",
    }.get(extracted.status, extracted.status.upper())

    lines = [
        f"📑 **Extracted Section: {extracted.section_type.title()}**",
        f"- **Status**: {badge}",
        f"- **Message**: {extracted.message}",
        f"- **Source**: {extracted.topic_or_target}"
        + (f" ({extracted.source_domain})" if extracted.source_domain else ""),
    ]
    if extracted.source_url:
        lines.append(f"- **URL**: {extracted.source_url}")
    lines.extend(["", "**Content:**", extracted.text])

    if extracted.code_snippets:
        lines.append("\n**Code Snippets:**")
        for cb in extracted.code_snippets:
            lines.append(f"```{cb.language}\n{cb.code}\n```")
    return "\n".join(lines)


def format_verification_cli(verification: SourceVerificationResult) -> str:
    """Format verification result for CLI output."""
    badge = "✅ OFFICIAL" if verification.is_official else "ℹ️ COMMUNITY/THIRD-PARTY"
    return "\n".join(
        [
            "🔍 **Source Verification**",
            f"- **URL**: {verification.url}",
            f"- **Domain**: {verification.domain}",
            f"- **Status**: {badge}",
            f"- **Confidence**: {verification.confidence}",
            f"- **Trust Score**: {verification.trust_score}",
            f"- **Official Score**: {verification.official_score}",
            f"- **Reasoning**: {verification.reasoning}",
        ]
    )


def format_comparison_cli(comparison: ComparisonResult) -> str:
    """Format product comparison for CLI output."""
    lines = [
        f"⚖️ **Comparison: {comparison.item_a} vs {comparison.item_b}**",
        "",
        "| Feature | " + comparison.item_a + " | " + comparison.item_b + " |",
        "| --- | --- | --- |",
    ]
    for feat, values in comparison.attributes.items():
        val_a = values.get(comparison.item_a, "N/A")
        val_b = values.get(comparison.item_b, "N/A")
        lines.append(f"| **{feat}** | {val_a} | {val_b} |")

    lines.extend(
        [
            "",
            f"**Pros of {comparison.item_a}:** " + ", ".join(comparison.pros_a),
            f"**Cons of {comparison.item_a}:** " + ", ".join(comparison.cons_a),
            f"**Pros of {comparison.item_b}:** " + ", ".join(comparison.pros_b),
            f"**Cons of {comparison.item_b}:** " + ", ".join(comparison.cons_b),
            "",
            f"**Summary:** {comparison.summary}",
        ]
    )
    return "\n".join(lines)


def format_research_report_cli(report: ResearchReport) -> str:
    """Format web research report for CLI output."""
    lines = [
        f"🔬 **Web Research Report: {report.topic}**",
        f"- **Sources Visited**: {len(report.sources_visited)}",
        f"- **Verified Sources**: {len(report.verified_sources)}",
        "",
        "**Executive Summary:**",
        report.summary,
        "",
        "**Key Findings:**",
    ]
    for kf in report.key_findings:
        lines.append(f"- {kf}")

    lines.append("\n**Sources:**")
    for vs in report.verified_sources:
        off = " [Official]" if vs.is_official else ""
        lines.append(f"- {vs.domain}{off} (Confidence: {vs.confidence}) - {vs.url}")

    return "\n".join(lines)


def format_voice_summary(text: str, max_sentences: int = 2) -> str:
    """Format text into concise spoken text for voice output."""
    clean = text.replace("\n", " ").strip()
    sentences = [s.strip() for s in clean.split(".") if s.strip()]
    if not sentences:
        return "I have examined the page."
    spoken = ". ".join(sentences[:max_sentences])
    if not spoken.endswith("."):
        spoken += "."
    return spoken
