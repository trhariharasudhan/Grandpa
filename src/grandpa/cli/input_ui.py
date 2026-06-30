from __future__ import annotations

import subprocess
from typing import Optional

from grandpa.cli.slash_commands import (
    command_preview_options,
    get_command,
    top_level_commands,
)

try:
    from prompt_toolkit import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, VSplit, Window
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.styles import Style
except ImportError:  # pragma: no cover - exercised through monkeypatched fallback
    Application = None  # type: ignore[assignment]
    Buffer = None  # type: ignore[assignment]
    KeyBindings = None  # type: ignore[assignment]
    Layout = None  # type: ignore[assignment]
    HSplit = None  # type: ignore[assignment]
    VSplit = None  # type: ignore[assignment]
    Window = None  # type: ignore[assignment]
    BufferControl = None  # type: ignore[assignment]
    FormattedTextControl = None  # type: ignore[assignment]
    Style = None  # type: ignore[assignment]

PROMPT_TOOLKIT_AVAILABLE = Application is not None

LINE = "─" * 110


def read_chat_input() -> Optional[str]:
    if not PROMPT_TOOLKIT_AVAILABLE:
        return _read_chat_input_fallback()

    buffer = Buffer()
    buffer_control = BufferControl(buffer=buffer)
    selected_top_index = {"value": 0}
    selected_preview_index = {"value": 0}

    def top_matches() -> list[tuple[str, str]]:
        text = buffer.text.strip()
        return _top_level_suggestions(text)

    def preview_matches() -> list[tuple[str, str]]:
        current_top = top_matches()
        if not current_top:
            return []
        selected_top_index["value"] = min(selected_top_index["value"], len(current_top) - 1)
        command_name = current_top[selected_top_index["value"]][0]
        return _command_preview_options(command_name)

    def apply_selected():
        current_preview = preview_matches()
        if current_preview:
            selected_preview_index["value"] = min(selected_preview_index["value"], len(current_preview) - 1)
            buffer.text = current_preview[selected_preview_index["value"]][0]
            buffer.cursor_position = len(buffer.text)
            return True

        current_top = top_matches()
        if not current_top:
            return False

        index = selected_top_index["value"]
        if index >= len(current_top):
            index = 0

        buffer.text = current_top[index][0]
        buffer.cursor_position = len(buffer.text)
        return True

    def command_preview():
        current_top = top_matches()
        if not current_top:
            return []

        selected_top_index["value"] = min(selected_top_index["value"], len(current_top) - 1)
        current_preview = preview_matches()
        if current_preview:
            selected_preview_index["value"] = min(selected_preview_index["value"], len(current_preview) - 1)

        rows = [("", "\n")]
        rows.append(("class:title", "Slash Commands\n"))
        for i, (_command, label) in enumerate(current_top):
            style = "class:current_command" if i == selected_top_index["value"] else "class:command"
            rows.append((style, f"{label}  "))
        rows.append(("", "\n\n"))

        selected_command = current_top[selected_top_index["value"]][0]
        selected_label = current_top[selected_top_index["value"]][1]
        preview_lines = _picker_preview_lines(selected_command, selected_label=selected_label)
        rows.append(("class:title", f"{preview_lines[0]}\n"))
        if len(preview_lines) > 1:
            for i, command in enumerate(preview_lines[1:]):
                if i == selected_preview_index["value"]:
                    rows.append(("class:current_arrow", "> "))
                    rows.append(("class:current_command", f"{command}\n"))
                else:
                    rows.append(("", "  "))
                    rows.append(("class:command", f"{command}\n"))
        else:
            rows.append(("class:command", f"{selected_command}\n"))

        return rows

    kb = KeyBindings()

    @kb.add("down")
    def _(event):
        current = preview_matches()
        if current:
            selected_preview_index["value"] = (selected_preview_index["value"] + 1) % len(current)

    @kb.add("up")
    def _(event):
        current = preview_matches()
        if current:
            selected_preview_index["value"] = (selected_preview_index["value"] - 1) % len(current)

    @kb.add("right")
    def _(event):
        current = top_matches()
        if current:
            selected_top_index["value"] = (selected_top_index["value"] + 1) % len(current)
            selected_preview_index["value"] = 0

    @kb.add("left")
    def _(event):
        current = top_matches()
        if current:
            selected_top_index["value"] = (selected_top_index["value"] - 1) % len(current)
            selected_preview_index["value"] = 0

    @kb.add("tab")
    def _(event):
        if apply_selected():
            event.app.exit(result=buffer.text)

    @kb.add("enter")
    def _(event):
        current = top_matches()
        text = buffer.text.strip()

        if current and text.startswith("/"):
            apply_selected()
            event.app.exit(result=buffer.text)
            return

        event.app.exit(result=buffer.text)

    @kb.add("c-c")
    def _(event):
        event.app.exit(result=None)

    root = HSplit(
        [
            Window(FormattedTextControl([("class:line", LINE)]), height=1),
            VSplit(
                [
                    Window(FormattedTextControl([("class:prompt", "> ")]), width=2),
                    Window(buffer_control, height=1),
                ],
                height=1,
            ),
            Window(FormattedTextControl([("class:line", LINE)]), height=1),
            Window(
                FormattedTextControl(command_preview),
                dont_extend_height=True,
            ),
        ]
    )

    style = Style.from_dict(
        {
            "line": "#666666",
            "prompt": "bold #ffffff",
            "title": "bold #ffc448",
            "command": "#6244c5",
            "desc": "#ffffff",
            "current_arrow": "bold #ffc448",
            "current_command": "bold #ffc448",
            "current_desc": "#ffffff",
        }
    )

    app = Application(
        layout=Layout(root, focused_element=buffer_control),
        key_bindings=kb,
        style=style,
        full_screen=False,
        erase_when_done=True,
    )

    return app.run()


