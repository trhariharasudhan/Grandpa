from datetime import datetime

from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from grandpa.cli.slash_commands import command_groups

ACCENT = "#ffc448"       # border + GRANDPA logo
TEXT_ACCENT = "#6244c5"  # inside blue text replacement

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
    return "\n".join(f"{LEFT_INDENT}{line}" if line else "" for line in text.splitlines())


def _section(title: str, body: str) -> Text:
    return Text.from_markup(
        f"[bold {TEXT_ACCENT}]{title}[/bold {TEXT_ACCENT}]\n"
        f"[dim]{SECTION_RULE}[/dim]\n\n"
        f"{body}"
    )


def _build_left_panel(engine: str, model: str, agent: str) -> RenderableType:
    greeting = (
        f"[bold {ACCENT}]{_greeting()}, Hari[/bold {ACCENT}]\n"
        "[dim]Ready to assist.[/dim]"
    )
    session = (
        f"[{TEXT_ACCENT}]Mode      [/{TEXT_ACCENT}]: Odin\n"
        f"[{TEXT_ACCENT}]Engine    [/{TEXT_ACCENT}]: {engine}\n"
        f"[{TEXT_ACCENT}]Model     [/{TEXT_ACCENT}]: {model}\n"
        f"[{TEXT_ACCENT}]Memory    [/{TEXT_ACCENT}]: Active"
    )
    examples = (
        "• Open Chrome\n"
        "• Show my memories\n"
        "• Remind me at 8 PM\n"
        "• Search Python tutorials"
    )
    return Group(
        Text.from_markup(_indent(f"[bold {ACCENT}]{_logo()}[/bold {ACCENT}]")),
        "",
        Text.from_markup(_indent(greeting)),
        "",
        _section("Session", _indent(session)),
        "",
        _section("Examples", _indent(examples)),
    )


def _build_right_panel() -> RenderableType:
    status = (
        "[green]✓[/green] Brain Online\n"
        "[green]✓[/green] Memory Loaded\n"
        "[green]✓[/green] Tools Ready\n"
        "[green]✓[/green] Safety Enabled"
    )
    quick_start = (
        f"[{TEXT_ACCENT}]Press / [/{TEXT_ACCENT}]  Command Center\n"
        f"[{TEXT_ACCENT}]↑       [/{TEXT_ACCENT}]  Previous command\n"
        f"[{TEXT_ACCENT}]Tab     [/{TEXT_ACCENT}]  Autocomplete\n"
        f"[{TEXT_ACCENT}]Esc     [/{TEXT_ACCENT}]  Cancel"
    )
    return Group(
        _section("System Status", status),
        "",
        _section("Quick Start", quick_start),
    )


def render_chat_home(
    console: Console,
    engine: str,
    model: str,
    agent: str,
) -> None:
    table = Table.grid(expand=True)
    if console.width < TWO_COLUMN_MIN_WIDTH:
        table.add_column()
        table.add_row(_build_left_panel(engine, model, agent))
        table.add_row("")
        table.add_row(_build_right_panel())
    else:
        table.add_column(ratio=2)
        table.add_column(ratio=3)
        table.add_row(
            _build_left_panel(engine, model, agent),
            _build_right_panel(),
        )

    console.print(
        Panel(
            table,
            border_style=ACCENT,
            padding=(1, 2),
            subtitle=f"[bold {ACCENT}]Think • Plan • Execute[/bold {ACCENT}]",
            subtitle_align="center",
        )
    )


def render_help(console: Console) -> None:
    groups = command_groups()
    top_grid = Table.grid(expand=True)
    top_grid.add_column(ratio=1)
    top_grid.add_column(ratio=1)
    top_grid.add_column(ratio=1)
    top_grid.add_row(
        _command_group("Core", [command.name for command in groups["Core"]]),
        _command_group("Memory & Productivity", [command.name for command in groups["Memory & Productivity"]]),
        _command_group("Computer", [command.name for command in groups["Computer"]]),
    )

    bottom_grid = Table.grid(expand=True)
    bottom_grid.add_column(ratio=1)
    bottom_grid.add_column(ratio=1)
    bottom_grid.add_column(ratio=1)
    bottom_grid.add_row(
        _command_group("Developer", [command.name for command in groups["Developer"]]),
        _command_group("Personal", [command.name for command in groups["Personal"]]),
        _command_group("Automation", [command.name for command in groups["Automation"]]),
    )

    examples = (
        f"[bold {TEXT_ACCENT}]Natural examples[/bold {TEXT_ACCENT}]\n"
        "- show my memories\n"
        "- what reminders do I have\n"
        "- open Chrome\n"
        "- search YouTube for Python\n"
        "- call Amma\n"
        "- order biryani"
    )

    layout = Table.grid(expand=True)
    layout.add_column()
    layout.add_row(top_grid)
    layout.add_row("")
    layout.add_row(bottom_grid)
    layout.add_row("")
    layout.add_row(examples)

    console.print(f"[bold {ACCENT}]Grandpa Command Center[/bold {ACCENT}]")
    console.print()
    console.print(layout)


def help_commands_text() -> str:
    groups = command_groups()
    descriptions = {
        "/help": "Open command center",
        "/status": "Show Grandpa health",
        "/mode": "Switch assistant mode",
        "/settings": "Show settings help",
        "/model": "Select or change model",
        "/history": "Show chat history",
        "/clear": "Clear chat history",
        "/quit": "Exit chat",
        "/exit": "Exit chat",
        "/memory": "Manage saved memories",
        "/reminders": "Manage reminders",
        "/tasks": "Task planning help",
        "/desktop": "Desktop control help",
        "/browser": "Browser navigation/search help",
        "/files": "Local file search/actions",
        "/system": "System status help",
        "/coding": "Developer assistant",
        "/git": "Git workflow help",
        "/github": "GitHub workflow help",
        "/phone": "Phone bridge controls",
        "/voice": "Voice controls",
        "/order": "Daily-life ordering placeholder",
        "/automation": "Workflow automation help",
    }
    lines = [
        "/help commands - Shows all available slash commands grouped by module.",
    ]
    for category, commands in groups.items():
        lines.extend(("", category))
        lines.extend(f"{command.name:<13} {descriptions.get(command.name, command.description)}" for command in commands)
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
        "Phone:\n"
        "  call Amma\n\n"
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
        "Phone       Future mobile bridge for calls/SMS\n"
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

def render_assistant_response(console: Console, content) -> None:
    """Render AI response without title."""

    console.print(f"[bold {ACCENT}]<[/bold {ACCENT}] ", end="")
    console.print(content)
