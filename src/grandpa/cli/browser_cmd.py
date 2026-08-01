"""Click CLI interface for Grandpa Browser Intelligence."""

from __future__ import annotations

import click

from grandpa.browser_intelligence import (
    LocalPageSummarizer,
    ProductComparisonEngine,
    WebResearchEngine,
    analyze_page_structure,
    extract_section_content,
    format_comparison_cli,
    format_extracted_content_cli,
    format_page_analysis_cli,
    format_research_report_cli,
    format_verification_cli,
    read_current_browser_page,
    verify_source,
)
from grandpa.browser_intelligence.session_memory import BrowserSessionMemory


@click.group(name="browser", help="Grandpa Browser Intelligence commands.")
def browser() -> None:
    """Browser Intelligence CLI group."""


@browser.command(name="page", help="Read current browser page structure and title.")
def page_cmd() -> None:
    page = read_current_browser_page()
    click.echo(f"Page Title : {page.title or 'N/A'}")
    click.echo(f"URL        : {page.url or 'N/A'}")
    click.echo(f"Domain     : {page.domain or 'N/A'}")
    click.echo(f"Provider   : {page.acquisition_source}")
    click.echo(f"Confidence : {page.confidence}")
    click.echo(f"Status     : {page.status}")
    click.echo(f"Headings   : {len(page.headings)}")
    click.echo(f"Paragraphs : {len(page.paragraphs)}")


@browser.command(name="analyze", help="Analyze current browser page elements and search results.")
def analyze_cmd() -> None:
    page = read_current_browser_page()
    analysis = analyze_page_structure(page)
    click.echo(format_page_analysis_cli(analysis))


@browser.command(name="extract", help="Extract targeted section (installation, specs, code, etc.).")
@click.argument("section", default="installation")
def extract_cmd(section: str) -> None:
    page = read_current_browser_page()
    extracted = extract_section_content(page, target_section=section)
    click.echo(format_extracted_content_cli(extracted))


@browser.command(name="verify", help="Verify domain trust and official status for current page or URL.")
@click.argument("url", required=False)
@click.option("--subject", "-s", default="", help="Target subject/technology name.")
def verify_cmd(url: str | None, subject: str) -> None:
    target_url = url or ""
    target_subject = subject
    if not target_url:
        page = read_current_browser_page()
        target_url = page.url or ""
        if not target_subject:
            target_subject = page.title
    result = verify_source(target_url, subject=target_subject)
    click.echo(format_verification_cli(result))


@browser.command(name="summarize", help="Summarize current page using local model or heuristics.")
@click.option("--type", "-t", "summary_type", default="short", help="Summary type: short, detailed, bullet, technical, installation, requirements, research.")
def summarize_cmd(summary_type: str) -> None:
    page = read_current_browser_page()
    summarizer = LocalPageSummarizer()
    summary = summarizer.summarize_page(page, summary_type=summary_type)  # type: ignore[arg-type]
    click.echo(f"📝 [{summary_type.upper()} SUMMARY]\n")
    click.echo(summary)


@browser.command(name="compare", help="Compare two products, documentation, or specifications.")
@click.argument("item_a", default="Raspberry Pi 5")
@click.argument("item_b", default="Jetson Nano")
def compare_cmd(item_a: str, item_b: str) -> None:
    engine = ProductComparisonEngine()
    comparison = engine.compare_items(item_a, item_b)
    click.echo(format_comparison_cli(comparison))


@browser.command(name="research", help="Perform bounded multi-page web research on a topic.")
@click.argument("topic", default="FastAPI")
@click.option("--max-sources", default=5, help="Maximum search sources to inspect.")
@click.option("--max-pages", default=3, help="Maximum pages to read.")
def research_cmd(topic: str, max_sources: int, max_pages: int) -> None:
    engine = WebResearchEngine(max_sources=max_sources, max_pages=max_pages)
    report = engine.research_topic(topic)
    click.echo(format_research_report_cli(report))


@browser.command(name="history", help="Show in-memory session navigation history.")
def history_cmd() -> None:
    memory = BrowserSessionMemory.get_instance()
    ctx = memory.get_summary_context()
    visited = ctx.get("visited_pages", [])
    click.echo("📜 **Session Navigation History:**")
    if not visited:
        click.echo("  No visited pages recorded in this session.")
    for i, v in enumerate(visited, 1):
        click.echo(f"  {i}. {v.get('title')} ({v.get('url')})")


@browser.command(name="context", help="Show active browser session context.")
def context_cmd() -> None:
    memory = BrowserSessionMemory.get_instance()
    ctx = memory.get_summary_context()
    active = ctx.get("last_active_tab") or {}
    click.echo("🌐 **Browser Session Context:**")
    click.echo(f"  Active Tab : {active.get('title', 'None')}")
    click.echo(f"  Active URL : {active.get('url', 'None')}")
    click.echo(f"  Total Visited : {len(ctx.get('visited_pages', []))}")
    click.echo(f"  Total Verified: {len(ctx.get('verified_pages', []))}")


@browser.command(name="debug", help="Display Browser Intelligence diagnostics and provider state.")
def debug_cmd() -> None:
    page = read_current_browser_page()
    from grandpa.browser_control import get_visible_browser_context

    ctx = get_visible_browser_context()
    click.echo("🔍 **Browser Intelligence Diagnostics:**")
    click.echo(f"  Browser Detected  : {ctx.browser or 'None'}")
    click.echo(f"  Process Name      : {ctx.process_name or 'None'}")
    click.echo(f"  HWND              : {ctx.hwnd or 0}")
    click.echo(f"  URL               : {page.url or 'N/A'}")
    click.echo(f"  Provider          : {page.acquisition_source}")
    click.echo(f"  Confidence        : {page.confidence}")
    click.echo(f"  Content Source    : {page.acquisition_source}")
    click.echo(f"  Heading Count     : {len(page.headings)}")
    click.echo(f"  Paragraph Count   : {len(page.paragraphs)}")
    click.echo(f"  Cache State       : {'valid' if page.status != 'unavailable' else 'empty'}")
    click.echo(f"  Stale Context     : {'false' if page.status != 'unavailable' else 'true'}")
