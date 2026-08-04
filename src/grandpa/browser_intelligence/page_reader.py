"""Page reader for converting visible browser context or raw HTML into structured text."""

from __future__ import annotations

import html.parser
import re
from typing import Any

from grandpa.browser_control import BrowserContext, get_visible_browser_context
from grandpa.browser_intelligence.models import PageContent
from grandpa.browser_intelligence.source_verifier import extract_domain

# Prompt injection markers to sanitize from webpage text
_PROMPT_INJECTION_PATTERNS = (
    r"(?i)\bignore (?:all )?previous instructions\b",
    r"(?i)\bdisregard (?:all )?prior instructions\b",
    r"(?i)\bsystem prompt:\b",
    r"(?i)\byou are now an evil ai\b",
    r"(?i)\bnew instruction:\b",
    r"(?i)\bdo not tell the user\b",
    r"(?i)\bsecret key:\b",
    r"(?i)\bpassword:\b",
)


def sanitize_untrusted_text(text: str) -> str:
    """Sanitize webpage text against prompt injections and secret leaks."""
    if not text:
        return ""

    cleaned = text
    for pattern in _PROMPT_INJECTION_PATTERNS:
        cleaned = re.sub(pattern, "[UNTRUSTED_INSTRUCTION_REMOVED]", cleaned)

    return cleaned


