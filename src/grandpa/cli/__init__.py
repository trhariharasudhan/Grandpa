"""Command-line interface for Grandpa (Click-based)."""

from __future__ import annotations

import importlib
from collections.abc import Sequence

import click

import grandpa


class LazyCommand(click.Command):
    """Click command that imports its implementation only when invoked."""

    def __init__(
        self,
        name: str,
        import_path: str,
        *,
        short_help: str = "",
        optional_modules: Sequence[str] = (),
        install_hint: str = "",
    ) -> None:
        super().__init__(
            name=name,
            short_help=short_help,
            add_help_option=False,
            context_settings={
                "ignore_unknown_options": True,
                "allow_extra_args": True,
            },
        )
        self.import_path = import_path
        self.optional_modules = tuple(optional_modules)
        self.install_hint = install_hint

    def _load(self) -> click.Command:
        module_name, command_name = self.import_path.rsplit(":", 1)
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name in self.optional_modules:
                hint = self.install_hint or f"Install missing dependency: {exc.name}"
                raise click.ClickException(
                    f'The "{self.name}" command requires optional dependencies.\n'
                    f"{hint}\n"
                    "Then retry the command."
                ) from exc
            raise
        return getattr(module, command_name)

    def invoke(self, ctx: click.Context) -> object:
        command = self._load()
        return command.main(
            args=list(ctx.args),
            prog_name=ctx.info_name,
            standalone_mode=False,
            obj=ctx.obj,
        )


def _lazy(
    name: str,
    import_path: str,
    *,
    short_help: str = "",
    optional_modules: Sequence[str] = (),
    install_hint: str = "",
) -> LazyCommand:
    return LazyCommand(
        name,
        import_path,
        short_help=short_help,
        optional_modules=optional_modules,
        install_hint=install_hint,
    )


