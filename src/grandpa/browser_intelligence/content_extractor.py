"""Targeted content extractor for sections like installation, requirements, pricing, specs, FAQs, and code snippets."""

from __future__ import annotations

from grandpa.browser_intelligence.models import (
    CodeBlockItem,
    ExtractedContent,
    PageContent,
    TableItem,
)
from grandpa.browser_intelligence.page_reader import sanitize_untrusted_text

SECTION_KEYWORDS = {
    "installation": (
        "installation",
        "install",
        "getting started",
        "setup",
        "quick start",
        "pip install",
    ),
    "requirements": (
        "requirements",
        "prerequisites",
        "dependencies",
        "system requirements",
        "compatibility",
    ),
    "pricing": ("pricing", "plans", "cost", "price", "billing", "free tier"),
    "specs": (
        "specifications",
        "specs",
        "technical specifications",
        "hardware",
        "features",
        "cpu",
        "ram",
    ),
    "faq": ("faq", "frequently asked questions", "q&a", "questions"),
    "documentation": ("documentation", "overview", "guide", "manual", "api reference"),
    "code": ("example", "code snippet", "usage", "quickstart", "code"),
}


def _normalize_heading(text: str) -> str:
    cleaned = text.replace("¶", "").replace("#", "").strip().lower()
    return cleaned.rstrip(". :")


def extract_section_content(
    page: PageContent,
    target_section: str = "installation",
) -> ExtractedContent:
    """Extract targeted section from page content based on target_section topic/type."""
    target_clean = _normalize_heading(target_section)

    if (
        not page.title
        and not page.domain
        and not page.visible_text
        and not page.paragraphs
        and not page.elements
    ):
        return ExtractedContent(
            topic_or_target="N/A",
            section_type=target_clean,
            text="No browser page content was available to extract.",
            status="unavailable",
            message="No browser page content was available to extract.",
            source_url=page.url,
            source_domain=page.domain,
        )

    keywords = SECTION_KEYWORDS.get(target_clean, (target_clean,))

    matched_headings: list[str] = []
    matched_paragraphs: list[str] = []
    matched_code: list[CodeBlockItem] = []
    matched_tables: list[TableItem] = []
    key_points: list[str] = []

    # 1. Ordered element traversal with Main Content vs Sidebar TOC scoring
    if page.elements:
        candidate_indices: list[tuple[int, int, int]] = []  # (score, idx, level)
        for idx, el in enumerate(page.elements):
            text = str(el.get("text", ""))
            norm_t = _normalize_heading(text)
            if any(kw in norm_t for kw in keywords) or norm_t in keywords:
                # Score candidate by checking following 4 elements
                score = 0
                has_body = False
                for f_idx in range(idx + 1, min(idx + 5, len(page.elements))):
                    fel = page.elements[f_idx]
                    frole = str(fel.get("role", "text"))
                    ftxt = str(fel.get("text", "")).strip()
                    if frole in ("paragraph", "code_block", "text") and len(ftxt) > 15:
                        has_body = True
                        score += 10
                    elif frole == "code_block" or "pip install" in ftxt.lower():
                        has_body = True
                        score += 15
                if not has_body:
                    score -= 10
                candidate_indices.append((score, idx, int(el.get("level") or 2)))

        if candidate_indices:
            # Sort candidates by score descending
            candidate_indices.sort(key=lambda c: c[0], reverse=True)
            _, match_idx, matched_level = candidate_indices[0]
            clean_h = (
                str(page.elements[match_idx].get("text", "")).replace("¶", "").strip()
            )
            matched_headings.append(clean_h)

        if match_idx != -1:
            for idx in range(match_idx + 1, len(page.elements)):
                el = page.elements[idx]
                role = str(el.get("role", "text"))
                text = (
                    sanitize_untrusted_text(str(el.get("text", "")))
                    .replace("¶", "")
                    .strip()
                )
                norm = _normalize_heading(text)

                if not text:
                    continue

                if role == "heading":
                    hlevel = int(el.get("level") or 2)
                    if hlevel <= matched_level or norm not in keywords:
                        break

                if any(h in text for h in matched_headings):
                    continue

                if (
                    role == "code_block"
                    or "pip install" in text.lower()
                    or "python" in text.lower()
                ):
                    if text not in [c.code for c in matched_code]:
                        matched_code.append(CodeBlockItem(language="bash", code=text))
                elif role in ("paragraph", "list_item", "text"):
                    if text not in matched_paragraphs and len(text) > 2:
                        matched_paragraphs.append(text)
                        if len(text) > 10 and text not in key_points:
                            key_points.append(
                                text[:120] + ("..." if len(text) > 120 else "")
                            )

    # 2. Fallback to headings / paragraphs if elements not populated or matched_paragraphs empty
    if not matched_paragraphs and not matched_code:
        for heading in page.headings:
            htext = _normalize_heading(heading.text)
            if any(kw in htext for kw in keywords) or htext in keywords:
                clean_h = heading.text.replace("¶", "").strip()
                if clean_h not in matched_headings:
                    matched_headings.append(clean_h)

        for p in page.paragraphs:
            clean_p = sanitize_untrusted_text(p).replace("¶", "").strip()
            plower = clean_p.lower()
            if not clean_p:
                continue
            if any(
                _normalize_heading(h) == _normalize_heading(clean_p)
                for h in matched_headings
            ):
                continue
            if any(kw in plower for kw in keywords) or matched_headings:
                if clean_p not in matched_paragraphs:
                    matched_paragraphs.append(clean_p)

        for cb in page.code_blocks:
            cb_code_clean = sanitize_untrusted_text(cb.code).strip()
            if cb_code_clean and cb_code_clean not in [c.code for c in matched_code]:
                matched_code.append(
                    CodeBlockItem(
                        language=cb.language,
                        code=cb_code_clean,
                        context_heading=cb.context_heading,
                    )
                )

    # Combine extracted text
    combined_text_parts = []
    if matched_headings:
        combined_text_parts.append(f"Section Headings: {', '.join(matched_headings)}")
    if matched_paragraphs:
        combined_text_parts.append("\n\n".join(matched_paragraphs))
    if matched_code:
        combined_text_parts.append(
            "Code Snippets:\n"
            + "\n\n".join([f"```\n{c.code}\n```" for c in matched_code])
        )

    extracted_text = "\n\n".join(combined_text_parts).strip()

    body_text_only = "\n\n".join(
        matched_paragraphs + [c.code for c in matched_code]
    ).strip()
    body_words = len(body_text_only.split())
    has_substantive_body = (
        body_words >= 5 or len(matched_code) > 0 or len(matched_paragraphs) > 0
    )

    if not matched_headings and not has_substantive_body:
        status = "not_found"
        message = f"Section '{target_clean}' was not found on the page."
        extracted_text = (
            f"Section '{target_clean}' was not found on {page.title or page.domain}."
        )
    elif matched_headings and not has_substantive_body:
        status = "partial_success"
        message = f"Found section heading '{', '.join(matched_headings)}', but no substantive body content was available."
    else:
        status = "success"
        message = "Extraction completed successfully."

    return ExtractedContent(
        topic_or_target=target_section,
        section_type=target_clean,
        text=extracted_text,
        key_points=tuple(key_points),
        code_snippets=tuple(matched_code),
        tables=tuple(matched_tables),
        status=status,
        message=message,
        source_url=page.url,
        source_domain=page.domain,
    )
