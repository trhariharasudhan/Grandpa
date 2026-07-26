from __future__ import annotations

import subprocess
import sys
from typing import Iterable, Optional

from grandpa.cli.slash_commands import (
    command_preview_options,
    get_command,
    top_level_commands,
)

try:
    from prompt_toolkit import Application, PromptSession
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.document import Document
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import (
        ConditionalContainer,
        HSplit,
        VSplit,
        Window,
    )
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.styles import Style
except ImportError:  # pragma: no cover - exercised through monkeypatched fallback
    Application = None  # type: ignore[assignment]
    PromptSession = None  # type: ignore[assignment]
    Buffer = None  # type: ignore[assignment]
    Completer = object  # type: ignore[assignment,misc]
    Completion = None  # type: ignore[assignment]
    Condition = None  # type: ignore[assignment]
    Document = None  # type: ignore[assignment]
    KeyBindings = None  # type: ignore[assignment]
    Layout = None  # type: ignore[assignment]
    ConditionalContainer = None  # type: ignore[assignment]
    HSplit = None  # type: ignore[assignment]
    VSplit = None  # type: ignore[assignment]
    Window = None  # type: ignore[assignment]
    BufferControl = None  # type: ignore[assignment]
    FormattedTextControl = None  # type: ignore[assignment]
    Style = None  # type: ignore[assignment]

PROMPT_TOOLKIT_AVAILABLE = Application is not None and PromptSession is not None

USER_PROMPT = "> "
USER_PROMPT_COLOR = "#6244c5"
ASSISTANT_PROMPT_COLOR = "#ffc448"
PICKER_HIGHLIGHT_COLOR = "#ffc448"
PICKER_COMMAND_COLOR = "#6244c5"
PICKER_TEXT_COLOR = "#ffffff"
PICKER_BACKGROUND_COLOR = "#181818"
PICKER_BASE_STYLE = f"bg:{PICKER_BACKGROUND_COLOR} {PICKER_TEXT_COLOR}"
PICKER_TITLE_STYLE = f"bg:{PICKER_BACKGROUND_COLOR} bold {PICKER_HIGHLIGHT_COLOR}"
PICKER_COMMAND_STYLE = f"bg:{PICKER_BACKGROUND_COLOR} {PICKER_COMMAND_COLOR}"
PICKER_CURRENT_STYLE = f"bg:{PICKER_BACKGROUND_COLOR} bold {PICKER_HIGHLIGHT_COLOR}"
PICKER_DIM_STYLE = f"bg:{PICKER_BACKGROUND_COLOR} #8f8f9a"


def read_chat_input() -> Optional[str]:
    if not PROMPT_TOOLKIT_AVAILABLE or not sys.stdin.isatty():
        return _read_chat_input_fallback()

    picker_state = SlashPickerState()
    bindings = _chat_key_bindings(picker_state)
    buffer = Buffer(multiline=False)
    input_control = BufferControl(buffer=buffer)
    app = _slash_input_application(buffer, input_control, picker_state, bindings)
    try:
        return app.run()
    except (EOFError, KeyboardInterrupt):
        return None


def _slash_input_application(
    buffer: Buffer,
    input_control: BufferControl,
    picker_state: "SlashPickerState",
    bindings,
):
    prompt_control = FormattedTextControl([("class:prompt", USER_PROMPT)])
    input_row = VSplit(
        [
            Window(prompt_control, width=len(USER_PROMPT), height=1),
            Window(input_control, height=1),
        ]
    )
    popup = ConditionalContainer(
        Window(
            FormattedTextControl(
                lambda: _picker_toolbar_fragments(buffer.text, picker_state)
            ),
            style="class:picker.background",
            char=" ",
            dont_extend_height=True,
        ),
        filter=Condition(lambda: buffer.text.startswith("/")),
    )
    root = HSplit([input_row, popup])
    return Application(
        layout=Layout(root, focused_element=input_control),
        key_bindings=bindings,
        style=Style.from_dict(_picker_style_dict()),
        full_screen=False,
        erase_when_done=True,
    )


def _picker_style_dict() -> dict[str, str]:
    return {
        "prompt": f"bold {USER_PROMPT_COLOR}",
        "picker.background": PICKER_BASE_STYLE,
        "picker.title": PICKER_TITLE_STYLE,
        "picker.command": PICKER_COMMAND_STYLE,
        "picker.text": PICKER_BASE_STYLE,
        "picker.current": PICKER_CURRENT_STYLE,
        "picker.dim": PICKER_DIM_STYLE,
    }


