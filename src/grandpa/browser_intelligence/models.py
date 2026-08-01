"""Data models for Browser Intelligence V1 in Grandpa."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

ConfidenceLevel = Literal["High", "Medium", "Low"]
SearchEngineType = Literal["google", "bing", "duckduckgo", "brave", "unknown"]
SummaryType = Literal[
    "short",
    "detailed",
    "bullet",
    "technical",
    "installation",
    "requirements",
    "research",
]


@dataclass(frozen=True)
class HeadingItem:
    level: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "text": self.text}


@dataclass(frozen=True)
class TableItem:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    caption: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "caption": self.caption,
            "headers": list(self.headers),
            "rows": [list(row) for row in self.rows],
        }


@dataclass(frozen=True)
class CodeBlockItem:
    language: str
    code: str
    context_heading: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "code": self.code,
            "context_heading": self.context_heading,
        }


@dataclass(frozen=True)
class FormItem:
    name: str
    action: str
    method: str
    inputs: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "action": self.action,
            "method": self.method,
            "inputs": [dict(inp) for inp in self.inputs],
        }


@dataclass(frozen=True)
class NavItem:
    text: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "url": self.url}


@dataclass(frozen=True)
class SearchEngineResult:
    title: str
    url: str
    snippet: str
    domain: str
    ranking: int
    engine: SearchEngineType = "unknown"
    trust_score: float = 0.5
    official_score: float = 0.0
    confidence: ConfidenceLevel = "Medium"
    is_official: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "domain": self.domain,
            "ranking": self.ranking,
            "engine": self.engine,
            "trust_score": round(self.trust_score, 2),
            "official_score": round(self.official_score, 2),
            "confidence": self.confidence,
            "is_official": self.is_official,
        }


@dataclass(frozen=True)
class PageContent:
    title: str
    url: str
    domain: str
    headings: tuple[HeadingItem, ...] = field(default_factory=tuple)
    paragraphs: tuple[str, ...] = field(default_factory=tuple)
    buttons: tuple[str, ...] = field(default_factory=tuple)
    forms: tuple[FormItem, ...] = field(default_factory=tuple)
    nav_sections: tuple[NavItem, ...] = field(default_factory=tuple)
    tables: tuple[TableItem, ...] = field(default_factory=tuple)
    lists: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    code_blocks: tuple[CodeBlockItem, ...] = field(default_factory=tuple)
    search_results: tuple[SearchEngineResult, ...] = field(default_factory=tuple)
    visible_text: str = ""
    acquisition_source: str = "unavailable"
    confidence: str = "Low"
    status: str = "unavailable"
    elements: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "domain": self.domain,
            "headings": [h.to_dict() for h in self.headings],
            "paragraphs": list(self.paragraphs),
            "buttons": list(self.buttons),
            "forms": [f.to_dict() for f in self.forms],
            "nav_sections": [n.to_dict() for n in self.nav_sections],
            "tables": [t.to_dict() for t in self.tables],
            "lists": [list(lst) for lst in self.lists],
            "code_blocks": [cb.to_dict() for cb in self.code_blocks],
            "search_results": [sr.to_dict() for sr in self.search_results],
            "visible_text": self.visible_text,
            "acquisition_source": self.acquisition_source,
            "confidence": self.confidence,
            "status": self.status,
            "elements": [dict(el) for el in self.elements],
        }


@dataclass(frozen=True)
class SourceVerificationResult:
    url: str
    domain: str
    is_official: bool
    trust_score: float
    official_score: float
    confidence: ConfidenceLevel
    reasoning: str
    target_subject: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "domain": self.domain,
            "is_official": self.is_official,
            "trust_score": round(self.trust_score, 2),
            "official_score": round(self.official_score, 2),
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "target_subject": self.target_subject,
        }


@dataclass(frozen=True)
class ExtractedContent:
    topic_or_target: str
    section_type: str
    text: str
    key_points: tuple[str, ...] = field(default_factory=tuple)
    code_snippets: tuple[CodeBlockItem, ...] = field(default_factory=tuple)
    tables: tuple[TableItem, ...] = field(default_factory=tuple)
    source_url: str = ""
    source_domain: str = ""
    status: str = "success"
    message: str = "Extraction completed successfully."

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_or_target": self.topic_or_target,
            "section_type": self.section_type,
            "text": self.text,
            "key_points": list(self.key_points),
            "code_snippets": [cb.to_dict() for cb in self.code_snippets],
            "tables": [t.to_dict() for t in self.tables],
            "source_url": self.source_url,
            "source_domain": self.source_domain,
        }


@dataclass(frozen=True)
class ComparisonResult:
    item_a: str
    item_b: str
    attributes: dict[str, dict[str, str]] = field(default_factory=dict)
    pros_a: tuple[str, ...] = field(default_factory=tuple)
    cons_a: tuple[str, ...] = field(default_factory=tuple)
    pros_b: tuple[str, ...] = field(default_factory=tuple)
    cons_b: tuple[str, ...] = field(default_factory=tuple)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_a": self.item_a,
            "item_b": self.item_b,
            "attributes": self.attributes,
            "pros_a": list(self.pros_a),
            "cons_a": list(self.cons_a),
            "pros_b": list(self.pros_b),
            "cons_b": list(self.cons_b),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class ResearchReport:
    topic: str
    summary: str
    sources_visited: tuple[str, ...]
    verified_sources: tuple[SourceVerificationResult, ...]
    key_findings: tuple[str, ...]
    extracted_sections: tuple[ExtractedContent, ...]
    bounded_reached: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "summary": self.summary,
            "sources_visited": list(self.sources_visited),
            "verified_sources": [vs.to_dict() for vs in self.verified_sources],
            "key_findings": list(self.key_findings),
            "extracted_sections": [es.to_dict() for es in self.extracted_sections],
            "bounded_reached": self.bounded_reached,
            "timestamp": self.timestamp,
        }


@dataclass
class BrowserSessionState:
    visited_pages: list[dict[str, Any]] = field(default_factory=list)
    verified_pages: list[dict[str, Any]] = field(default_factory=list)
    last_active_tab: dict[str, Any] | None = None
    last_extracted_section: ExtractedContent | None = None
    navigation_history: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "visited_pages": self.visited_pages,
            "verified_pages": self.verified_pages,
            "last_active_tab": self.last_active_tab,
            "last_extracted_section": self.last_extracted_section.to_dict()
            if self.last_extracted_section
            else None,
            "navigation_history": self.navigation_history,
        }
