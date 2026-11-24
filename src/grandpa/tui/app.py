"""Grandpa's full-screen terminal interface (bare ``grandpa``).

The layout follows the terminal assistants people already know (Claude Code,
Gemini CLI, opencode): the conversation scrolls in the middle, a framed input
box sits at the bottom, slash commands pop up as you type ``/``, and a status
line says what Grandpa is doing. On top of that, things those tools don't do:

* **Talk instead of typing** (F2): speak, and the words land in the input box.
* **Hear the reply** (F4 or ``/speak``): Grandpa reads replies in its own voice.
* **Attach files** with ``@path``: the file's text goes with the message.
* **Copy, export, retry**: F3 copies the last reply, ``/export`` saves the
  conversation as Markdown, F5 asks the last question again.
* **Dark and light themes** (Ctrl+T or ``/theme``), drawn only from the
  project's seven colours.
* A bell when a long reply finishes, so you can look away while it thinks.

Questions Grandpa must ask before acting ("Delete note 'x'? [y/N]") appear as
a bar with Yes / No buttons, so nothing risky happens without an answer.

The conversation itself is the existing chat engine, run by
:class:`grandpa.tui.bridge.ChatBridge`. Commands handled here and never sent
to the engine are listed in :data:`LOCAL_COMMANDS`.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Button, Label, OptionList, Static, TextArea
from textual.widgets.option_list import Option

import grandpa
from grandpa.tui.bridge import ChatBridge, Question, UiHooks, clean_terminal_text
from grandpa.tui.console_guard import ConsoleModeGuard
from grandpa.tui.helpers import (
    Turn,
    copy_text,
    expand_file_mentions,
    export_markdown,
    file_suggestions,
    mention_at_cursor,
)
from grandpa.tui.themes import (
    THEMES,
    ThemeColors,
    save_settings,
    saved_theme_name,
    textual_theme,
)
from grandpa.tui.voice import PushToTalk, ReplyVoice

#: Handled by the interface itself; never sent to the chat engine.
LOCAL_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/theme", "Switch dark / light theme (/theme dark, /theme light)"),
    ("/talk", "Speak your message instead of typing (F2)"),
    ("/speak", "Read Grandpa's replies aloud (/speak on, /speak off)"),
    ("/copy", "Copy Grandpa's last reply (F3)"),
    ("/retry", "Ask the last message again (F5)"),
    ("/export", "Save this conversation as a Markdown file"),
    ("/keys", "Keyboard shortcuts (F1)"),
)

#: Kept for callers that imported the old name; built from the registry below.
SLASH_COMMANDS: tuple[tuple[str, str], ...] = ()

LONG_REPLY_SECONDS = 15.0


def _registry_commands() -> list[tuple[str, str, tuple[str, ...]]]:
    """``(name, description, subcommands)`` for every working engine command."""
    try:
        from grandpa.cli.slash_commands import SLASH_COMMANDS as REGISTRY
    except Exception:  # noqa: BLE001
        return []
    found = []
    for command in REGISTRY:
        if not command.implemented or command.name == "/quit":
            continue
        found.append((command.name, command.description, tuple(command.subcommands)))
    return found


def all_commands() -> list[tuple[str, str, tuple[str, ...]]]:
    local = [(name, about, ()) for name, about in LOCAL_COMMANDS]
    registry = _registry_commands()
    primary = {"/help", "/clear", "/model", "/voice", "/memory", "/status", "/exit"}
    registry.sort(key=lambda item: (item[0] not in primary, item[0]))
    return registry[:1] + local + registry[1:]


SLASH_COMMANDS = tuple((name, about) for name, about, _ in all_commands())

_SUBCOMMAND_TYPING = re.compile(r"^(/[\w-]+) (\S*)$")
# "Model changed to Grandpa Fast (grandpa-fast:latest)." or the automatic
# switch "... so Grandpa Fast (grandpa-fast:latest) is answering."
_MODEL_SWITCH = re.compile(r"(?:Model changed to|so)[^()\n]*\(([\w.:/\-]+)\)")


def matching_commands(text: str) -> list[tuple[str, str]]:
    """Completions for what was typed.

    ``/`` alone lists every command; ``/mem`` narrows it; ``/memory `` (with a
    space) lists that command's subcommands.
    """
    if not text.startswith("/") or "\n" in text:
        return []
    commands = all_commands()
    if " " not in text:
        typed = text.lower()
        return [(name, about) for name, about, _ in commands if name.startswith(typed)]
    match = _SUBCOMMAND_TYPING.match(text)
    if not match:
        return []
    for name, _about, subs in commands:
        if name == match.group(1).lower():
            typed = text.lower()
            return [
                (sub, "")
                for sub in subs
                if sub.lower().startswith(typed) and sub != text
            ]
    return []


def completion_text(choice: str) -> str:
    """What goes in the box for a picked completion: stop before ``<arg>``."""
    if "<" in choice:
        return choice[: choice.index("<")]
    return choice


class InputHistory:
    """Up/Down through earlier messages, kept between sessions."""

    def __init__(self, path: Path | None, limit: int = 500) -> None:
        self.path = path
        self.limit = limit
        self.items: list[str] = []
        self.index: int | None = None
        if path and path.exists():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                self.items = [line.replace("\\n", "\n") for line in lines if line][
                    -limit:
                ]
            except OSError:
                self.items = []

    def add(self, text: str) -> None:
        self.index = None
        if not text.strip() or (self.items and self.items[-1] == text):
            return
        self.items.append(text)
        self.items = self.items[-self.limit :]
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(
                    "\n".join(i.replace("\n", "\\n") for i in self.items) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass

    def previous(self) -> str | None:
        if not self.items:
            return None
        self.index = (
            len(self.items) - 1 if self.index is None else max(0, self.index - 1)
        )
        return self.items[self.index]

    def next(self) -> str | None:
        if self.index is None:
            return None
        self.index += 1
        if self.index >= len(self.items):
            self.index = None
            return ""
        return self.items[self.index]


class PromptBox(TextArea):
    """The input box: Enter sends, Shift+Enter / Alt+Enter / Ctrl+J add a line."""

    BINDINGS = [
        Binding("enter", "submit", "Send", show=False, priority=True),
        Binding(
            "shift+enter,alt+enter,ctrl+j",
            "newline",
            "New line",
            show=False,
            priority=True,
        ),
    ]

    def action_submit(self) -> None:
        self.app.submit_prompt()  # type: ignore[attr-defined]

    def action_newline(self) -> None:
        self.insert("\n")

    async def _on_key(self, event: events.Key) -> None:
        app = self.app
        if event.key == "up" and self.cursor_location[0] == 0:
            if app.slash_visible():  # type: ignore[attr-defined]
                app.move_slash(-1)  # type: ignore[attr-defined]
            else:
                app.history_step(-1)  # type: ignore[attr-defined]
            event.prevent_default()
            event.stop()
            return
        if (
            event.key == "down"
            and self.cursor_location[0] == self.document.line_count - 1
        ):
            if app.slash_visible():  # type: ignore[attr-defined]
                app.move_slash(1)  # type: ignore[attr-defined]
            else:
                app.history_step(1)  # type: ignore[attr-defined]
            event.prevent_default()
            event.stop()
            return
        if event.key == "tab" and app.slash_visible():  # type: ignore[attr-defined]
            app.complete_slash()  # type: ignore[attr-defined]
            event.prevent_default()
            event.stop()
            return
        await super()._on_key(event)


# --- colours ---------------------------------------------------------------------


def fit_text(text: Text, colors: ThemeColors) -> Text:
    """``text`` with every colour replaced by the nearest one the theme allows."""

    def fit(style) -> Style:
        if isinstance(style, str):
            try:
                style = Style.parse(style)
            except Exception:  # noqa: BLE001 - a theme name Rich can't parse alone
                return Style()
        changes = {}
        if style.color is not None and not style.color.is_default:
            changes["color"] = colors.fit(style.color.get_truecolor().hex)
        if style.bgcolor is not None and not style.bgcolor.is_default:
            changes["bgcolor"] = colors.fit(
                style.bgcolor.get_truecolor().hex, background=True
            )
        return style + Style(**changes) if changes else style

    fitted = Text(text.plain, style=fit(text.style) if text.style else "", end="")
    for span in text.spans:
        fitted.stylize(fit(span.style), span.start, span.end)
    return fitted


# --- highlights ------------------------------------------------------------------------

#: What each kind of highlight is drawn in (a key of ``ThemeColors.accents``).
HIGHLIGHT_ROLES = {
    "marker": "purple",  # 1.  2)  -  •
    "label": "blue",  # Model: ...   Status: ...
    "good": "green",  # ✓ done, connected, active
    "bad": "red",  # ✗ failed, error, not installed
    "link": "blue",
    "code": "green",  # `inline code`
}

_HIGHLIGHTS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("marker", re.compile(r"^[ \t]*(\d{1,3}[.)]|[-•*▪●○◦])(?=[ \t])", re.M), 1),
    (
        "label",
        re.compile(
            r"^[ \t]*(?:\d{1,3}[.)][ \t]+|[-•*][ \t]+)?([A-Z][\w /()'-]{0,28}):(?=[ \t])",
            re.M,
        ),
        1,
    ),
    ("code", re.compile(r"`([^`\n]+)`"), 0),
    ("link", re.compile(r"https?://[^\s)>\]]+"), 0),
    (
        "good",
        re.compile(
            r"✓|✔|\b(?:done|ok|OK|connected|Connected|active|Active|ready|Ready|"
            r"installed|Installed|enabled|Enabled|success|passed)\b"
        ),
        0,
    ),
    (
        "bad",
        re.compile(
            r"✗|✘|\b(?:failed|Failed|error|Error|not installed|not available|"
            r"not connected|disabled|Disabled|blocked|Blocked)\b"
        ),
        0,
    ),
)


def highlight_reply(text: Text, colors: ThemeColors) -> Text:
    """Colour the parts of a reply worth spotting, one colour per kind.

    Only plain stretches are coloured: anything the engine already styled
    (markdown headings, code blocks) keeps its own colour.
    """
    if not colors.accents:
        return text
    styled = [
        (span.start, span.end)
        for span in text.spans
        if not isinstance(span.style, str)
        and span.style.color is not None
        and span.style.color.get_truecolor().hex != _hex(colors.grandpa)
        and span.style.color.get_truecolor().hex != _hex(colors.text)
    ]

    def free(start: int, end: int) -> bool:
        return not any(a < end and start < b for a, b in styled)

    plain = text.plain
    for role, pattern, group in _HIGHLIGHTS:
        colour = colors.accents[HIGHLIGHT_ROLES[role]]
        style = Style(
            color=colour, bold=role in {"marker", "label"}, underline=role == "link"
        )
        for match in pattern.finditer(plain):
            start, end = match.span(group)
            if start < end and free(start, end):
                text.stylize(style, start, end)
                styled.append((start, end))
    return text


def _hex(colour: str) -> str:
    return colour.lower()


# --- conversation widgets ----------------------------------------------------------


class Message(Static):
    """Base for one entry in the conversation."""

    def repaint(self, colors: ThemeColors) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class UserMessage(Message):
    """What the user sent, in the user colour."""

    def __init__(self, text: str, at: datetime, attached: Iterable[str] = ()) -> None:
        super().__init__("", classes="msg user")
        self.text = text
        self.at = at
        self.attached = list(attached)

    def repaint(self, colors: ThemeColors) -> None:
        body = Text()
        body.append("You", style=Style(color=colors.user, bold=True))
        body.append(f"  {self.at:%H:%M}\n", style=colors.muted)
        body.append(self.text, style=colors.user)
        for name in self.attached:
            body.append(f"\n+ {name}", style=colors.muted)
        self.update(body)


class OutputBlock(Message):
    """What the chat engine printed: a Grandpa reply, or startup/system text."""

    def __init__(self, role: str = "system") -> None:
        super().__init__("", classes=f"msg block {role}")
        self.role = role
        self.raw = ""
        self.at = datetime.now()
        self.seconds: float | None = None
        self._colors: ThemeColors | None = None

    def feed(self, text: str) -> None:
        self.raw += text
        if self._colors is not None:
            self.repaint(self._colors)

    def plain(self) -> str:
        cleaned = clean_terminal_text(self.raw)
        lines = [line.rstrip() for line in Text.from_ansi(cleaned).plain.split("\n")]
        return "\n".join(lines).strip("\n")

    def repaint(self, colors: ThemeColors) -> None:
        self._colors = colors
        base = colors.grandpa if self.role == "grandpa" else colors.text
        cleaned = clean_terminal_text(self.raw).rstrip("\n").lstrip("\n")
        body = Text.from_ansi(cleaned, style=base)
        body = fit_text(body, colors)
        if self.role == "grandpa":
            body = highlight_reply(body, colors)
        body.rstrip()
        out = Text()
        if self.role == "grandpa":
            out.append("Grandpa", style=Style(color=colors.grandpa, bold=True))
            out.append(f"  {self.at:%H:%M}", style=colors.muted)
            if self.seconds is not None:
                out.append(f"  ·  {self.seconds:.1f}s", style=colors.muted)
            out.append("\n")
        out.append_text(body)
        self.update(out)


HELP_TEXT = (
    ("Enter", "send"),
    ("Shift+Enter / Alt+Enter", "new line"),
    ("↑ / ↓", "earlier messages"),
    ("/", "commands  (/memory then space: its subcommands)"),
    ("@file", "attach a text file to the message"),
    ("F2", "talk: speak instead of typing"),
    ("F3", "copy Grandpa's last reply"),
    ("F4", "read replies aloud on / off"),
    ("F5", "ask the last message again"),
    ("F6", "switch model (your Grandpa models)"),
    ("Ctrl+T", "dark / light theme"),
    ("PgUp / PgDn", "scroll the conversation"),
    ("Esc / Ctrl+C", "cancel the reply, or answer No"),
    ("Ctrl+L", "clear the screen"),
    ("Ctrl+D", "quit"),
)


class GrandpaApp(App):
    """The full-screen Grandpa terminal app."""

    TITLE = "Grandpa"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: $background; }
    #header { height: 1; padding: 0 1; background: $panel; }
    #log { padding: 0 1; scrollbar-size-vertical: 1; }
    .msg { margin: 0 0 1 0; padding: 0 0 0 1; }
    .msg.user { border-left: outer $secondary; }
    .msg.grandpa { border-left: outer $accent; }
    .msg.system { padding: 0; }
    #help { display: none; height: auto; margin: 0 1; padding: 0 1;
            border: round $primary; background: $surface; }
    #help.visible { display: block; }
    #question { display: none; height: auto; padding: 0 1; margin: 0 1;
                border: round $warning; background: $surface; }
    #question.visible { display: block; }
    #question-text { width: 1fr; color: $warning; padding: 1 0 0 0; }
    #question Button { min-width: 10; margin: 0 0 0 1; }
    #slash { display: none; height: auto; max-height: 12; margin: 0 1;
             border: round $border; background: $surface; }
    #slash.visible { display: block; }
    #choices { display: none; height: auto; max-height: 12; margin: 0 1;
               border: round $primary; background: $surface; }
    #choices.visible { display: block; }
    #prompt { height: auto; min-height: 3; max-height: 10; margin: 0 1;
              border: round $border; background: $surface; color: $foreground; }
    #prompt:focus { border: round $primary; }
    #prompt .text-area--cursor-line { background: transparent; }
    #status { height: 1; padding: 0 2; }
    """
    BINDINGS = [
        Binding("ctrl+c,escape", "cancel", "Cancel reply", show=False, priority=True),
        Binding("ctrl+d", "quit_grandpa", "Quit", show=False, priority=True),
        Binding("ctrl+l", "clear_screen", "Clear screen", show=False),
        Binding("ctrl+t", "toggle_theme", "Theme", show=False, priority=True),
        Binding("f1", "toggle_help", "Keys", show=False, priority=True),
        Binding("f2,ctrl+space", "talk", "Talk", show=False, priority=True),
        Binding("f3", "copy_reply", "Copy reply", show=False, priority=True),
        Binding("f4", "toggle_speak", "Read aloud", show=False, priority=True),
        Binding("f5", "retry", "Retry", show=False, priority=True),
        Binding("f6", "pick_model", "Model", show=False, priority=True),
        Binding("pageup", "scroll_log(-1)", show=False, priority=True),
        Binding("pagedown", "scroll_log(1)", show=False, priority=True),
        Binding("y", "answer_yes", show=False),
        Binding("n", "answer_no", show=False),
    ]

    def __init__(
        self,
        *,
        chat_args: Iterable[str] = (),
        bridge: ChatBridge | None = None,
        theme_name: str | None = None,
    ):
        super().__init__()
        self._chat_args = list(chat_args)
        self.bridge = bridge
        self._block: OutputBlock | None = None
        self._question: Question | None = None
        self._busy_since: float | None = None
        self._spinner = 0
        self._exit_code = 0
        self._stopped = False
        self._notice: tuple[str, str, float] | None = None  # text, role, until
        self._level = 0.0
        self.turns: list[Turn] = []
        self.last_sent: str | None = None
        self.history = InputHistory(self._history_path())
        for colors in THEMES.values():
            self.register_theme(textual_theme(colors))
        self.palette = THEMES[theme_name or saved_theme_name()]
        self.theme = f"grandpa-{self.palette.name}"
        self.talk = PushToTalk(
            on_text=lambda t: self.call_from_thread(self._on_heard, t),
            on_error=lambda m: self.call_from_thread(self.notify_status, m, "error"),
            on_level=self._set_level,
        )
        self.reply_voice = ReplyVoice(
            on_error=lambda m: self.call_from_thread(self.notify_status, m, "error")
        )

    # --- layout ----------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        yield VerticalScroll(id="log")
        yield Static("", id="help")
        with Horizontal(id="question"):
            yield Label("", id="question-text")
            yield Button("Yes (y)", id="yes", variant="success")
            yield Button("No (n)", id="no", variant="error")
        yield OptionList(id="slash")
        yield OptionList(id="choices")
        yield PromptBox(
            id="prompt", soft_wrap=True, show_line_numbers=False, tab_behavior="focus"
        )
        yield Static("", id="status")

    def on_mount(self) -> None:
        prompt = self.query_one("#prompt", PromptBox)
        prompt.border_title = "Ask Grandpa anything · / commands · @ files · F2 talk"
        prompt.focus()
        self._paint_chrome()
        self.set_interval(0.12, self._tick)
        # Windows: if anything resets the console input mode, put it back, or
        # the classic Command Prompt starts echoing mouse reports as text.
        self._console_guard = ConsoleModeGuard()
        self._console_guard.capture()
        if self._console_guard.active:
            self.set_interval(0.2, self._console_guard.check)
        if self.bridge is None:
            width = max(60, self.size.width - 6)
            hooks = UiHooks(
                output=lambda text: self.call_from_thread(self._on_output, text),
                ready_for_input=lambda p: self.call_from_thread(self._on_ready, p),
                ask=lambda q: self.call_from_thread(self._on_question, q),
                finished=lambda code: self.call_from_thread(self._on_finished, code),
                turn=lambda role: self.call_from_thread(self._on_turn, role),
            )
            self.bridge = ChatBridge(hooks, width=width, chat_args=self._chat_args)
        self._busy_since = time.monotonic()
        self.bridge.start()

    def on_key(self, event: events.Key) -> None:
        """Typing while the chat log has focus goes to the input box."""
        prompt = self.query_one("#prompt", PromptBox)
        if self.focused is prompt or prompt.disabled or not event.is_printable:
            return
        if not self.query_one("#question").has_class("visible") and event.character:
            prompt.focus()
            prompt.insert(event.character)
            event.stop()

    # --- what the chat engine sends -----------------------------------------------

    def _mount_message(self, widget: Message) -> None:
        log = self.query_one("#log", VerticalScroll)
        widget.repaint(self.palette)
        log.mount(widget)
        log.scroll_end(animate=False)

    def _on_turn(self, role: str) -> None:
        if role == "user":
            self._block = None
            return
        if self._block is not None and self._block.role == "grandpa":
            return  # one reply printed in several parts
        self._block = OutputBlock("grandpa")
        self._mount_message(self._block)

    def _on_output(self, text: str) -> None:
        if self._block is None:
            if not clean_terminal_text(text).strip():
                return  # blank lines between turns: the layout spaces turns itself
            self._block = OutputBlock("system")
            self._mount_message(self._block)
        self._block.feed(text)
        switched = _MODEL_SWITCH.search(clean_terminal_text(text))
        if switched:
            self._model_cache = switched.group(1)
            self._paint_chrome()
        self.query_one("#log", VerticalScroll).scroll_end(animate=False)

    def _on_ready(self, _prompt: str) -> None:
        took = (
            time.monotonic() - self._busy_since
            if self._busy_since is not None
            else None
        )
        block = self._block
        if block is not None and block.role == "grandpa":
            if took is not None and self.last_sent is not None:
                block.seconds = took
                block.repaint(self.palette)
            reply = block.plain()
            if reply:
                self.turns.append(Turn("grandpa", reply, block.at))
                self.reply_voice.say(reply)
            if took is not None and took >= LONG_REPLY_SECONDS:
                self.bell()
        self._busy_since = None
        self._block = None  # the next turn starts a new block
        self._update_status()

    def _on_question(self, question: Question) -> None:
        self._question = question
        self._busy_since = None
        if question.kind == "choose":
            choices = self.query_one("#choices", OptionList)
            choices.clear_options()
            choices.add_options(
                [Option(str(o), id=str(i)) for i, o in enumerate(question.options)]
            )
            choices.border_title = question.prompt
            choices.highlighted = 0
            choices.add_class("visible")
            choices.focus()
        else:
            bar = self.query_one("#question", Horizontal)
            self.query_one("#question-text", Label).update(
                question.prompt or "Grandpa asks:"
            )
            for button in bar.query(Button):
                button.display = question.yes_no
            bar.add_class("visible")
            if not question.yes_no:
                self.query_one("#prompt", PromptBox).focus()
            else:
                self.query_one("#yes", Button).focus()
        self._update_status()

    def _on_finished(self, code: int) -> None:
        """The chat ended. A normal goodbye closes the app; a failure stays on
        screen, because closing would hide the reason (the old silent exit)."""
        self._exit_code = code
        self._busy_since = None
        if code == 0:
            self.exit(code)
            return
        self._block = None
        self._on_output(
            "\n\x1b[31mGrandpa stopped. The reason is above.\x1b[0m\n"
            "Fix it, then start again with \x1b[1mgrandpa\x1b[0m. "
            "Press Ctrl+D (or Ctrl+C) to close.\n"
        )
        self.query_one("#prompt", PromptBox).disabled = True
        self._stopped = True
        self._update_status()

    # --- sending -----------------------------------------------------------------------

    def submit_prompt(self) -> None:
        prompt = self.query_one("#prompt", PromptBox)
        if self.slash_visible():
            slash = self.query_one("#slash", OptionList)
            name = (
                slash.get_option_at_index(slash.highlighted).id
                if slash.highlighted is not None and slash.option_count
                else None
            )
            self.complete_slash(name)
            if name is None or name.startswith("@") or "<" in name:
                return  # filled in; the user adds the file or the argument
        text = prompt.text.rstrip()
        if self._question is not None and self._question.kind == "input":
            self._answer(text)
            prompt.clear()
            return
        if not text:
            return
        if self._run_local_command(text):
            prompt.clear()
            self.history.add(text)
            return
        if self.bridge is None or self._busy_since is not None:
            return
        prompt.clear()
        self.history.add(text)
        self.send_message(text)

    def send_message(self, text: str) -> None:
        """Show the message, attach any @files, and hand it to the engine."""
        message, attached, notes = expand_file_mentions(text)
        self._block = None
        self._mount_message(UserMessage(text, datetime.now(), attached))
        for note in notes:
            self.notify_status(note, "error")
        self.turns.append(Turn("user", text, datetime.now()))
        self.last_sent = text
        if text.strip().lower() in {"/clear", "/new"}:
            self.action_clear_screen()
        self._busy_since = time.monotonic()
        self.bridge.send(message)  # type: ignore[union-attr]
        self._update_status()

    def _run_local_command(self, text: str) -> bool:
        parts = text.strip().split()
        if not parts:
            return False
        name, args = parts[0].lower(), [a.lower() for a in parts[1:]]
        if name == "/theme":
            if args and args[0] in THEMES:
                self.set_theme(args[0])
            else:
                self.action_toggle_theme()
            return True
        if name == "/talk":
            self.action_talk()
            return True
        if name == "/speak":
            if args and args[0] in {"on", "off"}:
                self.set_speak(args[0] == "on")
            else:
                self.action_toggle_speak()
            return True
        if name == "/copy":
            self.action_copy_reply()
            return True
        if name == "/retry":
            self.action_retry()
            return True
        if name == "/export":
            self.export_conversation()
            return True
        if name in {"/keys", "/shortcuts"}:
            self.action_toggle_help()
            return True
        return False

    def _answer(self, value: str | None) -> None:
        question = self._question
        if question is None:
            return
        self._question = None
        self.query_one("#question", Horizontal).remove_class("visible")
        self.query_one("#choices", OptionList).remove_class("visible")
        self.query_one("#prompt", PromptBox).focus()
        self._busy_since = time.monotonic()
        question.answer(value)
        self._update_status()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in {"yes", "no"}:
            self._answer("y" if event.button.id == "yes" else "n")

    def action_answer_yes(self) -> None:
        if self._question is not None and self._question.yes_no:
            self._answer("y")

    def action_answer_no(self) -> None:
        if self._question is not None and self._question.yes_no:
            self._answer("n")

    # --- completions -------------------------------------------------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "choices" and self._question is not None:
            index = int(event.option.id or 0)
            self._answer(self._question.options[index])
        elif event.option_list.id == "slash":
            self.complete_slash(event.option.id)

    def _completions(self, text: str) -> list[tuple[str, str]]:
        found = matching_commands(text)
        if found:
            return found
        if text.startswith("/"):
            return []
        partial = mention_at_cursor(text)
        if partial is None:
            return []
        return [("@" + path, "") for path in file_suggestions(partial)]

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "prompt":
            return
        found = self._completions(event.text_area.text)
        slash = self.query_one("#slash", OptionList)
        if found:
            slash.clear_options()
            width = max(len(name) for name, _ in found) + 2
            options = []
            for name, about in found:
                label = Text(name.ljust(width), style=Style(color=self.palette.brand))
                label.append(about, style=self.palette.muted)
                options.append(Option(label, id=name))
            slash.add_options(options)
            slash.highlighted = 0
            slash.add_class("visible")
        else:
            slash.remove_class("visible")

    def slash_visible(self) -> bool:
        return self.query_one("#slash", OptionList).has_class("visible")

    def move_slash(self, step: int) -> None:
        slash = self.query_one("#slash", OptionList)
        if slash.option_count:
            current = slash.highlighted or 0
            slash.highlighted = (current + step) % slash.option_count

    def complete_slash(self, name: str | None = None) -> None:
        slash = self.query_one("#slash", OptionList)
        if name is None and slash.highlighted is not None and slash.option_count:
            name = slash.get_option_at_index(slash.highlighted).id
        slash.remove_class("visible")
        if not name:
            return
        prompt = self.query_one("#prompt", PromptBox)
        if name.startswith("@"):
            path = name[1:]
            if " " in path:
                path = f'"{path}"'
            at = prompt.text.rfind("@")
            ending = "" if name.endswith("/") else " "
            prompt.text = prompt.text[: max(at, 0)] + "@" + path + ending
        else:
            prompt.text = completion_text(name)
        prompt.move_cursor(prompt.document.end)

    def history_step(self, step: int) -> None:
        text = self.history.previous() if step < 0 else self.history.next()
        if text is None:
            return
        prompt = self.query_one("#prompt", PromptBox)
        prompt.text = text
        prompt.move_cursor(prompt.document.end)

    # --- actions ----------------------------------------------------------------------

    def action_cancel(self) -> None:
        if self._stopped:
            self.exit(self._exit_code)
            return
        if self._question is not None:
            self._answer(None if not self._question.yes_no else "n")
            return
        if self.talk.recording:
            self.talk.stop()
            return
        if self.slash_visible():
            self.query_one("#slash", OptionList).remove_class("visible")
            return
        if self.query_one("#help").has_class("visible"):
            self.query_one("#help").remove_class("visible")
            return
        if (
            self.bridge is not None
            and self._busy_since is not None
            and self.bridge.cancel()
        ):
            self._on_output("\n[cancelled]\n")

    def action_quit_grandpa(self) -> None:
        if self._stopped:
            self.exit(self._exit_code)
        elif self.bridge is not None and self.bridge.alive:
            self.bridge.quit()
        else:
            self.exit(self._exit_code)

    def action_clear_screen(self) -> None:
        self.query_one("#log", VerticalScroll).remove_children()
        self._block = None

    def action_scroll_log(self, direction: int) -> None:
        log = self.query_one("#log", VerticalScroll)
        if direction < 0:
            log.scroll_page_up(animate=False)
        else:
            log.scroll_page_down(animate=False)

    def set_theme(self, name: str) -> None:
        self.palette = THEMES[name]
        self.theme = f"grandpa-{name}"
        save_settings({"theme": name})
        for message in self.query(Message):
            message.repaint(self.palette)
        self._paint_chrome()
        self.notify_status(f"{name.title()} theme", "info")

    def action_toggle_theme(self) -> None:
        self.set_theme("light" if self.palette.name == "dark" else "dark")

    def action_toggle_help(self) -> None:
        panel = self.query_one("#help", Static)
        if panel.has_class("visible"):
            panel.remove_class("visible")
            return
        self._paint_help()
        panel.add_class("visible")

    def action_talk(self) -> None:
        if self.talk.recording:
            self.talk.stop()
            return
        if self.talk.start():
            self.notify_status("Listening… speak now (F2 again to finish)", "voice", 15)

    def _set_level(self, rms: float) -> None:
        self._level = rms

    def _on_heard(self, text: str) -> None:
        self._notice = None
        prompt = self.query_one("#prompt", PromptBox)
        joiner = " " if prompt.text and not prompt.text.endswith((" ", "\n")) else ""
        prompt.insert(joiner + text)
        prompt.focus()
        self.notify_status("Heard you. Check the text, then press Enter.", "success")

    def set_speak(self, enabled: bool) -> None:
        self.reply_voice.enabled = enabled
        save_settings({"speak_replies": enabled})
        self.notify_status(
            "Grandpa will read replies aloud" if enabled else "Reading aloud is off",
            "voice" if enabled else "info",
        )
        self._paint_chrome()

    def action_toggle_speak(self) -> None:
        self.set_speak(not self.reply_voice.enabled)

    def last_reply(self) -> str | None:
        return next((t.text for t in reversed(self.turns) if t.role == "grandpa"), None)

    def action_copy_reply(self) -> None:
        reply = self.last_reply()
        if not reply:
            self.notify_status("No reply to copy yet", "error")
            return
        if copy_text(reply):
            self.notify_status("Copied Grandpa's last reply", "success")
            return
        # No clipboard tool: terminals that support OSC 52 still get it.
        self.copy_to_clipboard(reply)
        self.notify_status("Copied (through the terminal)", "success")

    def action_pick_model(self) -> None:
        if self._busy_since is not None or self.bridge is None:
            self.notify_status("Wait for the current reply (Esc cancels it)", "error")
            return
        self.send_message("/model")

    def action_retry(self) -> None:
        if not self.last_sent:
            self.notify_status("Nothing to retry yet", "error")
            return
        if self._busy_since is not None or self.bridge is None:
            self.notify_status("Wait for the current reply (Esc cancels it)", "error")
            return
        self.send_message(self.last_sent)

    def export_conversation(self) -> Path | None:
        if not self.turns:
            self.notify_status("Nothing to export yet", "error")
            return None
        try:
            from grandpa.runtime_paths import grandpa_home

            folder = grandpa_home() / "exports"
        except Exception:  # noqa: BLE001
            folder = Path.home() / ".grandpa" / "exports"
        try:
            path = export_markdown(self.turns, folder)
        except OSError as exc:
            self.notify_status(f"Export failed: {exc}", "error")
            return None
        self.notify_status(f"Saved {path}", "success", 10)
        return path

    # --- header, help and status ---------------------------------------------------------

    def notify_status(
        self, text: str, role: str = "info", seconds: float = 5.0
    ) -> None:
        self._notice = (text, role, time.monotonic() + seconds)
        self._update_status()

    def _paint_chrome(self) -> None:
        colors = self.palette
        header = Text()
        header.append(
            " ✦ GRANDPA ",
            style=Style(color=colors.background, bgcolor=colors.brand, bold=True),
        )
        header.append(f"  v{grandpa.__version__}", style=colors.muted)
        model = self._model_name()
        if model:
            header.append("  ·  ", style=colors.muted)
            header.append(model, style=colors.text)
        header.append("  ·  ", style=colors.muted)
        header.append(_short_cwd(), style=colors.muted)
        header.append(f"  ·  {colors.name}", style=colors.muted)
        if self.reply_voice.enabled:
            header.append("  ·  ", style=colors.muted)
            header.append("♪ speaking replies", style=colors.voice)
        try:
            self.query_one("#header", Static).update(header)
        except NoMatches:
            return
        if self.query_one("#help").has_class("visible"):
            self._paint_help()
        self._update_status()

    def _paint_help(self) -> None:
        colors = self.palette
        text = Text()
        text.append("Keyboard\n", style=Style(color=colors.brand, bold=True))
        for key, about in HELP_TEXT:
            text.append(f"  {key:<24}", style=colors.grandpa)
            text.append(f"{about}\n", style=colors.text)
        text.append(
            "\nGrandpa's own commands\n", style=Style(color=colors.brand, bold=True)
        )
        for name, about in LOCAL_COMMANDS:
            text.append(f"  {name:<24}", style=colors.user)
            text.append(f"{about}\n", style=colors.text)
        text.append(
            "\nType / to see every command.  Esc closes this.", style=colors.muted
        )
        self.query_one("#help", Static).update(text)

    _model_cache: str | None = None

    def _model_name(self) -> str:
        if self._model_cache is None:
            try:
                from grandpa.core.config import load_config

                config = load_config()
                self._model_cache = str(config.intelligence.default_model or "")
            except Exception:  # noqa: BLE001
                self._model_cache = ""
            for i, arg in enumerate(self._chat_args):
                if arg in {"-m", "--model"} and i + 1 < len(self._chat_args):
                    self._model_cache = self._chat_args[i + 1]
        return self._model_cache

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def _tick(self) -> None:
        if self._busy_since is not None or self.talk.recording or self._notice:
            self._spinner = (self._spinner + 1) % len(self._FRAMES)
            self._update_status()

    def _role_colour(self, role: str) -> str:
        colors = self.palette
        return {
            "error": colors.error,
            "success": colors.success,
            "voice": colors.voice,
            "info": colors.info,
        }.get(role, colors.text)

    def _update_status(self) -> None:
        try:
            status = self.query_one("#status", Static)
        except NoMatches:  # the screen is already closing
            return
        colors = self.palette
        text = Text()
        if self._notice and time.monotonic() > self._notice[2]:
            self._notice = None
        if self._stopped:
            text.append("■ stopped", style=colors.error)
            text.append("  ·  ctrl+d to close", style=colors.muted)
        elif self.talk.recording:
            bars = min(8, int(self._level / 120))
            text.append("● ", style=colors.error)
            text.append("Listening… ", style=colors.voice)
            text.append("▮" * bars + "▯" * (8 - bars), style=colors.voice)
            text.append("  ·  F2 to finish · esc to stop", style=colors.muted)
        elif self._question is not None:
            text.append("● waiting for your answer", style=colors.thinking)
            hint = (
                "  y / n · esc = no"
                if self._question.yes_no
                else "  type the answer · enter"
            )
            text.append(hint, style=colors.muted)
        elif self._notice:
            message, role, _until = self._notice
            text.append(message, style=self._role_colour(role))
        elif self._busy_since is not None:
            seconds = int(time.monotonic() - self._busy_since)
            text.append(
                f"{self._FRAMES[self._spinner]} Grandpa is thinking… {seconds}s",
                style=colors.thinking,
            )
            text.append("  ·  esc to cancel", style=colors.muted)
        else:
            text.append(
                "enter send · / commands · @ files · F2 talk · F6 model · F1 keys · ctrl+t theme",
                style=colors.muted,
            )
        status.update(text)

    @staticmethod
    def _history_path() -> Path | None:
        try:
            from grandpa.runtime_paths import grandpa_home

            return grandpa_home() / "tui_history"
        except Exception:  # noqa: BLE001
            return None


def _short_cwd() -> str:
    cwd = Path.cwd()
    try:
        home = Path.home()
        if cwd == home or home in cwd.parents:
            return (
                "~/" + str(cwd.relative_to(home)).replace("\\", "/")
                if cwd != home
                else "~"
            )
    except (OSError, ValueError):
        pass
    return str(cwd)


def can_run_fullscreen() -> bool:
    """A real interactive terminal, so the full-screen app can draw."""
    import sys

    return sys.stdin.isatty() and sys.stdout.isatty()


def run(chat_args: Iterable[str] = ()) -> int:
    app = GrandpaApp(chat_args=chat_args)
    try:
        from grandpa.tui.themes import load_settings

        app.reply_voice.enabled = bool(load_settings().get("speak_replies", False))
    except Exception:  # noqa: BLE001
        pass
    result = app.run()
    return int(result or 0)


__all__ = [
    "GrandpaApp",
    "InputHistory",
    "LOCAL_COMMANDS",
    "SLASH_COMMANDS",
    "all_commands",
    "can_run_fullscreen",
    "completion_text",
    "fit_text",
    "matching_commands",
    "run",
]