class SlashPickerState:
    def __init__(self) -> None:
        self.top_index = 0
        self.preview_index = 0

    def reset_preview(self) -> None:
        self.preview_index = 0


class SlashCommandCompleter(Completer):
    """Live slash command completer for the unified chat input line."""

    def __init__(self, picker_state: SlashPickerState | None = None) -> None:
        self._picker_state = picker_state or SlashPickerState()

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:
        if Completion is None:
            return

        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        for value, label, description in _completion_candidates(text, self._picker_state):
            yield Completion(
                value,
                start_position=-len(text),
                display=label,
                display_meta=description,
            )


def _chat_key_bindings(picker_state: SlashPickerState):
    if KeyBindings is None:
        return None

    bindings = KeyBindings()

    @bindings.add("left")
    def _(event):
        text = event.current_buffer.text
        commands = _top_level_suggestions("/")
        if text.startswith("/") and commands:
            picker_state.top_index = (picker_state.top_index - 1) % len(commands)
            picker_state.reset_preview()
            event.app.invalidate()
            return
        event.current_buffer.cursor_left()

    @bindings.add("right")
    def _(event):
        text = event.current_buffer.text
        commands = _top_level_suggestions("/")
        if text.startswith("/") and commands:
            picker_state.top_index = (picker_state.top_index + 1) % len(commands)
            picker_state.reset_preview()
            event.app.invalidate()
            return
        event.current_buffer.cursor_right()

    @bindings.add("up")
    def _(event):
        text = event.current_buffer.text
        preview = _selected_preview_options(text, picker_state)
        if text.startswith("/") and preview:
            picker_state.preview_index = (picker_state.preview_index - 1) % len(preview)
            event.app.invalidate()

    @bindings.add("down")
    def _(event):
        text = event.current_buffer.text
        preview = _selected_preview_options(text, picker_state)
        if text.startswith("/") and preview:
            picker_state.preview_index = (picker_state.preview_index + 1) % len(preview)
            event.app.invalidate()

    @bindings.add("tab")
    def _(event):
        if _apply_picker_selection(event.current_buffer, picker_state):
            return
        state = event.current_buffer.complete_state
        if state and state.current_completion is not None:
            event.current_buffer.apply_completion(state.current_completion)

    @bindings.add("enter")
    def _(event):
        state = event.current_buffer.complete_state
        if state and state.current_completion is not None:
            event.current_buffer.apply_completion(state.current_completion)
            return
        if _apply_picker_selection(event.current_buffer, picker_state):
            event.app.invalidate()
            return
        event.app.exit(result=event.current_buffer.text)

    @bindings.add("c-c")
    @bindings.add("c-d")
    def _(event):
        event.app.exit(result=None)

    return bindings


def _should_complete_while_typing() -> bool:
    return True


def _read_chat_input_fallback(prompt: str = USER_PROMPT) -> Optional[str]:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def _completion_candidates(
    text: str,
    picker_state: SlashPickerState | None = None,
) -> list[tuple[str, str, str]]:
    if not text.startswith("/"):
        return []
    if text == "/":
        return _top_level_completion_candidates(text)
    preview = _preview_completion_candidates(text, picker_state)
    if preview:
        return preview
    return _top_level_completion_candidates(text)


def _top_level_completion_candidates(text: str) -> list[tuple[str, str, str]]:
    query = text.split(maxsplit=1)[0].lower()
    return [
        (command.name, command.display_label, command.description)
        for command in top_level_commands()
        if command.name.startswith(query)
    ]


def _preview_completion_candidates(
    text: str,
    picker_state: SlashPickerState | None = None,
) -> list[tuple[str, str, str]]:
    command_name = text.split(maxsplit=1)[0].lower()
    command = get_command(command_name)
    if command is None:
        return []
    options = _command_preview_options(command_name)
    if not options:
        return []
    if text == command_name:
        return [(value, label, command.description) for value, label in options]
    return [
        (value, label, command.description)
        for value, label in options
        if value.lower().startswith(text.lower())
    ]


def _slash_suggestions(text: str) -> list[tuple[str, str]]:
    if not text.startswith("/"):
        return []
    preview = _preview_completion_candidates(text)
    if preview:
        return [(value, label) for value, label, _description in preview]
    return _top_level_suggestions(text)


def _top_level_suggestions(text: str) -> list[tuple[str, str]]:
    return [
        (value, label)
        for value, label, _description in _top_level_completion_candidates(text)
    ]


def _subcommand_suggestions(text: str) -> list[tuple[str, str]]:
    return [
        (value, description)
        for value, _label, description in _preview_completion_candidates(text)
    ]


def _show_subcommands(text: str) -> bool:
    return bool(_subcommand_suggestions(text))