class HTMLStructureParser(html.parser.HTMLParser):
    """Lightweight HTML parser to extract structured elements from raw HTML strings."""

    def __init__(self) -> None:
        super().__init__()
        self.title: str = ""
        self.in_title: bool = False
        self.headings: list[tuple[int, str]] = []
        self.current_heading_level: int = 0
        self.current_heading_text: list[str] = []
        self.paragraphs: list[str] = []
        self.in_p: bool = False
        self.current_p_text: list[str] = []
        self.buttons: list[str] = []
        self.in_button: bool = False
        self.current_button_text: list[str] = []
        self.code_blocks: list[tuple[str, str]] = []
        self.in_code: bool = False
        self.in_pre: bool = False
        self.current_code_text: list[str] = []
        self.links: list[tuple[str, str]] = []  # text, href
        self.in_a: bool = False
        self.current_a_href: str = ""
        self.current_a_text: list[str] = []
        self.forms: list[dict[str, Any]] = []
        self.in_form: bool = False
        self.current_form: dict[str, Any] = {}
        self.tables: list[tuple[list[str], list[list[str]]]] = []
        self.in_table: bool = False
        self.current_table_headers: list[str] = []
        self.current_table_rows: list[list[str]] = []
        self.current_row: list[str] = []
        self.in_th: bool = False
        self.in_td: bool = False
        self.current_cell_text: list[str] = []
        self.lists: list[list[str]] = []
        self.in_list: bool = False
        self.current_list: list[str] = []
        self.in_li: bool = False
        self.current_li_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k.lower(): (v or "") for k, v in attrs}

        if tag == "title":
            self.in_title = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.current_heading_level = int(tag[1])
            self.current_heading_text = []
        elif tag == "p":
            self.in_p = True
            self.current_p_text = []
        elif tag == "button":
            self.in_button = True
            self.current_button_text = []
        elif tag == "a":
            self.in_a = True
            self.current_a_href = attr_dict.get("href", "")
            self.current_a_text = []
        elif tag in ("pre", "code"):
            if tag == "pre":
                self.in_pre = True
                self.in_code = True
                self.current_code_text = []
            elif tag == "code":
                if not self.in_pre:
                    self.in_code = True
                    self.current_code_text = []
        elif tag == "form":
            self.in_form = True
            self.current_form = {
                "name": attr_dict.get("name", attr_dict.get("id", "form")),
                "action": attr_dict.get("action", ""),
                "method": attr_dict.get("method", "get"),
                "inputs": [],
            }
        elif tag == "input" and self.in_form:
            inp_type = attr_dict.get("type", "text")
            # Filter out sensitive inputs
            if inp_type.lower() not in ("password", "hidden"):
                self.current_form["inputs"].append(
                    {
                        "name": attr_dict.get("name", attr_dict.get("id", "input")),
                        "type": inp_type,
                        "placeholder": attr_dict.get("placeholder", ""),
                    }
                )
        elif tag == "table":
            self.in_table = True
            self.current_table_headers = []
            self.current_table_rows = []
        elif tag == "tr" and self.in_table:
            self.current_row = []
        elif tag == "th" and self.in_table:
            self.in_th = True
            self.current_cell_text = []
        elif tag == "td" and self.in_table:
            self.in_td = True
            self.current_cell_text = []
        elif tag in ("ul", "ol"):
            self.in_list = True
            self.current_list = []
        elif tag == "li" and self.in_list:
            self.in_li = True
            self.current_li_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = sanitize_untrusted_text(" ".join(self.current_heading_text).strip())
            if text:
                self.headings.append((self.current_heading_level, text))
            self.current_heading_level = 0
        elif tag == "p":
            self.in_p = False
            text = sanitize_untrusted_text(" ".join(self.current_p_text).strip())
            if text:
                self.paragraphs.append(text)
        elif tag == "button":
            self.in_button = False
            text = sanitize_untrusted_text(" ".join(self.current_button_text).strip())
            if text:
                self.buttons.append(text)
        elif tag == "a":
            self.in_a = False
            text = sanitize_untrusted_text(" ".join(self.current_a_text).strip())
            if text or self.current_a_href:
                self.links.append((text, self.current_a_href))
        elif tag == "code":
            if not self.in_pre:
                self.in_code = False
                text = sanitize_untrusted_text("".join(self.current_code_text).strip())
                if text:
                    self.code_blocks.append(("code", text))
        elif tag == "pre":
            self.in_pre = False
            self.in_code = False
            text = sanitize_untrusted_text("".join(self.current_code_text).strip())
            if text:
                self.code_blocks.append(("code", text))
        elif tag == "form":
            self.in_form = False
            if self.current_form:
                self.forms.append(self.current_form)
        elif tag == "th":
            self.in_th = False
            cell = sanitize_untrusted_text(" ".join(self.current_cell_text).strip())
            self.current_table_headers.append(cell)
        elif tag == "td":
            self.in_td = False
            cell = sanitize_untrusted_text(" ".join(self.current_cell_text).strip())
            self.current_row.append(cell)
        elif tag == "tr" and self.in_table:
            if self.current_row:
                self.current_table_rows.append(self.current_row)
        elif tag == "table":
            self.in_table = False
            if self.current_table_headers or self.current_table_rows:
                self.tables.append(
                    (list(self.current_table_headers), list(self.current_table_rows))
                )
        elif tag == "li" and self.in_list:
            self.in_li = False
            text = sanitize_untrusted_text(" ".join(self.current_li_text).strip())
            if text:
                self.current_list.append(text)
        elif tag in ("ul", "ol"):
            self.in_list = False
            if self.current_list:
                self.lists.append(list(self.current_list))

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        if self.current_heading_level > 0:
            self.current_heading_text.append(data)
        if self.in_p:
            self.current_p_text.append(data)
        if self.in_button:
            self.current_button_text.append(data)
        if self.in_a:
            self.current_a_text.append(data)
        if self.in_code:
            self.current_code_text.append(data)
        if self.in_th or self.in_td:
            self.current_cell_text.append(data)
        if self.in_li:
            self.current_li_text.append(data)


