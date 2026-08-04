"""CLI commands for Grandpa web search."""

from __future__ import annotations

import click

from grandpa.web_search import handle_web_search_command


@click.group(name="search")
def search() -> None:
    """Search the web through a configured provider."""


@search.command("web")
@click.argument("query", nargs=-1)
def web(query: tuple[str, ...]) -> None:
    click.echo(
        handle_web_search_command("search the web for " + " ".join(query)).message
    )


@search.command("news")
@click.argument("query", nargs=-1)
def news(query: tuple[str, ...]) -> None:
    click.echo(handle_web_search_command("search news for " + " ".join(query)).message)


@search.command("official")
@click.argument("query", nargs=-1)
def official(query: tuple[str, ...]) -> None:
    click.echo(
        handle_web_search_command("search official docs for " + " ".join(query)).message
    )


@search.command("recent")
@click.argument("query", nargs=-1)
def recent(query: tuple[str, ...]) -> None:
    click.echo(
        handle_web_search_command(
            "find recent articles from the last week about " + " ".join(query)
        ).message
    )


@search.command("status")
def status() -> None:
    click.echo(handle_web_search_command("web search status").message)


@search.command("clear-cache")
def clear_cache() -> None:
    click.echo(handle_web_search_command("clear web search cache").message)


__all__ = ["search"]
