from contextlib import contextmanager
from datetime import datetime

from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.text import Text

from grandpa.cli.slash_commands import command_groups, picker_group_items

ACCENT = "#ffc448"  # border + GRANDPA logo
TEXT_ACCENT = "#6244c5"  # inside blue text replacement
DEFAULT_USERNAME = "Username"
ASSISTANT_NAME = "Grandpa"

CHAT_STARTUP_TEXT = (
    "Chat Assistant\nType your message and press Enter.\nType exit or quit to leave."
)

VOICE_STARTUP_TEXT = 'Voice Assistant\nSay "stop listening" to exit.'

FAREWELL_TEXT = "Goodbye! I’ll be here when you need me."

GRANDPA_LOGO = r"""
  ██████╗ ██████╗  █████╗ ███╗   ██╗██████╗ ██████╗  █████╗
 ██╔════╝ ██╔══██╗██╔══██╗████╗  ██║██╔══██╗██╔══██╗██╔══██╗
 ██║  ███╗██████╔╝███████║██╔██╗ ██║██║  ██║██████╔╝███████║
 ██║   ██║██╔══██╗██╔══██║██║╚██╗██║██║  ██║██╔═══╝ ██╔══██║
 ╚██████╔╝██║  ██║██║  ██║██║ ╚████║██████╔╝██║     ██║  ██║
  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═════╝ ╚═╝     ╚═╝  ╚═╝
"""


LEFT_INDENT = "  "
TWO_COLUMN_MIN_WIDTH = 108
SECTION_RULE = "────────────────"


def _greeting() -> str:
    hour = datetime.now().hour

    if hour < 12:
        return "Good Morning"
    if hour < 17:
        return "Good Afternoon"
    return "Good Evening"


def _logo() -> str:
    lines = GRANDPA_LOGO.strip("\n").splitlines()
    width = max(len(line) for line in lines)
    return "\n".join(line.ljust(width) for line in lines)


def _indent(text: str) -> str:
    return "\n".join(
        f"{LEFT_INDENT}{line}" if line else "" for line in text.splitlines()
    )


def _section(title: str, body: str) -> Text:
    return Text.from_markup(
        f"[bold {TEXT_ACCENT}]{title}[/bold {TEXT_ACCENT}]\n"
        f"[dim]{SECTION_RULE}[/dim]\n\n"
        f"{body}"
    )


def _build_left_panel(engine: str, model: str, agent: str) -> RenderableType:
    return Group(
        Align.center(Text.from_markup(f"[bold {ACCENT}]{_logo()}[/bold {ACCENT}]"))
    )


def _build_right_panel() -> RenderableType:
    return Text("")


def render_chat_home(
    console: Console,
    engine: str,
    model: str,
    agent: str,
) -> None:
    """Render the legacy chat home without the former full-screen panel."""
    console.print()
    render_logo_borderless(console)
    console.print()
    console.print(CHAT_STARTUP_TEXT)


def render_logo(console: Console) -> None:
    """Render the canonical Grandpa logo without a surrounding panel."""

    console.print(Text(_logo(), style=f"bold {ACCENT}"))


def render_logo_borderless(console: Console) -> None:
    """Backward-compatible alias for the canonical logo renderer."""

    render_logo(console)


def render_help(console: Console) -> None:
    console.print(f"[bold {ACCENT}]Grandpa Command Center[/bold {ACCENT}]")
    console.print()
    console.print(help_commands_text())
    console.print()
    console.print("[dim]More: /help tools  /help advanced  /help all[/dim]")


def help_commands_text(view: str = "default") -> str:
    groups = command_groups(view)
    heading = {
        "default": "Beginner commands",
        "tools": "/help tools - Local tools and integrations",
        "advanced": "/help advanced - Settings and advanced controls",
        "all": "/help all - Complete slash command reference",
        "commands": "/help commands - Shows beginner-friendly slash commands.",
    }.get(view, "Beginner commands")
    lines = [heading]
    for category, commands in groups.items():
        lines.extend(("", category))
        for command in commands:
            if view in {"default", "commands"} and command.name == "/tools":
                lines.extend(
                    f"{item.command:<22} {item.description}"
                    for item in picker_group_items("Tools")
                )
                continue
            display_name = command.name
            if view == "tools":
                display_name = f"/tools {command.name.lstrip('/')}"
            elif view == "advanced":
                display_name = f"/settings {command.name.lstrip('/')}"
            lines.append(f"{display_name:<22} {command.description}")
    return "\n".join(lines)