def read_current_browser_page(
    browser_context: BrowserContext | None = None,
    html_content: str | None = None,
) -> PageContent:
    """Read visible browser context or raw HTML content into standardized PageContent."""
    if browser_context is None and html_content is None:
        browser_context = get_visible_browser_context()

    if html_content:
        parser = HTMLStructureParser()
        try:
            parser.feed(html_content)
        except Exception:
            pass

        title = sanitize_untrusted_text(parser.title.strip() or "Untitled Page")
        url = "https://localhost/page"
        domain = extract_domain(url)

        from grandpa.browser_intelligence.models import (
            CodeBlockItem,
            FormItem,
            HeadingItem,
            NavItem,
            TableItem,
        )

        headings = tuple(HeadingItem(level=h[0], text=h[1]) for h in parser.headings)
        paragraphs = tuple(parser.paragraphs)
        buttons = tuple(parser.buttons)
        nav_sections = tuple(
            NavItem(text=link[0], url=link[1]) for link in parser.links[:15]
        )
        forms = tuple(
            FormItem(
                name=f.get("name", ""),
                action=f.get("action", ""),
                method=f.get("method", "get"),
                inputs=tuple(f.get("inputs", [])),
            )
            for f in parser.forms
        )
        tables = tuple(
            TableItem(headers=tuple(t[0]), rows=tuple(tuple(r) for r in t[1]))
            for t in parser.tables
        )
        lists = tuple(tuple(lst) for lst in parser.lists)
        code_blocks = tuple(
            CodeBlockItem(language=cb[0], code=cb[1]) for cb in parser.code_blocks
        )

        visible_text = sanitize_untrusted_text(
            "\n".join(
                [title]
                + [h.text for h in headings]
                + list(paragraphs)
                + [cb.code for cb in code_blocks]
            )
        )

        return PageContent(
            title=title,
            url=url,
            domain=domain,
            headings=headings,
            paragraphs=paragraphs,
            buttons=buttons,
            forms=forms,
            nav_sections=nav_sections,
            tables=tables,
            lists=lists,
            code_blocks=code_blocks,
            visible_text=visible_text,
        )

    # Use BrowserContext from Grandpa
    ctx = browser_context or get_visible_browser_context()
    if not ctx.supported:
        return PageContent(
            title="",
            url="",
            domain="",
            headings=(),
            paragraphs=(),
            buttons=(),
            forms=(),
            nav_sections=(),
            visible_text="",
        )

    title = sanitize_untrusted_text(ctx.title or "")
    url = ctx.url or ""
    domain = extract_domain(url)

    from grandpa.browser_intelligence.models import (
        FormItem,
        HeadingItem,
        NavItem,
    )

    headings = tuple(HeadingItem(level=2, text=h) for h in ctx.headings if h)
    buttons = tuple(b for b in ctx.buttons if b)
    nav_sections = tuple(
        NavItem(
            text=lk.get("text", lk.get("name", "")),
            url=lk.get("url", lk.get("href", "")),
        )
        for lk in ctx.links
    )
    forms = tuple(
        FormItem(
            name=f.get("name", "form"),
            action=f.get("action", ""),
            method=f.get("method", "get"),
            inputs=tuple(f.get("inputs", [])),
        )
        for f in ctx.forms
    )

    visible_text = sanitize_untrusted_text(ctx.visible_text or "")
    paragraphs = tuple([p.strip() for p in visible_text.split("\n\n") if p.strip()])

    from grandpa.browser_intelligence.models import CodeBlockItem

    code_blocks_list: list[CodeBlockItem] = []
    for el in ctx.elements:
        if (
            el.get("role") == "code_block"
            or "pip install" in str(el.get("text", "")).lower()
        ):
            code_blocks_list.append(
                CodeBlockItem(language="bash", code=str(el.get("text", "")))
            )

    return PageContent(
        title=title,
        url=url,
        domain=domain,
        headings=headings,
        paragraphs=paragraphs,
        buttons=buttons,
        forms=forms,
        nav_sections=nav_sections,
        code_blocks=tuple(code_blocks_list),
        visible_text=visible_text,
        acquisition_source=ctx.acquisition_source,
        confidence=ctx.confidence,
        status=ctx.status,
        elements=ctx.elements,
    )
