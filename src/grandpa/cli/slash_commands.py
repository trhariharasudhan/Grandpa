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
    routing: str = "local"

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
        routing="help",
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
        routing="help",
    ),
    SlashCommand(
        "/engine",
        "Inference engine",
        "Core",
        subcommands=("/engine", "/engine ollama"),
        note="Engine changes apply to the current interactive session.",
    ),
    SlashCommand("/model", "Model picker", "Core"),
    SlashCommand("/history", "Chat history", "Core"),
    SlashCommand(
        "/profile",
        "Local profile",
        "Core",
        subcommands=("/profile", "/profile edit", "/profile reset"),
        examples=("show my local profile", "change my display name"),
        note="Profile settings stay on this computer.",
    ),
    SlashCommand("/whoami", "Local identity and mode", "Core"),
    SlashCommand("/compact", "Compact context", "Core"),
    SlashCommand("/config", "Active configuration", "Core"),
    SlashCommand("/permissions", "Safety permissions", "Core"),
    SlashCommand("/doctor", "Readiness check", "Core"),
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
        "/gmail",
        "Gmail",
        "Memory & Productivity",
        status="Optional / requires OAuth setup",
        subcommands=(
            "/gmail setup",
            "/gmail status",
            "/gmail inbox",
            "/gmail unread",
            "/gmail search <query>",
            "/gmail read <selector>",
            "/gmail summarize <selector>",
            "/gmail labels",
        ),
        examples=(
            "show unread emails",
            "read latest email from Arjun",
            "summarize emails from today",
        ),
        note="Gmail uses local OAuth tokens and never asks for your Google password.",
    ),
    SlashCommand(
        "/calendar",
        "Calendar",
        "Memory & Productivity",
        status="Optional / requires OAuth setup",
        subcommands=(
            "/calendar setup",
            "/calendar status",
            "/calendar today",
            "/calendar tomorrow",
            "/calendar week",
            "/calendar upcoming",
            "/calendar free",
            "/calendar create <details>",
            "/calendar update <details>",
            "/calendar delete <details>",
        ),
        examples=(
            "what is on my calendar today",
            "show free time this afternoon",
            "create a meeting tomorrow at 3 PM",
        ),
        note="Calendar writes require confirmation and use local OAuth tokens.",
    ),
    SlashCommand(
        "/notes",
        "Notes",
        "Memory & Productivity",
        status="Available / local only",
        subcommands=(
            "/notes list",
            "/notes recent",
            "/notes search <query>",
            "/notes open <name>",
            "/notes create <name>",
            "/notes append <name>",
            "/notes rename",
            "/notes delete",
            "/notes archive",
            "/notes restore",
            "/notes pin",
        ),
        examples=(
            "create a note called Grandpa Ideas",
            "search notes for browser automation",
            "append this to my project note",
        ),
        note="Notes are local Markdown files under Grandpa's notes directory.",
    ),
    SlashCommand(
        "/tasks",
        "Task planner",
        "Memory & Productivity",
        status="Planned / Partially available",
        subcommands=("/tasks list", "/tasks add <task>", "/tasks done <id>"),
        examples=("show my tasks", "plan my day", "what should I do next"),
        note="Task planning is a safe placeholder here and does not execute actions.",
        routing="help",
    ),
    SlashCommand(
        "/desktop",
        "Desktop control",
        "Computer",
        status="Available via natural commands / Help only",
        subcommands=("/desktop status", "/desktop apps", "/desktop windows"),
        examples=("open Chrome", "type hello in Notepad", "press enter"),
        note="Desktop actions use Grandpa's local permission and confirmation layer.",
        routing="help",
    ),
    SlashCommand(
        "/apps",
        "Application manager",
        "Computer",
        status="Available / local index",
        subcommands=(
            "/apps scan",
            "/apps refresh",
            "/apps list",
            "/apps search <name>",
            "/apps find <name>",
            "/apps running",
            "/apps open <name>",
        ),
        examples=(
            "open Visual Studio Code",
            "list installed applications",
            "search applications for Blender",
        ),
        note="Apps are launched only from Grandpa's local application index or existing safe app resolver.",
    ),
    SlashCommand(
        "/browser",
        "Browser control",
        "Computer",
        status="Planned / Partially available",
        subcommands=("/browser open <url>", "/browser search <query>", "/browser tabs"),
        examples=(
            "search YouTube for Python",
            "open the browser",
            "summarize this page",
        ),
        note="Browser actions must stay local and permission-aware.",
    ),
    SlashCommand(
        "/search",
        "Web search",
        "Computer",
        status="Optional / requires provider setup",
        subcommands=(
            "/search web <query>",
            "/search news <query>",
            "/search official <query>",
            "/search recent <query>",
            "/search sources",
            "/search clear-cache",
        ),
        examples=(
            "search the web for FastAPI tutorials",
            "find recent AI news",
            "search official Python docs for asyncio",
        ),
        note="Web search uses configured provider APIs and treats results as untrusted.",
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
        "/downloads",
        "Downloads",
        "Computer",
        status="Available / local only",
        subcommands=(
            "/downloads recent",
            "/downloads today",
            "/downloads latest",
            "/downloads search <query>",
            "/downloads large",
            "/downloads incomplete",
            "/downloads organize",
            "/downloads move <selector> <destination>",
            "/downloads archive <selector>",
            "/downloads delete <selector>",
            "/downloads duplicates",
            "/downloads info <selector>",
        ),
        examples=(
            "show recent downloads",
            "find downloaded PDF",
            "organize my Downloads folder",
        ),
        note="Deletes and bulk operations require confirmation. Executables are never opened automatically.",
    ),
    SlashCommand(
        "/system",
        "System",
        "Computer",
        status="Planned / Restricted",
        subcommands=("/system status", "/system diagnostics", "/system health"),
        examples=("show system status", "check disk space"),
        note="No shutdown, restart, or destructive system action is enabled here.",
        routing="help",
    ),
    SlashCommand(
        "/coding",
        "Coding",
        "Developer",
        status="Help only / conversational support",
        subcommands=("/coding status", "/coding help", "/coding diagnostics"),
        examples=("review this code", "explain this error", "run the tests"),
        note="Coding actions should keep repository changes reviewable.",
        routing="help",
    ),
    SlashCommand(
        "/git",
        "Git",
        "Developer",
        status="Planned / Partially available",
        subcommands=("/git status", "/git diff", "/git commit"),
        examples=("show git status", "summarize my changes"),
        note="Git commit and push actions require explicit user approval.",
        routing="help",
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
        routing="help",
    ),
    SlashCommand(
        "/voice",
        "Voice",
        "Personal",
        status="Help only / dedicated voice command available",
        subcommands=("/voice status", "/voice wake-word", "/voice loop"),
        examples=("what is my voice status", "start push to talk"),
        note="No always-on microphone starts from this chat command.",
        routing="help",
    ),
    SlashCommand(
        "/order",
        "Order",
        "Personal",
        status="Planned / Not configured",
        subcommands=("/order food", "/order grocery", "/order status"),
        examples=("order biryani", "reorder groceries"),
        note="Ordering is a future feature. Grandpa will not place real orders from this command.",
        routing="help",
    ),
    SlashCommand(
        "/automation",
        "Automation",
        "Automation",
        status="Planned / Permission-gated",
        subcommands=("/automation status", "/automation help", "/automation workflows"),
        examples=(
            "create a workflow for my morning setup",
            "show automation diagnostics",
        ),
        note="Automation must remain explicit, local, and confirmation-gated.",
        routing="help",
    ),
)

