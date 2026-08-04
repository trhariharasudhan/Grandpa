"""Interactive terminal session helpers for bare ``grandpa``."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rich.console import Console

import grandpa
from grandpa.cli.theme import (
    DEFAULT_USERNAME,
    render_logo,
    resolve_username,
    user_prompt,
)
from grandpa.core.config import DEFAULT_CONFIG_PATH, GrandpaConfig
from grandpa.core.types import Message, Role

TUI_PROMPT = user_prompt()
TUI_HISTORY_PATH = Path.home() / ".grandpa" / "terminal_history"


@dataclass
class InteractiveSession:
    """Mutable state shared by local TUI command handlers."""

    console: Console
    config: GrandpaConfig
    engine_name: str
    engine: object
    model: str
    history: list[Message]
    system_prompt: str | None = None
    username: str = DEFAULT_USERNAME
    should_exit: bool = False
    clear_requested: bool = False


@dataclass(frozen=True)
class LocalCommandResult:
    """Outcome of a local slash-command dispatch."""

    handled: bool
    message: str | None = None


CommandHandler = Callable[[InteractiveSession, str], LocalCommandResult]


@dataclass(frozen=True)
class InteractiveCommand:
    name: str
    description: str
    handler: CommandHandler
    aliases: tuple[str, ...] = field(default_factory=tuple)


class InteractiveCommandRegistry:
    """Registry-backed dispatcher for commands owned by the terminal UI."""

    def __init__(self, commands: tuple[InteractiveCommand, ...]) -> None:
        self._commands = commands
        self._by_name: dict[str, InteractiveCommand] = {}
        for command in commands:
            for name in (command.name, *command.aliases):
                self._by_name[name] = command

    @property
    def commands(self) -> tuple[InteractiveCommand, ...]:
        return self._commands

    def dispatch(self, session: InteractiveSession, text: str) -> LocalCommandResult:
        parts = text.strip().split(maxsplit=1)
        if not parts or not parts[0].startswith("/"):
            return LocalCommandResult(False)
        command = self._by_name.get(parts[0].lower())
        if command is None:
            return LocalCommandResult(False)
        argument = parts[1].strip() if len(parts) > 1 else ""
        return command.handler(session, argument)


def _help(session: InteractiveSession, argument: str) -> LocalCommandResult:
    if argument:
        from grandpa.cli.chat_cmd import _handle_help_slash_command

        message = _handle_help_slash_command(f"/help {argument}")
        return LocalCommandResult(True, message or "Unknown help topic.")
    from grandpa.cli.theme import help_commands_text

    return LocalCommandResult(
        True,
        "Grandpa Command Center\n\n" + help_commands_text(),
    )


def _clear(session: InteractiveSession, _argument: str) -> LocalCommandResult:
    session.history[:] = _system_messages(session)
    session.clear_requested = True
    return LocalCommandResult(True, "Conversation cleared.")


def _exit(session: InteractiveSession, _argument: str) -> LocalCommandResult:
    session.should_exit = True
    return LocalCommandResult(True, "Goodbye!")


def _status(session: InteractiveSession, _argument: str) -> LocalCommandResult:
    return LocalCommandResult(True, runtime_status_text(session))


def _model(session: InteractiveSession, argument: str) -> LocalCommandResult:
    if not argument:
        models = _list_models(session.engine)
        available = ", ".join(models[:8]) if models else "No models reported"
        return LocalCommandResult(
            True,
            f"Active model: {session.model}\nAvailable: {available}",
        )
    available = _list_models(session.engine)
    if available and argument not in available:
        return LocalCommandResult(
            True,
            f'Model "{argument}" is not available on {session.engine_name}.',
        )
    session.model = argument
    return LocalCommandResult(True, f"Model changed to {argument}.")


def _engine(session: InteractiveSession, argument: str) -> LocalCommandResult:
    if not argument:
        return LocalCommandResult(True, f"Active engine: {session.engine_name}")
    from grandpa.engine import get_engine

    requested = argument.lower()
    resolved = get_engine(session.config, requested)
    if resolved is None or resolved[0] != requested:
        return LocalCommandResult(True, f'Engine "{argument}" is not available.')
    previous_engine = session.engine
    session.engine_name, session.engine = resolved
    close = getattr(previous_engine, "close", None)
    if callable(close) and previous_engine is not session.engine:
        try:
            close()
        except Exception:
            pass
    models = _list_models(session.engine)
    if models and session.model not in models:
        session.model = models[0]
    return LocalCommandResult(True, f"Engine changed to {session.engine_name}.")


def _memory(_session: InteractiveSession, argument: str) -> LocalCommandResult:
    from grandpa.cli.chat_cmd import _handle_memory_slash_command

    command = "/memory" if not argument else f"/memory {argument}"
    return LocalCommandResult(
        True,
        _handle_memory_slash_command(command) or "Unknown memory command.",
    )


def _voice(_session: InteractiveSession, _argument: str) -> LocalCommandResult:
    return LocalCommandResult(
        True,
        "Voice mode is available as a dedicated session.\nRun: grandpa voice",
    )


def _doctor(session: InteractiveSession, _argument: str) -> LocalCommandResult:
    health = _engine_health(session.engine)
    status = "ready" if health else "unreachable"
    return LocalCommandResult(
        True,
        f"Grandpa runtime: ready\n{session.engine_name}: {status}\n"
        "For the full report, run: grandpa doctor",
    )


def _config(session: InteractiveSession, _argument: str) -> LocalCommandResult:
    return LocalCommandResult(
        True,
        f"Config: {DEFAULT_CONFIG_PATH}\n"
        f"Engine: {session.engine_name}\nModel: {session.model}",
    )


def _permissions(_session: InteractiveSession, _argument: str) -> LocalCommandResult:
    return LocalCommandResult(
        True,
        "Permissions\n"
        "- Read-only local context: allowed\n"
        "- Desktop changes: permission-gated\n"
        "- Destructive actions: confirmation required\n"
        "- Arbitrary shell execution: blocked",
    )


def _compact(session: InteractiveSession, _argument: str) -> LocalCommandResult:
    system = _system_messages(session)
    conversation = [
        message for message in session.history if message.role != Role.SYSTEM
    ]
    removed = max(0, len(conversation) - 8)
    session.history[:] = [*system, *conversation[-8:]]
    return LocalCommandResult(
        True,
        f"Conversation compacted. Removed {removed} older message(s).",
    )


def _history(session: InteractiveSession, _argument: str) -> LocalCommandResult:
    messages = [message for message in session.history if message.role != Role.SYSTEM]
    if not messages:
        return LocalCommandResult(True, "No conversation history yet.")
    lines = ["Conversation history:"]
    for message in messages[-20:]:
        role = (
            message.role.value if isinstance(message.role, Role) else str(message.role)
        )
        lines.append(f"{role.title()}: {message.content[:240]}")
    return LocalCommandResult(True, "\n".join(lines))


def _profile(session: InteractiveSession, argument: str) -> LocalCommandResult:
    from grandpa.profile import (
        configure_profile,
        format_profile,
        profile_from_config,
        reset_profile,
    )

    action = argument.strip().lower()
    if not action:
        return LocalCommandResult(
            True, format_profile(profile_from_config(session.config))
        )
    if action == "edit":
        updated = configure_profile(
            console=session.console,
            config=session.config,
            interactive=True,
        )
        session.config = updated
        session.username = resolve_username(updated)
        return LocalCommandResult(
            True,
            "Profile updated. Engine and model defaults apply on the next launch.\n"
            + format_profile(profile_from_config(updated)),
        )
    if action == "reset":
        import click

        if not click.confirm("Reset local profile?", default=False):
            return LocalCommandResult(True, "Profile reset cancelled.")
        reset_profile(confirmed=True)
        session.config.user.onboarding_completed = False
        return LocalCommandResult(
            True,
            "Profile reset. Onboarding will run at the next interactive launch.",
        )
    return LocalCommandResult(True, "Usage: /profile [edit|reset]")


def _whoami(session: InteractiveSession, _argument: str) -> LocalCommandResult:
    from grandpa.profile import LOCAL_MODE

    return LocalCommandResult(True, f"{session.username}\nMode: {LOCAL_MODE}")


def _system_messages(session: InteractiveSession) -> list[Message]:
    if not session.system_prompt:
        return []
    return [Message(role=Role.SYSTEM, content=session.system_prompt)]


INTERACTIVE_COMMANDS = InteractiveCommandRegistry(
    (
        InteractiveCommand("/help", "Show terminal commands", _help),
        InteractiveCommand("/clear", "Clear conversation", _clear),
        InteractiveCommand("/exit", "Exit Grandpa", _exit, aliases=("/quit", "/q")),
        InteractiveCommand("/status", "Show runtime status", _status),
        InteractiveCommand("/model", "Show or change model", _model),
        InteractiveCommand("/engine", "Show or change engine", _engine),
        InteractiveCommand("/memory", "Show personal memory", _memory),
        InteractiveCommand("/voice", "Show voice guidance", _voice),
        InteractiveCommand("/doctor", "Check runtime readiness", _doctor),
        InteractiveCommand("/config", "Show active configuration", _config),
        InteractiveCommand("/permissions", "Show safety permissions", _permissions),
        InteractiveCommand("/compact", "Compact conversation context", _compact),
        InteractiveCommand("/history", "Show session history", _history),
        InteractiveCommand("/profile", "Show or edit local profile", _profile),
        InteractiveCommand("/whoami", "Show local identity", _whoami),
    )
)


def set_terminal_title(title: str = "Grandpa") -> None:
    """Set a supported terminal title without affecting redirected output."""

    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(title)
            return
        except (AttributeError, OSError):
            pass
    if os.isatty(1):
        print(f"\033]0;{title}\007", end="", flush=True)


def render_startup_header(session: InteractiveSession) -> None:
    """Render a compact, scan-friendly runtime header."""

    render_logo(session.console)
    session.console.print()
    engine_label = session.engine_name.replace("_", " ").title()
    session.console.print(
        f"[bold #ffc448]Grandpa v{grandpa.__version__}[/bold #ffc448] "
        f"[dim]|[/dim] [#ffffff]{engine_label}[/#ffffff] "
        f"[dim]|[/dim] [#ffffff]{session.model}[/#ffffff]"
    )
    session.console.print()
    session.console.print(
        "[dim]Type /help for commands. Alt+Enter adds a new line.[/dim]"
    )


def interactive_prompt(session: InteractiveSession) -> str:
    """Return the configured prompt for an interactive session."""

    return user_prompt(session.username or resolve_username(session.config))


def runtime_status_text(session: InteractiveSession) -> str:
    return (
        f"Grandpa v{grandpa.__version__}\n"
        f"Engine: {session.engine_name}\n"
        f"Model: {session.model}\n"
        f"Directory: {Path.cwd()}\n"
        f"Memory: {_memory_status()}\n"
        f"Ollama: {_ollama_status(session)}"
    )


def _memory_status() -> str:
    try:
        from grandpa.memory_context import MemoryStore

        MemoryStore()
    except Exception:
        return "Unavailable"
    return "Active"


def _ollama_status(session: InteractiveSession) -> str:
    if session.engine_name != "ollama":
        return "Not active"
    return "Connected" if _engine_health(session.engine) else "Unreachable"


def _engine_health(engine: object) -> bool:
    health = getattr(engine, "health", None)
    if not callable(health):
        return False
    try:
        return bool(health())
    except Exception:
        return False


def _list_models(engine: object) -> list[str]:
    list_models = getattr(engine, "list_models", None)
    if not callable(list_models):
        return []
    try:
        return list(list_models())
    except Exception:
        return []


__all__ = [
    "INTERACTIVE_COMMANDS",
    "InteractiveCommand",
    "InteractiveCommandRegistry",
    "InteractiveSession",
    "LocalCommandResult",
    "TUI_HISTORY_PATH",
    "TUI_PROMPT",
    "render_startup_header",
    "interactive_prompt",
    "runtime_status_text",
    "set_terminal_title",
]
