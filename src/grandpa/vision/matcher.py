"""Confidence-ranked hybrid element matching."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from grandpa.vision.models import ElementGraph, VisionMatch, VisionNode


class HybridElementMatcher:
    """Rank visible nodes without treating OCR alone as verified clickability."""

    def search(
        self,
        graph: ElementGraph,
        query: str,
        *,
        limit: int = 10,
        actionable: bool = False,
    ) -> tuple[VisionMatch, ...]:
        normalized = _normalize(query)
        if not normalized:
            return ()
        matches: list[VisionMatch] = []
        for node in graph.nodes:
            match = self._score(node, normalized, actionable=actionable)
            if match is not None:
                matches.append(match)
        matches.sort(
            key=lambda item: (
                -item.confidence,
                item.node.bounds.top,
                item.node.bounds.left,
            )
        )
        return tuple(matches[: max(1, limit)])

    def _score(
        self, node: VisionNode, query: str, *, actionable: bool
    ) -> VisionMatch | None:
        if not node.visible:
            return None
        candidate = _normalize(" ".join((node.name, node.text, node.value, node.type)))
        if not candidate:
            return None
        query_words = query.split()
        candidate_words = candidate.split()
        exact = candidate == query
        phrase = query in candidate
        all_words = all(word in candidate_words for word in query_words)
        fuzzy = SequenceMatcher(None, query, candidate).ratio()
        if not (exact or phrase or all_words or fuzzy >= 0.55):
            return None

        reasons: list[str] = []
        text_score = fuzzy
        if exact:
            text_score = 1.0
            reasons.append("exact text")
        elif phrase:
            text_score = max(text_score, 0.92)
            reasons.append("phrase match")
        elif all_words:
            text_score = max(text_score, 0.82)
            reasons.append("all query words")
        else:
            reasons.append("similar text")
        specificity = min(1.0, len(query_words) / max(1, len(candidate_words)))
        if not exact:
            text_score *= 0.65 + 0.35 * specificity
        if node.type in {"paragraph", "text_line"}:
            text_score *= 0.88

        source_score = (
            0.25 if node.source == "uia+ocr" else 0.18 if node.source == "uia" else 0.05
        )
        if node.source == "uia+ocr":
            reasons.append("OCR and UI Automation agree")
        elif node.source == "uia":
            reasons.append("UI Automation")
        else:
            reasons.append("OCR only")
        state_score = 0.08 if node.enabled else -0.2
        if node.clickable:
            state_score += 0.08
            reasons.append("clickable")
        confidence = min(
            1.0,
            text_score * 0.67 + source_score + state_score + node.confidence * 0.07,
        )
        if actionable and node.source == "ocr":
            confidence = min(confidence, 0.69)
        if actionable and (not node.enabled or not node.visible):
            return None
        return VisionMatch(node, round(max(0.0, confidence), 3), tuple(reasons))


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


__all__ = ["HybridElementMatcher"]
