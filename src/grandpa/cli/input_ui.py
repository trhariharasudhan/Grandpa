from __future__ import annotations

from typing import Optional

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.styles import Style

COMMANDS = [
    ("/help", "Commands"),
    ("/model", "Model info"),
    ("/mode", "Change mode"),
    ("/history", "Chat history"),
    ("/clear", "Clear chat"),
    ("/memory", "Memory commands"),
    ("/voice", "Voice mode"),
    ("/files", "File assistant"),
    ("/tasks", "Task planner"),
    ("/browser", "Browser control"),
    ("/reminders", "Reminders"),
    ("/settings", "Settings"),
    ("/quit", "Exit"),
    ("/exit", "Exit"),
]

LINE = "─" * 110


def read_chat_input() -> Optional[str]:
    buffer = Buffer()
    buffer_control = BufferControl(buffer=buffer)
    selected_index = {"value": 0}

    def matches():
        text = buffer.text.strip()
        if not text.startswith("/"):
            return []
        return [(cmd, desc) for cmd, desc in COMMANDS if cmd.startswith(text)]

    def apply_selected():
        current = matches()
        if not current:
            return False

        index = selected_index["value"]
        if index >= len(current):
            index = 0

        buffer.text = current[index][0]
        buffer.cursor_position = len(buffer.text)
        return True

    def command_preview():
        current = matches()
        if not current:
            return []

        selected_index["value"] = min(selected_index["value"], len(current) - 1)

        rows = [("", "\n")]

        for i, (command, desc) in enumerate(current):
            if i == selected_index["value"]:
                rows.append(("class:current_arrow", "> "))
                rows.append(("class:current_command", f"{command:<12}"))
                rows.append(("class:current_desc", f" {desc}\n"))
            else:
                rows.append(("", "  "))
                rows.append(("class:command", f"{command:<12}"))
                rows.append(("class:desc", f" {desc}\n"))

        return rows

    kb = KeyBindings()

    @kb.add("down")
    def _(event):
        current = matches()
        if current:
            selected_index["value"] = (selected_index["value"] + 1) % len(current)

    @kb.add("up")
    def _(event):
        current = matches()
        if current:
            selected_index["value"] = (selected_index["value"] - 1) % len(current)

    @kb.add("tab")
    def _(event):
        current = matches()
        if current:
            index = selected_index["value"]
            if index >= len(current):
                index = 0
            event.app.exit(result=current[index][0])

    @kb.add("enter")
    def _(event):
        current = matches()
        text = buffer.text.strip()

        if current and text == "/":
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

def select_from_list(title: str, items: list[str]) -> Optional[str]:
    if not items:
        return None

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