def help_examples_text() -> str:
    return (
        "/help examples - Shows natural language examples you can type.\n\n"
        "Memory:\n"
        "  show my memories\n\n"
        "Reminders:\n"
        "  what reminders do I have\n"
        "  remind me in 30 minutes to drink water\n\n"
        "Desktop:\n"
        "  open Chrome\n\n"
        "Browser:\n"
        "  search YouTube for Python\n\n"
        "Daily Life:\n"
        "  order biryani"
    )


def help_modules_text() -> str:
    return (
        "/help modules - Explains what each Grandpa module is for.\n\n"
        "Memory      Saved facts, preferences, and profile details\n"
        "Reminders   One-shot reminders and reminder listing\n"
        "Desktop     Computer/app/window control\n"
        "Browser     Web navigation/search\n"
        "Files       Local file search/actions\n"
        "Voice       Local speech input, wake word, and spoken responses\n"
        "Coding      Developer assistant\n"
        "Automation  Workflows/routines\n"
        "Order       Future daily-life ordering"
    )


def help_shortcuts_text() -> str:
    return (
        "/help shortcuts - Shows keyboard controls for the slash picker.\n\n"
        "Left/Right  Move between top-level commands\n"
        "Up/Down     Move through preview options\n"
        "Enter       Select highlighted option\n"
        "Ctrl+C/Esc  Cancel if supported"
    )


def _command_group(title: str, commands: list[str]) -> str:
    lines = [f"[bold {TEXT_ACCENT}]{title}[/bold {TEXT_ACCENT}]"]
    lines.extend(f"[{TEXT_ACCENT}]{command}[/{TEXT_ACCENT}]" for command in commands)
    return "\n".join(lines)


def resolve_username(config=None) -> str:
    """Resolve a safe terminal display name from the active config."""

    configured = getattr(getattr(config, "user", None), "username", "")
    normalized = " ".join(str(configured or "").split()).strip()
    return normalized[:40] or DEFAULT_USERNAME


def user_prompt(username: str = DEFAULT_USERNAME) -> str:
    """Return the shared interactive user prompt."""

    normalized = " ".join(str(username).split()).strip()[:40]
    return f"{normalized or DEFAULT_USERNAME} > "


def render_user_message(
    console: Console,
    content: str,
    *,
    username: str = DEFAULT_USERNAME,
) -> None:
    """Render submitted user input into the permanent chat transcript."""

    normalized = " ".join(str(username).split()).strip()[:40] or DEFAULT_USERNAME
    label = Text(f"{normalized} >", style=f"bold {TEXT_ACCENT}")
    console.print(Text.assemble(label, " ", content))


def render_assistant_prefix(console: Console) -> None:
    """Render the stable Grandpa response prefix."""

    console.print(Text(f"{ASSISTANT_NAME} >", style=f"bold {ACCENT}"), end=" ")


def render_assistant_response(console: Console, content) -> None:
    """Render a prefixed Grandpa response."""

    render_assistant_prefix(console)
    console.print(content)


def render_status_message(console: Console, content) -> None:
    """Render an informational status or system message without assistant prefix."""

    if isinstance(content, str):
        console.print(f"[dim]{content}[/dim]")
    elif hasattr(content, "style"):
        content.style = "dim"
        console.print(content)
    else:
        console.print(content)


def enable_vt_mode() -> bool:
    """Enable Virtual Terminal Processing on Windows to support ANSI escape sequences."""
    import sys

    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        hOut = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        if hOut == -1 or hOut is None:
            return False

        dwMode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(hOut, ctypes.byref(dwMode)):
            return False

        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        dwMode.value |= 0x0004
        if not kernel32.SetConsoleMode(hOut, dwMode):
            return False
        return True
    except Exception:
        return False


@contextmanager
def alternate_screen(enabled: bool = True):
    """Enter and exit terminal alternate screen buffer using VT100/ANSI escape sequences."""
    if not enabled:
        yield
        return

    # Check if stdout and stderr are TTYs
    is_tty = False
    try:
        import sys

        is_tty = sys.stdout.isatty() and sys.stderr.isatty()
    except Exception:
        pass

    if is_tty:
        # Enable VT mode on Windows to support ANSI sequences
        import sys

        if sys.platform == "win32":
            enable_vt_mode()

        # Enter alternate screen buffer and move cursor to home
        sys.stdout.write("\x1b[?1049h\x1b[H")
        sys.stdout.flush()
        try:
            yield
        finally:
            # Exit alternate screen buffer, restore cursor shape/visibility, and reset styles
            try:
                sys.stdout.write("\x1b[?1049l\x1b[?25h\x1b[0m")
                sys.stdout.flush()
            except Exception:
                pass
    else:
        # Fallback to standard terminal output
        yield
