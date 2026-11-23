"""``grandpa mcp``: external MCP servers listed in ``~/.grandpa/mcp.toml``.

``list`` shows each server and its tools (which are allowed), ``test`` starts
one server, checks the handshake and stops it, ``call`` runs one allowed tool
through the action layer (it always asks first), and ``off`` / ``on`` is the
kill switch.
"""

from __future__ import annotations

import json
from typing import Any

import click

from grandpa.cli._tty import confirm_destructive


@click.group()
def mcp() -> None:
    """External MCP servers: list, test, call, and the off switch."""


def _print_problems(settings: Any) -> None:
    for problem in settings.problems:
        click.echo(f"  ! {problem}", err=True)


@mcp.command("list")
@click.option("--no-start", is_flag=True, help="Do not start servers to list tools.")
def list_cmd(no_start: bool) -> None:
    """Show configured servers and which of their tools Grandpa may use."""
    from grandpa.mcp.servers import get_hub, is_off, load_settings

    settings = load_settings()
    click.echo(f"MCP config: {settings.path}")
    _print_problems(settings)
    why = is_off(settings)
    click.echo(f"MCP: {'OFF - ' + why if why else 'on'}")
    if not settings.servers:
        click.echo("No servers configured. See docs/getting-started/mcp.md.")
        return
    for row in get_hub().status(connect=not no_start):
        allow = ", ".join(row["allow"]) or "nothing (add an allow list)"
        click.echo(f"\n{row['name']}: {row['state']}")
        click.echo(f"  command: {row['command']}")
        click.echo(f"  allow:   {allow}   timeout: {row['timeout']:g} s")
        for tool in row["tools"]:
            mark = "allowed" if tool["allowed"] else "blocked"
            click.echo(f"  [{mark}] {tool['action']}  {tool['description']}")


@mcp.command("test")
@click.argument("server")
def test_cmd(server: str) -> None:
    """Start SERVER, do the MCP handshake, list its tools, and stop it."""
    from grandpa.mcp.servers import get_hub, is_off, load_settings

    settings = load_settings()
    _print_problems(settings)
    why = is_off(settings)
    if why:
        raise click.ClickException(f"MCP is off ({why}). Run 'grandpa mcp on' first.")
    try:
        report = get_hub().test(server)
    except KeyError as exc:
        raise click.ClickException(str(exc.args[0])) from exc
    except Exception as exc:  # noqa: BLE001 - shown to the user
        raise click.ClickException(f"{server} did not start: {exc}") from exc
    click.echo(
        f"{server}: OK, answered in {report['seconds']:g} s, "
        f"{len(report['tools'])} tool(s), {len(report['allowed'])} allowed"
    )
    for tool in report["tools"]:
        mark = "allowed" if tool in report["allowed"] else "blocked"
        click.echo(f"  [{mark}] {tool}")
    for name in report["unknown_in_allow"]:
        click.echo(f"  ! allow list names {name!r}, which this server does not have")


def _parse_args(values: tuple[str, ...]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for item in values:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise click.BadParameter(f"{item!r} is not NAME=VALUE", param_hint="--arg")
        try:
            parsed[key.strip()] = json.loads(value)
        except ValueError:
            parsed[key.strip()] = value
    return parsed


def _terminal_confirm(action: str, parameters: Any, risk: Any) -> bool:
    shown = ", ".join(f"{k}={v!r}" for k, v in dict(parameters).items())
    answer = confirm_destructive(f"Run {action}({shown}) [{risk}]? [y/N]")
    if answer is None:
        click.echo("Nobody can answer here, so nothing was run.")
    return answer is True


@mcp.command("call")
@click.argument("action")
@click.option("--arg", "args", multiple=True, help="A tool argument: NAME=VALUE.")
def call_cmd(action: str, args: tuple[str, ...]) -> None:
    """Run ACTION (mcp__<server>__<tool>) once. It always asks first."""
    from grandpa.action_layer.catalogue import get
    from grandpa.action_layer.executor import execute
    from grandpa.action_layer.model import ActionRequest, Origin

    try:
        spec = get(action)
    except KeyError as exc:
        raise click.ClickException(
            f"{action} is not available: {exc.args[0] if exc.args else action}"
        ) from exc
    request = ActionRequest(
        action=spec.name,
        parameters=_parse_args(args),
        origin=Origin.USER_CLI,
        risk=spec.risk,
        requires_confirmation=True,
    )
    result = execute(request, confirm_callback=_terminal_confirm)
    click.echo(result.message)
    if not result.success:
        raise SystemExit(1)


@mcp.command("off")
def off_cmd() -> None:
    """Kill switch: every MCP tool stops working until 'grandpa mcp on'."""
    from grandpa.mcp.servers import kill_switch_path, set_off

    set_off(True)
    click.echo(f"MCP is OFF ({kill_switch_path()}). 'grandpa mcp on' undoes it.")


@mcp.command("on")
def on_cmd() -> None:
    """Remove the 'grandpa mcp off' switch."""
    from grandpa.mcp.servers import is_off, set_off

    set_off(False)
    why = is_off()
    click.echo(f"MCP is still off: {why}" if why else "MCP is on.")
