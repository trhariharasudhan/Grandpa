"""Command-line interface for Grandpa (Click-based)."""

from __future__ import annotations

import click

import grandpa
from grandpa.cli._bootstrap import bootstrap_cmd
from grandpa.cli.add_cmd import add
from grandpa.cli.agent_cmd import agent
from grandpa.cli.ask import ask
from grandpa.cli.bench_cmd import bench
from grandpa.cli.channel_cmd import channel
from grandpa.cli.channels_cmd import channels
from grandpa.cli.chat_cmd import chat
from grandpa.cli.compose_cmd import compose
from grandpa.cli.config_cmd import config
from grandpa.cli.connect_cmd import connect
from grandpa.cli.daemon_cmd import restart, start, status, stop
from grandpa.cli.deep_research_setup_cmd import deep_research_setup
from grandpa.cli.digest_cmd import digest
from grandpa.cli.doctor_cmd import doctor
from grandpa.cli.eval_cmd import eval_group
from grandpa.cli.feedback_cmd import feedback_group
from grandpa.cli.gateway_cmd import gateway
from grandpa.cli.host_cmd import host
from grandpa.cli.init_cmd import init
from grandpa.cli.memory_cmd import memory
from grandpa.cli.mine_cmd import mine
from grandpa.cli.model import model
from grandpa.cli.operators_cmd import operators
from grandpa.cli.optimize_cmd import optimize_group
from grandpa.cli.pearl_cmd import pearl
from grandpa.cli.quickstart_cmd import quickstart
from grandpa.cli.registry_cmd import registry
from grandpa.cli.reminders_cmd import reminders
from grandpa.cli.scan_cmd import scan
from grandpa.cli.scheduler_cmd import scheduler
from grandpa.cli.self_update_cmd import self_update
from grandpa.cli.serve import serve
from grandpa.cli.skill_cmd import skill
from grandpa.cli.telemetry_cmd import telemetry
from grandpa.cli.tool_cmd import tool
from grandpa.cli.vault_cmd import vault
from grandpa.cli.workflow_cmd import workflow


@click.group(
    help="Grandpa — modular AI assistant backend",
    invoke_without_command=True,
)
@click.version_option(version=grandpa.__version__, prog_name="Grandpa")
@click.option("--verbose", is_flag=True, default=False, help="Enable debug logging")
@click.option("--quiet", is_flag=True, default=False, help="Suppress non-error output")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool) -> None:
    """Top-level CLI group."""
    from grandpa.cli.log_config import setup_logging

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    setup_logging(verbose=verbose, quiet=quiet)

    # Check for updates on interactive commands. The banner is noise in
    # demo recordings of ``Grandpa ask --research``, so skip it whenever
    # the research flag is in argv (cheap argv sniff — Click hasn't
    # parsed the subcommand's args yet at this point).
    import sys

    research_mode_active = "--research" in sys.argv
    if not quiet and ctx.invoked_subcommand and not research_mode_active:
        from grandpa.cli._version_check import check_for_updates

        check_for_updates(ctx.invoked_subcommand)

    # First-run guard — routes bare `Grandpa` to chat or init.
    if ctx.invoked_subcommand is None:
        from grandpa.cli._first_run import check_and_route

        check_and_route(ctx)


cli.add_command(init, "init")
cli.add_command(ask, "ask")
cli.add_command(chat, "chat")
cli.add_command(serve, "serve")
cli.add_command(model, "model")
cli.add_command(memory, "memory")
cli.add_command(mine, "mine")
cli.add_command(pearl, "pearl")
cli.add_command(telemetry, "telemetry")
cli.add_command(bench, "bench")
cli.add_command(channel, "channel")
cli.add_command(channels, "channels")
cli.add_command(scheduler, "scheduler")
cli.add_command(reminders, "reminders")
cli.add_command(doctor, "doctor")
cli.add_command(agent, "agents")
cli.add_command(workflow, "workflow")
cli.add_command(skill, "skill")
cli.add_command(start, "start")
cli.add_command(stop, "stop")
cli.add_command(restart, "restart")
cli.add_command(status, "status")
cli.add_command(vault, "vault")
cli.add_command(add, "add")
cli.add_command(operators, "operators")
cli.add_command(eval_group, "eval")
cli.add_command(host, "host")
cli.add_command(quickstart, "quickstart")
cli.add_command(optimize_group, "optimize")
cli.add_command(feedback_group, "feedback")
cli.add_command(compose, "compose")
cli.add_command(gateway, "gateway")
cli.add_command(tool, "tool")
cli.add_command(registry, "registry")
cli.add_command(config, "config")
cli.add_command(scan, "scan")
cli.add_command(connect, "connect")
cli.add_command(digest, "digest")
cli.add_command(deep_research_setup, "deep-research-setup")
cli.add_command(deep_research_setup, "research")
cli.add_command(self_update, "self-update")
cli.add_command(bootstrap_cmd, "_bootstrap")

# Gateway CLI commands (lazy import to avoid pulling starlette)
try:
    from grandpa.cli.auth_cmd import auth

    cli.add_command(auth, "auth")
except ImportError:
    pass

try:
    from grandpa.cli.tunnel_cmd import tunnel

    cli.add_command(tunnel, "tunnel")
except ImportError:
    pass


def main() -> None:
    """Entry point registered as ``Grandpa`` console script."""
    import sys

    if sys.platform == "win32":
        for _stream in (sys.stdout, sys.stderr):
            if hasattr(_stream, "reconfigure"):
                try:
                    _stream.reconfigure(encoding="utf-8", errors="replace")
                except (AttributeError, OSError):
                    pass
    cli()


__all__ = ["cli", "main"]