def _read_chat_input_fallback(prompt: str = "You> ") -> Optional[str]:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def _slash_suggestions(text: str) -> list[tuple[str, str]]:
    if not text.startswith("/"):
        return []
    subcommands = _subcommand_suggestions(text)
    if subcommands:
        return subcommands
    return _top_level_suggestions(text)


def _top_level_suggestions(text: str) -> list[tuple[str, str]]:
    if not text.startswith("/"):
        return []
    query = text.split(maxsplit=1)[0]
    return [
        (command.name, command.display_label)
        for command in top_level_commands()
        if command.name.startswith(query)
    ]


def _subcommand_suggestions(text: str) -> list[tuple[str, str]]:
    command_name = text.split(maxsplit=1)[0]
    command = get_command(command_name)
    if command is None or not command.subcommands:
        return []
    if text == command_name:
        return [(subcommand, command.description) for subcommand in command.subcommands]
    return [
        (subcommand, command.description)
        for subcommand in command.subcommands
        if subcommand.startswith(text)
    ]


def _show_subcommands(text: str) -> bool:
    return bool(_subcommand_suggestions(text))


def _picker_preview_lines(command_name: str, *, selected_label: str | None = None) -> list[str]:
    items = [display for _value, display in _command_preview_options(command_name)]
    label = selected_label or _command_label(command_name)
    return [f"Selected: {label} ({command_name})", *(items or [command_name])]


def _command_label(command_name: str) -> str:
    command = get_command(command_name)
    return command.display_label if command else command_name


def _command_preview_options(command_name: str) -> list[tuple[str, str]]:
    if command_name == "/model":
        return _model_preview_options()
    return [(item.command, item.label) for item in command_preview_options(command_name)]


def _model_preview_options() -> list[tuple[str, str]]:
    models = _installed_ollama_models()
    if not models:
        return [
            ("/model", "Model"),
            ("/model", "No local models found"),
            ("/model", "Install with: ollama pull qwen2.5:3b"),
        ]
    return [("/model", "Model"), *((f"/model {model}", model) for model in models)]


def _installed_ollama_models() -> list[str]:
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    models: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def select_from_list(title: str, items: list[str]) -> Optional[str]:
    if not items:
        return None
    if not PROMPT_TOOLKIT_AVAILABLE:
        return items[0]

    selected_index = {"value": 0}

    def preview():
        rows = [
            ("class:title", f"{title}\n\n"),
        ]

        for i, item in enumerate(items):
            if i == selected_index["value"]:
                rows.append(("class:current_arrow", "> "))
                rows.append(("class:current_command", f"{item}\n"))
            else:
                rows.append(("", "  "))
                rows.append(("class:command", f"{item}\n"))

        return rows

    kb = KeyBindings()

    @kb.add("down")
    def _(event):
        selected_index["value"] = (selected_index["value"] + 1) % len(items)

    @kb.add("up")
    def _(event):
        selected_index["value"] = (selected_index["value"] - 1) % len(items)

    @kb.add("enter")
    def _(event):
        event.app.exit(result=items[selected_index["value"]])

    @kb.add("escape")
    def _(event):
        event.app.exit(result=None)

    @kb.add("c-c")
    def _(event):
        event.app.exit(result=None)

    root = HSplit(
        [
            Window(FormattedTextControl([("class:line", LINE)]), height=1),
            Window(FormattedTextControl(preview), dont_extend_height=True),
            Window(FormattedTextControl([("class:line", LINE)]), height=1),
        ]
    )

    style = Style.from_dict(
        {
            "line": "#666666",
            "title": "bold #ffc448",
            "command": "#6244c5",
            "current_arrow": "bold #ffc448",
            "current_command": "bold #ffc448",
        }
    )

    app = Application(
        layout=Layout(root),
        key_bindings=kb,
        style=style,
        full_screen=False,
        erase_when_done=True,
    )

    return app.run()
