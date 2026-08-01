"""Browser Intelligence V1 for Grandpa.

Provides structured page understanding, source verification, content extraction,
smart navigation, local summarization, comparison engine, bounded web research,
session memory, and formatters.
"""

from __future__ import annotations

from grandpa.browser_intelligence.comparison_engine import ProductComparisonEngine
from grandpa.browser_intelligence.content_extractor import extract_section_content
from grandpa.browser_intelligence.formatter import (
    format_comparison_cli,
    format_extracted_content_cli,
    format_page_analysis_cli,
    format_research_report_cli,
    format_verification_cli,
    format_voice_summary,
)
from grandpa.browser_intelligence.link_resolver import resolve_target_link
from grandpa.browser_intelligence.models import (
    CodeBlockItem,
    ComparisonResult,
    ExtractedContent,
    FormItem,
    HeadingItem,
    NavItem,
    PageContent,
    ResearchReport,
    SearchEngineResult,
    SourceVerificationResult,
    TableItem,
)
from grandpa.browser_intelligence.navigator import SmartNavigator
from grandpa.browser_intelligence.page_analyzer import (
    analyze_page_structure,
    extract_search_results_from_page,
)
from grandpa.browser_intelligence.page_reader import (
    read_current_browser_page,
    sanitize_untrusted_text,
)
from grandpa.browser_intelligence.research_mode import WebResearchEngine
from grandpa.browser_intelligence.session_memory import BrowserSessionMemory
from grandpa.browser_intelligence.source_verifier import (
    is_official_domain,
    rank_search_results,
    verify_source,
)
from grandpa.browser_intelligence.summarizer import (
    LocalPageSummarizer,
    heuristic_summarize,
)

__all__ = [
    "BrowserSessionMemory",
    "CodeBlockItem",
    "ComparisonResult",
    "ExtractedContent",
    "FormItem",
    "HeadingItem",
    "LocalPageSummarizer",
    "NavItem",
    "PageContent",
    "ProductComparisonEngine",
    "ResearchReport",
    "SearchEngineResult",
    "SmartNavigator",
    "SourceVerificationResult",
    "TableItem",
    "WebResearchEngine",
    "analyze_page_structure",
    "extract_search_results_from_page",
    "extract_section_content",
    "format_comparison_cli",
    "format_extracted_content_cli",
    "format_page_analysis_cli",
    "format_research_report_cli",
    "format_verification_cli",
    "format_voice_summary",
    "heuristic_summarize",
    "is_official_domain",
    "rank_search_results",
    "read_current_browser_page",
    "resolve_target_link",
    "sanitize_untrusted_text",
    "verify_source",
]
