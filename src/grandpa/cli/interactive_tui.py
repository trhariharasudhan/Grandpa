"""Interactive terminal session helpers for bare ``grandpa``."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

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
    from grandpa.intelligence.grandpa_models import (
        canonical_model_tag,
        get_model_role,
        user_visible_models,
    )

    if not argument:
        models = _list_models(session.engine)
        installed = set(models)
        lines = ["Grandpa Models", ""]
        for entry in user_visible_models(capability="chat"):
            marker = "*" if entry.ollama_tag == session.model else " "
            status = "" if entry.ollama_tag in installed else " (not installed)"
            lines.append(
                f"{marker} {entry.display_name.removeprefix('Grandpa '):<8} "
                f"{entry.description}{status}"
            )
        lines.append("\nUse /model <role> or /model <tag>.")
        return LocalCommandResult(
            True,
            "\n".join(lines),
        )
    available = _list_models(session.engine)
    requested = canonical_model_tag(argument)
    if available and requested not in available:
        return LocalCommandResult(
            True,
            f'Model "{requested}" is not available on {session.engine_name}.',
        )
    session.model = requested
    entry = get_model_role(requested)
    label = entry.display_name if entry else requested
    return LocalCommandResult(True, f"Model changed to {label} ({requested}).")


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


def _voice(session: InteractiveSession, argument: str) -> LocalCommandResult:
    args = argument.strip().split()
    if not args:
        return LocalCommandResult(
            True,
            "Usage:\n"
            "  /voice status           - Show current voice engine status\n"
            "  /voice backend <name>   - Change active TTS backend (e.g. grandpa_voice, kokoro)\n"
            "  /voice test             - Test voice synthesis and playback\n"
            "  /voice off              - Disable speech output\n"
            "  /voice on               - Enable speech output",
        )

    cmd = args[0].lower()

    # Helper to save settings
    def _update_and_persist_config(key: str, value: Any) -> None:
        parts = key.split(".")
        current = session.config
        for part in parts[:-1]:
            current = getattr(current, part)
        setattr(current, parts[-1], value)

        import tomlkit

        from grandpa.core.config import DEFAULT_CONFIG_DIR

        config_path = Path(
            os.environ.get("Grandpa_CONFIG", DEFAULT_CONFIG_DIR / "config.toml")
        )
        if config_path.exists():
            try:
                doc = tomlkit.parse(config_path.read_text("utf-8"))
            except Exception:
                doc = tomlkit.document()
        else:
            doc = tomlkit.document()
            config_path.parent.mkdir(parents=True, exist_ok=True)

        current_toml = doc
        for part in parts[:-1]:
            if part not in current_toml:
                current_toml.add(part, tomlkit.table())
            current_toml = current_toml[part]
        current_toml[parts[-1]] = value

        config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    if cmd == "status":
        import grandpa.speech  # noqa: F401 - registers local TTS backends
        from grandpa.core.registry import TTSRegistry

        backend = session.config.tts.backend
        enabled_str = "Enabled" if session.config.tts.enabled else "Disabled"

        health_str = "Offline"
        if TTSRegistry.contains(backend):
            try:
                backend_cls = TTSRegistry.get(backend)
                health_str = "Ready" if backend_cls().health() else "Offline"
            except Exception:
                pass

        status_msg = (
            f"Voice: {enabled_str}\n"
            f"TTS Backend: {backend}\n"
            f"Engine: {session.config.grandpa_voice.engine}\n"
            f"Mode: Local\n"
            f"Internet Required: No\n"
            f"Reference Voice: {session.config.grandpa_voice.voice_id}\n"
            f"Health: {health_str}"
        )
        return LocalCommandResult(True, status_msg)

    elif cmd == "backend":
        if len(args) < 2:
            return LocalCommandResult(
                True, "Please specify a backend name, e.g. /voice backend grandpa_voice"
            )
        backend_name = args[1].lower()

        import grandpa.speech  # noqa: F401 - registers local TTS backends
        from grandpa.core.registry import TTSRegistry

        if not TTSRegistry.contains(backend_name):
            return LocalCommandResult(
                True,
                f"Backend '{backend_name}' is not registered.\n"
                f"Available backends: {', '.join(TTSRegistry.keys())}",
            )

        try:
            _update_and_persist_config("tts.backend", backend_name)
            return LocalCommandResult(
                True, f"Voice backend changed to '{backend_name}'."
            )
        except Exception as exc:
            return LocalCommandResult(True, f"Failed to save voice backend: {exc}")

    elif cmd == "off":
        try:
            _update_and_persist_config("tts.enabled", False)
            return LocalCommandResult(True, "Voice output disabled.")
        except Exception as exc:
            return LocalCommandResult(True, f"Failed to disable voice output: {exc}")

    elif cmd == "on":
        try:
            _update_and_persist_config("tts.enabled", True)
            return LocalCommandResult(True, "Voice output enabled.")
        except Exception as exc:
            return LocalCommandResult(True, f"Failed to enable voice output: {exc}")

    elif cmd == "test":
        from grandpa.voice.speech_output import SpeechOutputEngine

        engine = SpeechOutputEngine()
        phrase = "Hello, I am Grandpa, your offline local cloned voice assistant."
        try:
            result = engine.speak(phrase)
            if result.status == "fallback" and result.engine == "print_only":
                return LocalCommandResult(
                    True,
                    f"Test phrase: '{phrase}'\n(Speech output unavailable; printed response only)",
                )
            return LocalCommandResult(
                True,
                f"Live voice test spoken successfully.\n"
                f"Text: '{phrase}'\n"
                f"Backend used: {result.engine}",
            )
        except Exception as exc:
            return LocalCommandResult(True, f"Live voice test failed: {exc}")

    else:
        return LocalCommandResult(
            True, f"Unknown voice subcommand: '{cmd}'. Type '/voice' for help."
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
        import click

        choice = click.prompt(
            "Profile: 1) display name  2) preferred title  3) reset  4) back",
            type=click.Choice(("1", "2", "3", "4")),
            default="4",
        )
        if choice == "4":
            return LocalCommandResult(True, "Profile unchanged.")
        if choice == "3":
            if not click.confirm("Reset local profile?", default=False):
                return LocalCommandResult(True, "Profile reset cancelled.")
            reset_profile(confirmed=True)
            session.config.user.onboarding_completed = False
            return LocalCommandResult(
                True,
                "Profile reset. Onboarding will run at the next interactive launch.",
            )
        updated = configure_profile(
            console=session.console,
            config=session.config,
            interactive=True,
            edit_username=choice == "1",
            edit_title=choice == "2",
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
    from grandpa.intelligence.grandpa_models import get_model_role

    entry = get_model_role(session.model)
    model_label = entry.ollama_tag.removesuffix(":latest") if entry else session.model
    session.console.print(
        f"[bold #ffc448]Grandpa v{grandpa.__version__}[/bold #ffc448] "
        f"[dim]|[/dim] [#ffffff]{engine_label}[/#ffffff] "
        f"[dim]|[/dim] [#ffffff]{model_label}[/#ffffff]"
    )
    session.console.print()
    session.console.print(f"[dim]{chat_helper_text(session.console)}[/dim]")


def chat_helper_text(console: Console) -> str:
    """Return modern helper text with an encoding-safe separator."""

    encoding = getattr(getattr(console, "file", None), "encoding", None) or "utf-8"
    try:
        "•".encode(encoding)
        separator = " • "
    except (LookupError, UnicodeEncodeError):
        separator = " | "
    return separator.join(
        ("Ask anything", "/ for commands", "Alt+Enter for a new line")
    )


def interactive_prompt(session: InteractiveSession) -> str:
    """Return the configured prompt for an interactive session."""

    return user_prompt(session.username or resolve_username(session.config))


def runtime_status_text(session: InteractiveSession) -> str:
    from grandpa.intelligence.grandpa_models import get_model_role

    entry = get_model_role(session.model)
    if entry:
        model_lines = (
            f"Model: {entry.display_name}\n"
            f"Role: {entry.description}\n"
            f"Runtime tag: {entry.ollama_tag}\n"
            f"Base family: {entry.base_family}"
        )
    else:
        model_lines = f"Model: {session.model}"
    return (
        f"Grandpa v{grandpa.__version__}\n"
        f"Engine: {session.engine_name}\n"
        f"{model_lines}\n"
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
    "chat_helper_text",
    "render_startup_header",
    "interactive_prompt",
    "runtime_status_text",
    "set_terminal_title",
]