def _picker_preview_lines(
    command_name: str,
    *,
    selected_label: str | None = None,
    raw: bool = False,
) -> list[str]:
    options = _command_preview_options(command_name)
    if raw:
        return [value for value, _display in options] or [command_name]
    return [_preview_display_label(value, display) for value, display in options] or [
        selected_label or _command_label(command_name)
    ]


def _picker_toolbar_lines(
    text: str,
    picker_state: SlashPickerState | None = None,
) -> list[str]:
    if not text.startswith("/"):
        return []
    state = picker_state or SlashPickerState()
    commands = _top_level_suggestions("/")
    if not commands:
        return []
    state.top_index = min(state.top_index, len(commands) - 1)
    selected_command = _selected_top_level_command(text, state) or commands[state.top_index][0]
    preview = _command_preview_options(selected_command)
    state.preview_index = min(state.preview_index, max(len(preview) - 1, 0))
    preview_values = [
        _preview_display_label(value, label) for value, label in preview
    ] or [_command_label(selected_command)]
    lines = [
        "Slash Commands",
        "",
        "  ".join(label for _command, label in commands),
        "",
    ]
    for index, value in enumerate(preview_values):
        marker = "> " if index == state.preview_index else "  "
        lines.append(f"{marker}{value}")
    return lines


def _picker_toolbar_fragments(
    text: str,
    picker_state: SlashPickerState,
) -> list[tuple[str, str]]:
    lines = _picker_toolbar_lines(text, picker_state)
    if not lines:
        return []
    fragments: list[tuple[str, str]] = []
    for line_number, line in enumerate(lines):
        if line_number == 0:
            style = "class:picker.title"
        elif line_number == 2:
            style = "class:picker.command"
        elif line:
            style = "class:picker.text"
        else:
            style = "class:picker.background"
        if line.startswith("> "):
            fragments.append(("class:picker.current", line))
        else:
            fragments.append((style, line))
        fragments.append(("class:picker.background", "\n"))
    return fragments


def _selected_top_level_command(text: str, picker_state: SlashPickerState) -> str | None:
    if not text.startswith("/"):
        return None
    command_name = text.split(maxsplit=1)[0].lower()
    if command_name != "/" and get_command(command_name) is not None:
        return command_name
    commands = _top_level_suggestions("/")
    if not commands:
        return None
    picker_state.top_index = min(picker_state.top_index, len(commands) - 1)
    return commands[picker_state.top_index][0]


def _selected_preview_options(
    text: str,
    picker_state: SlashPickerState,
) -> list[tuple[str, str]]:
    command = _selected_top_level_command(text, picker_state)
    if command is None:
        return []
    return _command_preview_options(command)


def _apply_picker_selection(buffer, picker_state: SlashPickerState) -> bool:
    text = buffer.text
    if not text.startswith("/"):
        return False
    preview = _selected_preview_options(text, picker_state)
    if preview:
        picker_state.preview_index = min(picker_state.preview_index, len(preview) - 1)
        buffer.text = preview[picker_state.preview_index][0]
    else:
        command = _selected_top_level_command(text, picker_state)
        if command is None:
            return False
        buffer.text = command
    buffer.cursor_position = len(buffer.text)
    return True


def _command_label(command_name: str) -> str:
    command = get_command(command_name)
    return command.display_label if command else command_name


def _preview_display_label(command_value: str, fallback_label: str | None = None) -> str:
    if not command_value.startswith("/"):
        return fallback_label or command_value
    parts = command_value.split(maxsplit=1)
    if parts[0] == "/model" and fallback_label is not None:
        return fallback_label
    label = _command_label(parts[0])
    if len(parts) == 1:
        return label
    return f"{label} {parts[1]}"


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
    if not PROMPT_TOOLKIT_AVAILABLE or not sys.stdin.isatty():
        return items[0]

    session = PromptSession(
        completer=_ListCompleter(items),
        complete_while_typing=True,
        style=Style.from_dict(
            {
                "prompt": f"bold {USER_PROMPT_COLOR}",
                "completion-menu.completion.current": "bold #111111 bg:#ffc448",
            }
        ),
    )
    try:
        selected = session.prompt([("class:prompt", f"{title}> ")])
    except (EOFError, KeyboardInterrupt):
        return None
    return selected if selected in items else None


class _ListCompleter(Completer):
    def __init__(self, items: list[str]) -> None:
        self._items = items

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:
        if Completion is None:
            return
        text = document.text_before_cursor.lower()
        for item in self._items:
            if item.lower().startswith(text):
                yield Completion(item, start_position=-len(document.text_before_cursor))
