"""``grandpa plugin``: list, enable, disable and call plugins (G2).

``enable`` shows what the plugin is allowed to do and asks; nothing a plugin
offers works until then, and it stops working if its files change.
"""

from __future__ import annotations

import json
from typing import Any

import click

from grandpa.cli._tty import confirm_destructive


@click.group()
def plugin() -> None:
    """Plugins from plugins/<name>/plugin.toml: list, enable, disable, call."""


def _describe(info: Any) -> list[str]:
    from grandpa.plugins.host import tool_spec

    manifest = info.manifest
    lines = [f"  {manifest.description}"] if manifest.description else []
    lines.append(f"  permissions: {', '.join(manifest.permissions) or 'none'}")
    for tool in manifest.tools:
        spec = tool_spec(manifest, tool)
        asks = "asks first" if spec.requires_confirmation else "no question"
        lines.append(f"  tool {spec.name}  [{spec.risk}, {asks}]  {tool.description}")
    for hook in manifest.events:
        lines.append(f"  on {hook.on} -> {hook.handler}()")
    for option in manifest.config:
        lines.append(
            f"  config {option.name} = {option.default!r}  {option.description}"
        )
    return lines


@plugin.command("list")
def list_cmd() -> None:
    """Show every plugin found and whether it is enabled."""
    from grandpa.plugins.host import get_host, is_off

    host = get_host()
    click.echo(f"Plugin folders: {', '.join(str(d) for d in host.dirs)}")
    if is_off():
        click.echo("Plugins: OFF - GRANDPA_PLUGINS_OFF is set")
    found = host.discover()
    if not found:
        click.echo("No plugins found. See docs/getting-started/plugins.md.")
        return
    for info in found:
        version = f" {info.manifest.version}" if info.manifest else ""
        click.echo(f"\n{info.name}{version}: {info.state}  ({info.folder})")
        if info.problem:
            click.echo(f"  ! {info.problem}")
        if info.manifest is not None:
            for line in _describe(info):
                click.echo(line)


@plugin.command("enable")
@click.argument("name")
def enable_cmd(name: str) -> None:
    """Show NAME's permissions, ask, and enable it (pins its files)."""
    from grandpa.plugins.host import get_host
    from grandpa.plugins.manifest import ManifestError

    host = get_host()
    try:
        info = host.find(name)
    except KeyError as exc:
        raise click.ClickException(str(exc.args[0])) from exc
    if info.state == "broken":
        raise click.ClickException(f"{name} cannot be enabled: {info.problem}")
    click.echo(f"{name} {info.manifest.version} from {info.folder}")
    for line in _describe(info):
        click.echo(line)
    click.echo("Its Python code runs inside Grandpa. Enable it only if you trust it.")
    answer = confirm_destructive(f"Enable plugin {name}? [y/N]")
    if answer is None:
        raise click.ClickException("Nobody can answer here, so nothing was enabled.")
    if not answer:
        click.echo("Not enabled.")
        return
    try:
        host.enable(name)
    except (KeyError, ManifestError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{name} is enabled. If its files change, enable it again.")


@plugin.command("disable")
@click.argument("name")
def disable_cmd(name: str) -> None:
    """Disable NAME. Its tools and event handlers stop at once."""
    from grandpa.plugins.host import get_host

    host = get_host()
    removed = host.disable(name)
    host.stop_events()
    click.echo(f"{name} is disabled." if removed else f"{name} was not enabled.")


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


@plugin.command("call")
@click.argument("action")
@click.option("--arg", "args", multiple=True, help="A tool argument: NAME=VALUE.")
def call_cmd(action: str, args: tuple[str, ...]) -> None:
    """Run ACTION (plugin__<plugin>__<tool>) once, through the normal checks."""
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
        requires_confirmation=spec.requires_confirmation,
    )
    result = execute(request, confirm_callback=_terminal_confirm)
    click.echo(result.message)
    if not result.success:
        raise SystemExit(1)