@click.group(
    name="grandpa",
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


cli.add_command(_lazy("init", "grandpa.cli.init_cmd:init", short_help="Initialize Grandpa."))
cli.add_command(_lazy("ask", "grandpa.cli.ask:ask", short_help="Ask Grandpa once."))
cli.add_command(_lazy("chat", "grandpa.cli.chat_cmd:chat", short_help="Start chat mode."))
cli.add_command(_lazy("apps", "grandpa.cli.apps_cmd:apps", short_help="Scan and query installed apps."))
cli.add_command(_lazy("projects", "grandpa.cli.projects_cmd:projects", short_help="Manage developer projects."))
cli.add_command(_lazy("project", "grandpa.cli.project_cmd:project_group", short_help="Autonomous development workflow V1."))
cli.add_command(_lazy("roadmap", "grandpa.cli.roadmap_cmd:roadmap_group", short_help="Manage project roadmaps and milestones."))
cli.add_command(_lazy("screen", "grandpa.cli.screen_cmd:screen", short_help="Inspect the screen read-only."))
cli.add_command(
    _lazy(
        "vision",
        "grandpa.cli.vision_cmd:vision",
        short_help="Inspect the visible UI element graph.",
    )
)
cli.add_command(
    _lazy(
        "automation",
        "grandpa.cli.automation_cmd:automation",
        short_help="Safely automate visible Windows controls.",
    )
)
cli.add_command(
    _lazy(
        "plan",
        "grandpa.cli.plan_cmd:plan",
        short_help="Create and run verified multi-step plans.",
    )
)
cli.add_command(_lazy("serve", "grandpa.cli.serve:serve", short_help="Run the API server."))
cli.add_command(_lazy("model", "grandpa.cli.model:model", short_help="Manage models."))
cli.add_command(_lazy("memory", "grandpa.cli.memory_cmd:memory", short_help="Manage memory."))
cli.add_command(_lazy("telemetry", "grandpa.cli.telemetry_cmd:telemetry", short_help="Telemetry controls."))
cli.add_command(_lazy("scheduler", "grandpa.cli.scheduler_cmd:scheduler", short_help="Scheduled tasks."))
cli.add_command(_lazy("reminders", "grandpa.cli.reminders_cmd:reminders", short_help="Local reminders."))
cli.add_command(_lazy("startup", "grandpa.cli.startup_cmd:startup", short_help="Windows startup integration."))
cli.add_command(_lazy("tray", "grandpa.cli.tray_cmd:tray", short_help="Windows system tray controller."))
cli.add_command(_lazy("doctor", "grandpa.cli.doctor_cmd:doctor", short_help="Check readiness."))
cli.add_command(_lazy("speak", "grandpa.cli.speak_cmd:speak", short_help="Speak text aloud."))
cli.add_command(_lazy("jarvis", "grandpa.cli.jarvis_cmd:jarvis", short_help="Route Jarvis-style safe local commands."))
cli.add_command(_lazy("voice-operator", "grandpa.cli.voice_operator_cmd:voice_operator", short_help="Start voice operator mode."))
cli.add_command(_lazy("voice", "grandpa.cli.voice_cmd:voice", short_help="Start voice assistant or run voice diagnostics."))
cli.add_command(_lazy("gmail", "grandpa.cli.gmail_cmd:gmail", short_help="Manage Gmail integration."))
cli.add_command(_lazy("calendar", "grandpa.cli.calendar_cmd:calendar", short_help="Manage Google Calendar integration."))
cli.add_command(_lazy("notes", "grandpa.cli.notes_cmd:notes", short_help="Manage local notes."))
cli.add_command(_lazy("downloads", "grandpa.cli.downloads_cmd:downloads", short_help="Inspect and organize Downloads."))
cli.add_command(_lazy("search", "grandpa.cli.search_cmd:search", short_help="Search the web."))
cli.add_command(_lazy("browser", "grandpa.cli.browser_cmd:browser", short_help="Browser intelligence & page understanding."))
cli.add_command(_lazy("agents", "grandpa.cli.agent_cmd:agent", short_help="Manage agents."))
cli.add_command(_lazy("agent", "grandpa.cli.agent_run_cmd:agent_group", short_help="Grandpa Agent Runtime V1."))
cli.add_command(_lazy("workflow", "grandpa.cli.workflow_cmd:workflow", short_help="Run workflows."))
cli.add_command(_lazy("skill", "grandpa.cli.skill_cmd:skill", short_help="Manage skills."))
cli.add_command(_lazy("sprint", "grandpa.cli.sprint_cmd:sprint_group", short_help="Autonomous Sprint Runner V1."))
cli.add_command(_lazy("start", "grandpa.cli.daemon_cmd:start", short_help="Start background services."))
cli.add_command(_lazy("stop", "grandpa.cli.daemon_cmd:stop", short_help="Stop background services."))
cli.add_command(_lazy("restart", "grandpa.cli.daemon_cmd:restart", short_help="Restart background services."))
cli.add_command(_lazy("status", "grandpa.cli.daemon_cmd:status", short_help="Show service status."))
cli.add_command(_lazy("vault", "grandpa.cli.vault_cmd:vault", short_help="Manage vault secrets."))
cli.add_command(_lazy("operators", "grandpa.cli.operators_cmd:operators", short_help="Manage operators."))
cli.add_command(_lazy("quickstart", "grandpa.cli.quickstart_cmd:quickstart", short_help="Run quickstart."))
cli.add_command(_lazy("tool", "grandpa.cli.tool_cmd:tool", short_help="Tool commands."))
cli.add_command(_lazy("registry", "grandpa.cli.registry_cmd:registry", short_help="Registry commands."))
cli.add_command(_lazy("config", "grandpa.cli.config_cmd:config", short_help="Manage config."))
cli.add_command(_lazy("scan", "grandpa.cli.scan_cmd:scan", short_help="Run privacy scans."))
cli.add_command(_lazy("self-update", "grandpa.cli.self_update_cmd:self_update", short_help="Check for updates."))
cli.add_command(_lazy("_bootstrap", "grandpa.cli._bootstrap:bootstrap_cmd", short_help="Bootstrap helper."))


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
