from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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

def _greeting() -> str:
    hour = datetime.now().hour

    if hour < 12:
        return "Good Morning"
    if hour < 17:
        return "Good Afternoon"
    return "Good Evening"

def _build_left_panel(engine: str, model: str, agent: str) -> str:
    return (
        f"[bold {ACCENT}]{GRANDPA_LOGO}[/bold {ACCENT}]\n"
        "[bold]Grandpa AI[/bold]\n\n"
        f"[{TEXT_ACCENT}]Mode       [/{TEXT_ACCENT}] : Odin\n"
        f"[{TEXT_ACCENT}]Engine     [/{TEXT_ACCENT}] : {engine}\n"
        f"[{TEXT_ACCENT}]Model      [/{TEXT_ACCENT}] : {model}\n"
        f"[{TEXT_ACCENT}]Agent      [/{TEXT_ACCENT}] : {agent}\n"
        f"[{TEXT_ACCENT}]Memory     [/{TEXT_ACCENT}] : Active\n"
        f"[{TEXT_ACCENT}]Automation [/{TEXT_ACCENT}] : Enabled\n"
        f"[{TEXT_ACCENT}]Voice      [/{TEXT_ACCENT}] : Ready\n"
        f"[{TEXT_ACCENT}]Status     [/{TEXT_ACCENT}] : 🟢 Listening\n\n"
        f"[bold {ACCENT}]{_greeting()}, Hari[/bold {ACCENT}]\n"
        "[dim]Ready to assist.[/dim]\n\n"
        "[dim]Personal AI Operating System[/dim]\n"
        "[dim]Private • Local • Offline[/dim]"
    )


def _build_right_panel() -> str:
    return (
        f"[bold {TEXT_ACCENT}]SYSTEM STATUS[/bold {TEXT_ACCENT}]\n\n"
        "[green]✓[/green] Brain Online\n"
        "[green]✓[/green] Memory Loaded\n"
        "[green]✓[/green] Tools Ready\n"
        "[green]✓[/green] Safety Enabled\n\n"
        "[dim]────────────────────────[/dim]\n\n"
        f"[bold {TEXT_ACCENT}]CAPABILITIES[/bold {TEXT_ACCENT}]\n\n"
        "AI Chat          Files\n"
        "Voice            Browser\n"
        "Desktop Control  Terminal\n"
        "Reminders        Automation\n\n"
        "[dim]────────────────────────[/dim]\n\n"
        f"[bold {TEXT_ACCENT}]QUICK ACTIONS[/bold {TEXT_ACCENT}]\n\n"
        f"[{TEXT_ACCENT}]/help[/{TEXT_ACCENT}]     Commands\n"
        f"[{TEXT_ACCENT}]/model[/{TEXT_ACCENT}]    Model info\n"
        f"[{TEXT_ACCENT}]/history[/{TEXT_ACCENT}]  Chat history\n"
        f"[{TEXT_ACCENT}]/clear[/{TEXT_ACCENT}]    Clear chat\n"
        f"[{TEXT_ACCENT}]/memory[/{TEXT_ACCENT}]   Memory commands\n"
        f"[{TEXT_ACCENT}]/reminders[/{TEXT_ACCENT}] Reminder commands\n"
        f"[{TEXT_ACCENT}]/quit[/{TEXT_ACCENT}]     Exit"
    )


def render_chat_home(
    console: Console,
    engine: str,
    model: str,
    agent: str,
) -> None:
    table = Table.grid(expand=True)
    table.add_column(ratio=1)
    table.add_column(ratio=1)

    table.add_row(
        _build_left_panel(engine, model, agent),
        _build_right_panel(),
    )

    panel = Panel(
        table,
        title=f"[bold {ACCENT}]Grandpa Odin[/bold {ACCENT}]",
        title_align="left",
        subtitle=f"[bold {ACCENT}]Think • Plan • Execute[/bold {ACCENT}]",
        border_style=ACCENT,
        padding=(1, 2),
    )

    console.print(panel)


def render_help(console: Console) -> None:
    top_grid = Table.grid(expand=True)
    top_grid.add_column(ratio=1)
    top_grid.add_column(ratio=1)
    top_grid.add_column(ratio=1)
    top_grid.add_row(
        _command_group("Core", ["/status", "/mode", "/settings", "/help", "/model", "/history", "/clear", "/quit"]),
        _command_group("Memory & Productivity", ["/memory", "/reminders", "/tasks"]),
        _command_group("Computer", ["/desktop", "/browser", "/files", "/system"]),
    )

    bottom_grid = Table.grid(expand=True)
    bottom_grid.add_column(ratio=1)
    bottom_grid.add_column(ratio=1)
    bottom_grid.add_column(ratio=1)
    bottom_grid.add_row(
        _command_group("Developer", ["/coding", "/git", "/github"]),
        _command_group("Personal", ["/phone", "/voice", "/order"]),
        _command_group("Automation", ["/automation"]),
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

    console.print(
        Panel(
            layout,
            title=f"[bold {ACCENT}]Grandpa Command Center[/bold {ACCENT}]",
            title_align="left",
            border_style=ACCENT,
            padding=(1, 2),
        )
    )


def _command_group(title: str, commands: list[str]) -> str:
    lines = [f"[bold {TEXT_ACCENT}]{title}[/bold {TEXT_ACCENT}]"]
    lines.extend(f"[{TEXT_ACCENT}]{command}[/{TEXT_ACCENT}]" for command in commands)
    return "\n".join(lines)

def render_assistant_response(console: Console, content) -> None:
    """Render AI response without title."""

    console.print(f"[bold {ACCENT}]<[/bold {ACCENT}] ", end="")
    console.print(content)
