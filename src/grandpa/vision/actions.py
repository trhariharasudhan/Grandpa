"""Guarded visual targeting actions backed by existing automation services."""

from __future__ import annotations

from grandpa.automation.locator import HighlightOverlay
from grandpa.automation.models import BoundingBox, LocatedElement
from grandpa.vision.models import VisionMatch, VisionResult
from grandpa.vision.service import VisionEngine


class VisualActionService:
    """Locate and highlight safely; prepare clicks through confirmation flow."""

    def __init__(
        self,
        *,
        engine: VisionEngine | None = None,
        highlighter: HighlightOverlay | None = None,
        automation_service=None,
        minimum_confidence: float = 0.78,
    ) -> None:
        self.engine = engine or VisionEngine()
        self.highlighter = highlighter or HighlightOverlay()
        self.automation_service = automation_service
        self.minimum_confidence = minimum_confidence

    def highlight(self, query: str) -> VisionResult:
        result = self.engine.find(query, limit=3, actionable=True)
        selected = self._select(result.matches, query)
        if isinstance(selected, VisionResult):
            return selected
        self.highlighter.show(_located(selected))
        return VisionResult(
            "handled",
            f'Highlighted "{selected.node.label}" ({selected.confidence:.0%} confidence).',
            result.graph,
            (selected,),
        )

    def prepare_click(self, query: str, *, double: bool = False, right: bool = False):
        result = self.engine.find(query, limit=3, actionable=True)
        selected = self._select(result.matches, query)
        if isinstance(selected, VisionResult):
            return selected
        if selected.node.source == "ocr":
            return VisionResult(
                "confirmation_required",
                (
                    f'I found "{selected.node.label}" using OCR only. '
                    "I will not click it without UI Automation verification."
                ),
                result.graph,
                (selected,),
            )
        service = self.automation_service
        if service is None:
            from grandpa.automation.service import get_automation_service

            service = get_automation_service()
        x, y = selected.node.bounds.center
        verb = "double click" if double else "right click" if right else "click"
        window = result.graph.capture.window_title if result.graph else None
        return service.handle(
            f"{verb} at {x} {y}",
            target_window=window or None,
        )

    def _select(
        self, matches: tuple[VisionMatch, ...], query: str
    ) -> VisionMatch | VisionResult:
        if not matches:
            return VisionResult("not_found", f'I could not find "{query}".')
        best = matches[0]
        if best.confidence < self.minimum_confidence:
            return VisionResult(
                "confirmation_required",
                (
                    f'I found a low-confidence match for "{query}" '
                    f"({best.confidence:.0%}). Please clarify the target."
                ),
                matches=(best,),
            )
        if (
            len(matches) > 1
            and matches[1].confidence >= self.minimum_confidence
            and best.confidence - matches[1].confidence < 0.06
        ):
            choices = ", ".join(
                f"{index}. {item.node.label}"
                for index, item in enumerate(matches[:4], 1)
            )
            return VisionResult(
                "ambiguous",
                f'I found multiple matches for "{query}": {choices}. Which one?',
                matches=matches,
            )
        return best


def _located(match: VisionMatch) -> LocatedElement:
    node = match.node
    return LocatedElement(
        text=node.label,
        role=node.type,
        confidence=match.confidence,
        bounds=BoundingBox(
            node.bounds.left,
            node.bounds.top,
            node.bounds.width,
            node.bounds.height,
        ),
        source=node.source,
    )


__all__ = ["VisualActionService"]
