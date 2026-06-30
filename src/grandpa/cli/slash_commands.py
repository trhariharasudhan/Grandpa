"""Shared slash command registry for Grandpa chat."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlashPreviewItem:
    command: str
    label: str


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    category: str
    label: str = ""
    status: str = "Available"
    subcommands: tuple[str, ...] = ()
    preview: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    note: str = ""

    @property
    def display_label(self) -> str:
        return self.label or self.name.lstrip("/").replace("-", " ").title()


CATEGORY_ORDER = (
    "Core",
    "Memory & Productivity",
    "Computer",
    "Developer",
    "Personal",
    "Automation",
)

SLASH_COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand(
        "/help",
        "Command center",
        "Core",
        preview=("/help", "/help commands", "/help examples", "/help modules"),
    ),
    SlashCommand(
        "/status",
        "Grandpa status",
        "Core",
        preview=("/status", "/system", "/model"),
        examples=("what is your status", "is Grandpa running"),
        note="Status checks are read-only.",
    ),
    SlashCommand(
        "/mode",
        "Assistant modes",
        "Core",
        status="Help only / Not persisted yet",
        subcommands=(
            "/mode list",
            "/mode show",
            "/mode coding",
            "/mode personal",
            "/mode system",
            "/mode automation",
            "/mode learning",
        ),
        note="Mode switching is a safe placeholder for now.",
    ),
    SlashCommand(
        "/settings",
        "Settings",
        "Core",
        status="Planned / Not configured",
        subcommands=("/settings", "/settings show", "/settings profile"),
        preview=("/settings", "/mode", "/model"),
        examples=("show my settings", "what is my default model"),
        note="Settings changes are not wired into chat yet.",
    ),
    SlashCommand("/model", "Model picker", "Core"),
    SlashCommand("/history", "Chat history", "Core"),
    SlashCommand("/clear", "Clear chat", "Core"),
    SlashCommand("/quit", "Exit chat", "Core"),
    SlashCommand("/exit", "Exit chat", "Core"),
    SlashCommand(
        "/memory",
        "Personal memory",
        "Memory & Productivity",
        subcommands=(
            "/memory list",
            "/memory all",
            "/memory search <query>",
            "/memory forget <query or id>",
        ),
        examples=("show my memories", "remember my name is Hari"),
    ),
    SlashCommand(
        "/reminders",
        "One-shot reminders",
        "Memory & Productivity",
        subcommands=("/reminders list", "/reminders all", "/reminders cancel <id>"),
        examples=("what reminders do I have", "remind me in 30 minutes to drink water"),
    ),
    SlashCommand(
        "/tasks",
        "Task planner",
        "Memory & Productivity",
        status="Planned / Partially available",
        subcommands=("/tasks list", "/tasks add <task>", "/tasks done <id>"),
        examples=("show my tasks", "plan my day", "what should I do next"),
        note="Task planning is a safe placeholder here and does not execute actions.",
    ),
    SlashCommand(
        "/desktop",
        "Desktop control",
        "Computer",
        status="Available with safety confirmations",
        subcommands=("/desktop status", "/desktop apps", "/desktop windows"),
        examples=("open Chrome", "type hello in Notepad", "press enter"),
        note="Desktop actions use Grandpa's local permission and confirmation layer.",
    ),
    SlashCommand(
        "/browser",
        "Browser control",
        "Computer",
        status="Planned / Partially available",
        subcommands=("/browser open <url>", "/browser search <query>", "/browser tabs"),
        examples=("search YouTube for Python", "open the browser", "summarize this page"),
        note="Browser actions must stay local and permission-aware.",
    ),
    SlashCommand(
        "/files",
        "Files",
        "Computer",
        status="Available with safe local handling",
        subcommands=("/files search <query>", "/files recent"),
        examples=("summarize this file", "find my notes about Grandpa"),
        note="File actions should avoid destructive changes unless explicitly confirmed.",
    ),
    SlashCommand(
        "/system",
        "System",
        "Computer",
        status="Planned / Restricted",
        subcommands=("/system status", "/system diagnostics", "/system health"),
        examples=("show system status", "check disk space"),
        note="No shutdown, restart, or destructive system action is enabled here.",
    ),
    SlashCommand(
        "/coding",
        "Coding",
        "Developer",
        subcommands=("/coding status", "/coding help", "/coding diagnostics"),
        examples=("review this code", "explain this error", "run the tests"),
        note="Coding actions should keep repository changes reviewable.",
    ),
    SlashCommand(
        "/git",
        "Git",
        "Developer",
        status="Planned / Partially available",
        subcommands=("/git status", "/git diff", "/git commit"),
        examples=("show git status", "summarize my changes"),
        note="Git commit and push actions require explicit user approval.",
    ),
    SlashCommand(
        "/github",
        "GitHub",
        "Developer",
        label="GitHub",
        status="Planned / Not configured",
        subcommands=("/github status", "/github prs", "/github issues"),
        examples=("show my open pull requests", "summarize issue 12"),
        note="GitHub actions require authenticated local tooling or a configured connector.",
    ),
    SlashCommand(
        "/phone",
        "Phone",
        "Personal",
        status="Planned / Not configured",
        subcommands=("/phone status", "/phone connect", "/call <contact>", "/sms <contact> <message>"),
        examples=("call Amma", "send SMS to Arjun", "show phone notifications"),
        note="Phone actions require a future Android companion app or Bluetooth/mobile bridge.",
    ),
    SlashCommand(
        "/voice",
        "Voice",
        "Personal",
        status="Available for safe foundations",
        subcommands=("/voice status", "/voice wake-word", "/voice loop"),
        examples=("what is my voice status", "start push to talk"),
        note="No always-on microphone starts from this chat command.",
    ),
    SlashCommand(
        "/order",
        "Order",
        "Personal",
        status="Planned / Not configured",
        subcommands=("/order food", "/order grocery", "/order status"),
        examples=("order biryani", "reorder groceries"),
        note="Ordering is a future feature. Grandpa will not place real orders from this command.",
    ),
    SlashCommand(
        "/automation",
        "Automation",
        "Automation",
        status="Planned / Permission-gated",
        subcommands=("/automation status", "/automation help", "/automation workflows"),
        examples=("create a workflow for my morning setup", "show automation diagnostics"),
        note="Automation must remain explicit, local, and confirmation-gated.",
    ),
)

COMMAND_BY_NAME = {command.name: command for command in SLASH_COMMANDS}


def command_groups() -> dict[str, list[SlashCommand]]:
    groups: dict[str, list[SlashCommand]] = {category: [] for category in CATEGORY_ORDER}
    for command in SLASH_COMMANDS:
        groups.setdefault(command.category, []).append(command)
    return groups


def top_level_commands() -> list[SlashCommand]:
    return list(SLASH_COMMANDS)


def command_names() -> list[str]:
    return [command.name for command in SLASH_COMMANDS]


def get_command(name: str) -> SlashCommand | None:
    return COMMAND_BY_NAME.get(name)


def command_help_text(name: str) -> str | None:
    command = get_command(name)
    if command is None:
        return None
    module_name = {
        "/status": "Grandpa Status",
        "/mode": "Assistant Modes",
        "/github": "GitHub Module",
    }.get(command.name, f"{command.name.lstrip('/').title()} Module")
    lines = [
        module_name,
        f"Status: {command.status}",
    ]
    if command.subcommands:
        lines.extend(("", "Commands:"))
        lines.extend(f"- {subcommand}" for subcommand in command.subcommands)
    if command.examples:
        lines.extend(("", "Natural examples:"))
        lines.extend(f"- {example}" for example in command.examples)
    if command.note:
        lines.extend(("", "Note:", command.note))
    return "\n".join(lines)


def command_preview_items(name: str) -> list[str]:
    return [item.command for item in command_preview_options(name)]


def command_preview_options(name: str) -> list[SlashPreviewItem]:
    command = get_command(name)
    if command is None:
        return []
    if command.subcommands:
        return [_preview_item(item) for item in command.subcommands]
    if command.preview:
        return [_preview_item(item) for item in command.preview]
    return [_preview_item(item) for item in (command.name, *command.examples[:3])]


def _preview_item(command: str) -> SlashPreviewItem:
    return SlashPreviewItem(command=command, label=_preview_label(command))


def _preview_label(command: str) -> str:
    if not command.startswith("/"):
        return command
    parts = command.split()
    if len(parts) == 1:
        return parts[0].lstrip("/").replace("-", " ").title()
    label = " ".join(parts[1:])
    label = label.replace("<", "").replace(">", "")
    return label.replace("-", " ").title()


def mode_help_text() -> str:
    return command_help_text("/mode") or ""


def unknown_command_message(command: str) -> str:
    command_name = command.split(maxsplit=1)[0]
    suggestions = "\n".join(["/help", "/memory", "/reminders", "/desktop", "/phone"])
    return f"Unknown command: {command_name}\n\nTry:\n{suggestions}"
