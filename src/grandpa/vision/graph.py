"""Merge OCR and UI Automation into one element graph."""

from __future__ import annotations

import re
from dataclasses import replace

from grandpa.screen.models import OcrResult
from grandpa.screen.redaction import redact_screen_text
from grandpa.vision.models import (
    ElementGraph,
    VisionBounds,
    VisionCaptureMetadata,
    VisionNode,
)


class ElementGraphBuilder:
    """Build a deterministic graph while preserving source provenance."""

    def build(
        self,
        *,
        capture: VisionCaptureMetadata,
        ocr: OcrResult,
        uia_nodes: tuple[VisionNode, ...],
        warnings: tuple[str, ...] = (),
    ) -> ElementGraph:
        ocr_nodes = self._ocr_nodes(ocr, capture.region[:2])
        merged = list(uia_nodes)
        for ocr_node in ocr_nodes:
            match_index = _matching_uia_index(merged, ocr_node)
            if match_index is None:
                merged.append(ocr_node)
                continue
            uia = merged[match_index]
            text = uia.text or ocr_node.text
            confidence = max(uia.confidence, ocr_node.confidence)
            merged[match_index] = replace(
                uia,
                text=text,
                confidence=confidence,
                source="uia+ocr",
            )
        focused = next((item.id for item in merged if item.focused), None)
        return ElementGraph(
            nodes=tuple(merged),
            capture=capture,
            active_node_id=focused,
            ocr_available=ocr.available,
            uia_available=bool(uia_nodes),
            warnings=warnings,
        )

    def _ocr_nodes(
        self, ocr: OcrResult, offset: tuple[int, int]
    ) -> tuple[VisionNode, ...]:
        offset_x, offset_y = offset
        words: list[VisionNode] = []
        lines: dict[str, list[VisionNode]] = {}
        paragraphs: dict[str, list[VisionNode]] = {}
        for index, block in enumerate(ocr.blocks):
            safe_text = redact_screen_text(block.text).text
            if not safe_text.strip():
                continue
            left, top, width, height = block.bounds
            node = VisionNode(
                id=f"ocr:word:{index}",
                type="text",
                text=safe_text,
                confidence=max(0.0, min(1.0, block.confidence)),
                bounds=VisionBounds(left + offset_x, top + offset_y, width, height),
                parent=f"ocr:line:{block.line_id}" if block.line_id else None,
                source="ocr",
            )
            words.append(node)
            if block.line_id:
                lines.setdefault(block.line_id, []).append(node)
            if block.paragraph_id:
                paragraphs.setdefault(block.paragraph_id, []).append(node)

        group_nodes: list[VisionNode] = []
        for line_id, children in lines.items():
            paragraph_id = line_id.rsplit(":", 1)[0]
            group_nodes.append(
                VisionNode(
                    id=f"ocr:line:{line_id}",
                    type="text_line",
                    text=" ".join(item.text for item in children),
                    confidence=_average(item.confidence for item in children),
                    bounds=_union(item.bounds for item in children),
                    parent=f"ocr:paragraph:{paragraph_id}",
                    children=tuple(item.id for item in children),
                    source="ocr",
                )
            )
        for paragraph_id, children in paragraphs.items():
            child_ids = tuple(
                item.id
                for item in group_nodes
                if item.id.startswith(f"ocr:line:{paragraph_id}:")
            )
            group_nodes.append(
                VisionNode(
                    id=f"ocr:paragraph:{paragraph_id}",
                    type="paragraph",
                    text=" ".join(item.text for item in children),
                    confidence=_average(item.confidence for item in children),
                    bounds=_union(item.bounds for item in children),
                    children=child_ids,
                    source="ocr",
                )
            )
        return tuple(group_nodes + words)


def _matching_uia_index(nodes: list[VisionNode], ocr: VisionNode) -> int | None:
    wanted = _normalize(ocr.text)
    if not wanted:
        return None
    best: tuple[int, float] | None = None
    for index, node in enumerate(nodes):
        if not node.visible or node.source != "uia":
            continue
        overlap = node.bounds.intersection_over_union(ocr.bounds)
        label = _normalize(f"{node.name} {node.text} {node.value}")
        text_match = wanted in label or label in wanted if label else False
        if overlap < 0.15 or not text_match:
            continue
        score = overlap + (0.5 if text_match else 0)
        if best is None or score > best[1]:
            best = (index, score)
    return best[0] if best else None


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _union(bounds) -> VisionBounds:
    items = list(bounds)
    if not items:
        return VisionBounds(0, 0, 0, 0)
    left = min(item.left for item in items)
    top = min(item.top for item in items)
    right = max(item.right for item in items)
    bottom = max(item.bottom for item in items)
    return VisionBounds(left, top, right - left, bottom - top)


def _average(values) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


__all__ = ["ElementGraphBuilder"]
