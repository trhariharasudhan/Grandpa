"""High-level read-first Grandpa Vision Engine."""

from __future__ import annotations

import re
from collections import Counter

from grandpa.screen.analyzer import detect_visible_error
from grandpa.screen.errors import SensitiveScreenDetectedError
from grandpa.screen.redaction import is_sensitive_screen, redact_screen_text
from grandpa.vision.extractor import VisionExtractor
from grandpa.vision.matcher import HybridElementMatcher
from grandpa.vision.models import ElementGraph, VisionNode, VisionResult

SENSITIVE_VISION_MESSAGE = (
    "This screen may contain passwords, payment details, or authentication data. "
    "Grandpa did not expose or store its visible text."
)


class VisionEngine:
    """Build and query one local screen graph at a time."""

    def __init__(
        self,
        *,
        extractor: VisionExtractor | None = None,
        matcher: HybridElementMatcher | None = None,
        max_text_chars: int = 6000,
    ) -> None:
        self.extractor = extractor or VisionExtractor()
        self.matcher = matcher or HybridElementMatcher()
        self.max_text_chars = max(200, max_text_chars)

    def inspect(self, **capture_options) -> VisionResult:
        graph, _screenshot = self.extractor.inspect(**capture_options)
        self._assert_safe(graph)
        counts = Counter(item.type for item in graph.nodes if item.visible)
        title = graph.capture.window_title or "Unknown window"
        message = (
            f"Current window: {title}\n"
            f"Capture: {graph.capture.width} x {graph.capture.height} "
            f"({graph.capture.source}, {graph.capture.backend})\n"
            f"Elements: {len(graph.nodes)} "
            f"(UIA={'ready' if graph.uia_available else 'unavailable'}, "
            f"OCR={'ready' if graph.ocr_available else 'unavailable'})"
        )
        return VisionResult(
            "handled",
            message,
            graph,
            data={"control_counts": dict(sorted(counts.items()))},
        )

    def find(
        self,
        query: str,
        *,
        limit: int = 10,
        actionable: bool = False,
        graph: ElementGraph | None = None,
    ) -> VisionResult:
        graph = graph or self.inspect().graph
        if graph is None:
            return VisionResult("unsupported", "Vision graph is unavailable.")
        matches = self.matcher.search(
            graph, query, limit=limit, actionable=actionable
        )
        if not matches:
            return VisionResult(
                "not_found",
                f'I could not find "{query}" in the visible window.',
                graph,
            )
        lines = [
            (
                f"{index}. {match.node.label or match.node.type} "
                f"at {match.node.bounds.center} ({match.confidence:.0%})"
            )
            for index, match in enumerate(matches, 1)
        ]
        return VisionResult(
            "handled",
            f'Found {len(matches)} match(es) for "{query}":\n' + "\n".join(lines),
            graph,
            matches,
        )

    def describe(self) -> VisionResult:
        result = self.inspect()
        graph = result.graph
        if graph is None:
            return result
        controls = [
            item
            for item in graph.nodes
            if item.visible and item.type not in {"text", "text_line", "paragraph"}
        ]
        buttons = [item.label for item in controls if item.type == "button" and item.label]
        fields = [item.label or item.type for item in controls if item.editable]
        dialogs = [
            item.label
            for item in controls
            if item.type == "window" and item.parent is not None and item.label
        ]
        text = self._visible_text(graph)
        error = detect_visible_error(text)
        parts = [f"The current window is {graph.capture.window_title or 'unknown'}."]
        if buttons:
            parts.append("Visible buttons include " + ", ".join(buttons[:8]) + ".")
        if fields:
            parts.append(f"I found {len(fields)} editable field(s).")
        if dialogs:
            parts.append("A dialog may be open: " + ", ".join(dialogs[:3]) + ".")
        if error.error_detected:
            parts.append(f"A likely error is visible: {error.headline}")
        elif text:
            parts.append("Visible text includes: " + " ".join(text.split())[:500])
        loading = self._loading_nodes(graph)
        if loading:
            parts.append("The window appears to be loading.")
        return VisionResult(
            "handled",
            "\n\n".join(parts),
            graph,
            data={
                "buttons": len(buttons),
                "editable_fields": len(fields),
                "dialog_detected": bool(dialogs),
                "loading": bool(loading),
                "error_detected": error.error_detected,
            },
        )

    def read(self) -> VisionResult:
        result = self.inspect()
        graph = result.graph
        if graph is None:
            return result
        text = self._visible_text(graph)
        return VisionResult(
            "handled",
            f"Visible text:\n{text}" if text else "No readable visible text was found.",
            graph,
            data={"character_count": len(text)},
        )

    def list_elements(self, *types: str) -> VisionResult:
        result = self.inspect()
        graph = result.graph
        if graph is None:
            return result
        wanted = {item.casefold() for item in types}
        nodes = [
            item
            for item in graph.nodes
            if item.visible
            and item.type.casefold() in wanted
            and (item.label or item.type)
        ]
        lines = [
            f"{index}. {item.label or item.type} ({item.type})"
            for index, item in enumerate(nodes[:100], 1)
        ]
        label = ", ".join(types) or "controls"
        return VisionResult(
            "handled",
            f"Visible {label}:\n" + ("\n".join(lines) if lines else "None found."),
            graph,
            data={"nodes": [item.to_dict() for item in nodes[:100]]},
        )

    def focused(self) -> VisionNode | None:
        graph = self.inspect().graph
        if graph is None:
            return None
        return graph.node(graph.active_node_id) if graph.active_node_id else None

    def selected(self) -> tuple[VisionNode, ...]:
        graph = self.inspect().graph
        if graph is None:
            return ()
        return tuple(item for item in graph.nodes if item.visible and item.selected)

    def _visible_text(self, graph: ElementGraph) -> str:
        lines = [
            item.text.strip()
            for item in graph.nodes
            if item.visible and item.type == "text_line" and item.text.strip()
        ]
        if not lines:
            lines = [
                item.label
                for item in graph.nodes
                if item.visible
                and item.label
                and item.type in {"text", "edit", "document", "status_bar"}
            ]
        deduplicated = list(dict.fromkeys(lines))
        return redact_screen_text("\n".join(deduplicated)).text[: self.max_text_chars]

    def _assert_safe(self, graph: ElementGraph) -> None:
        sample = "\n".join(
            item.label for item in graph.nodes if item.visible and item.label
        )[: self.max_text_chars]
        if is_sensitive_screen(title=graph.capture.window_title, text=sample):
            raise SensitiveScreenDetectedError(SENSITIVE_VISION_MESSAGE)

    @staticmethod
    def _loading_nodes(graph: ElementGraph) -> tuple[VisionNode, ...]:
        pattern = re.compile(r"\b(loading|please wait|working|progress)\b", re.I)
        return tuple(
            item
            for item in graph.nodes
            if item.visible
            and (item.type == "progress_bar" or pattern.search(item.label))
        )


__all__ = ["SENSITIVE_VISION_MESSAGE", "VisionEngine"]