COMMAND_BY_NAME = {command.name: command for command in SLASH_COMMANDS}


def command_groups() -> dict[str, list[SlashCommand]]:
    groups: dict[str, list[SlashCommand]] = {
        category: [] for category in CATEGORY_ORDER
    }
    for command in SLASH_COMMANDS:
        groups.setdefault(command.category, []).append(command)
    return groups


def top_level_commands() -> list[SlashCommand]:
    return list(SLASH_COMMANDS)


def command_names() -> list[str]:
    return [command.name for command in SLASH_COMMANDS]


def validate_command_registry() -> list[str]:
    """Return deterministic metadata consistency errors for slash commands."""

    errors: list[str] = []
    names = command_names()
    if len(names) != len(set(names)):
        errors.append("slash command names must be unique")
    for command in SLASH_COMMANDS:
        if command.category not in CATEGORY_ORDER:
            errors.append(f"{command.name} has unknown category {command.category!r}")
        if command.routing not in {"local", "help"}:
            errors.append(f"{command.name} has unknown routing {command.routing!r}")
        if command.routing == "help" and not any(
            marker in command.status.casefold()
            for marker in ("help", "planned", "not configured")
        ):
            errors.append(f"{command.name} help-only routing is not labeled")
        for preview in (*command.subcommands, *command.preview):
            if (
                preview.startswith("/")
                and preview.split(maxsplit=1)[0] not in COMMAND_BY_NAME
            ):
                errors.append(
                    f"{command.name} preview references unknown command {preview!r}"
                )
    return errors


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
    suggestions = "\n".join(["/help", "/memory", "/reminders", "/desktop", "/voice"])
    return f"Unknown command: {command_name}\n\nTry:\n{suggestions}"
