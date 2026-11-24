"""Run the existing ``grandpa chat`` engine behind the full-screen interface.

The chat command is two thousand lines of routing that already works: memory,
notes, reminders, the browser and desktop routes, the tool loop, and the
confirmation prompts in front of every risky action. Rewriting it for a new
screen would throw all of that away, so this bridge runs the *same* command in
a worker thread and changes only its edges:

* its Rich console writes into the interface instead of the terminal;
* its prompt (``read_chat_input``) waits for what the user types in the
  interface's input box;
* its yes/no questions (``input()``) become a question bar in the interface;
* its model picker (``select_from_list``) becomes a list in the interface.

Everything the chat command decides, asks and audits stays exactly as it was.
The bridge itself has no Textual import, so it is tested without a screen.
"""

from __future__ import annotations

import builtins
import ctypes
import logging
import queue
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)

# Control sequences a terminal understands but a text widget does not: cursor
# moves, erase-line, hide/show cursor, window titles. Colours (SGR, ending in
# "m") are kept; Rich's Text.from_ansi turns them into styles.
_NON_SGR_CSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-ln-z]")
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def clean_terminal_text(buffer: str) -> str:
    """Apply carriage returns and drop control sequences a widget cannot show.

    A spinner writes ``"\\r⠋ thinking"`` over and over; a terminal shows only
    the last one, so this keeps only the text after the last ``\\r`` on each
    line, the way a terminal would.
    """
    buffer = _OSC.sub("", buffer)
    buffer = _NON_SGR_CSI.sub("", buffer)
    lines = buffer.split("\n")
    out = []
    for line in lines:
        if "\r" in line:
            parts = [p for p in line.split("\r")]
            # "abc\r" followed by nothing keeps "abc" (Rich ends lines that way);
            # "spin\rdone" keeps "done".
            line = next((p for p in reversed(parts) if p), "")
        out.append(line)
    return "\n".join(out)


class _ForwardingFile:
    """A file-like object the chat console writes into."""

    def __init__(self, sink: Callable[[str], None]) -> None:
        self._sink = sink

    def write(self, text: str) -> int:
        if text:
            self._sink(text)
        return len(text)

    def flush(self) -> None:  # Rich calls it; nothing is buffered here
        pass

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:  # pragma: no cover - only for libraries that ask
        raise OSError("no file descriptor")


@dataclass
class Question:
    """Something the chat engine is waiting for the user to answer."""

    kind: str  # "input" (free text or y/N) or "choose" (pick one of options)
    prompt: str
    options: Sequence[str] = ()
    yes_no: bool = False
    _answer: "queue.Queue[Any]" = field(default_factory=lambda: queue.Queue(maxsize=1))

    def answer(self, value: Any) -> None:
        try:
            self._answer.put_nowait(value)
        except queue.Full:  # answered twice (double click): keep the first
            pass

    def wait(self) -> Any:
        return self._answer.get()


@dataclass
class UiHooks:
    """What the bridge calls; the interface provides these (thread-safe)."""

    output: Callable[[str], None]
    ready_for_input: Callable[[str], None]
    ask: Callable[[Question], None]
    finished: Callable[[int], None]


_YES_NO = re.compile(r"\[\s*y\s*/\s*n\s*\]\s*$", re.IGNORECASE)


class ChatBridge:
    """Owns the worker thread that runs ``grandpa chat`` for the interface."""

    def __init__(
        self,
        hooks: UiHooks,
        *,
        width: int = 100,
        chat_args: Sequence[str] = (),
        chat_command: Any = None,
    ) -> None:
        self.hooks = hooks
        self.width = max(40, width)
        self.chat_args = list(chat_args)
        self._chat_command = chat_command
        self._inputs: "queue.Queue[str | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._last_line = ""
        self.busy = False

    # --- what the interface calls -------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="grandpa-chat", daemon=True
        )
        self._thread.start()

    def send(self, text: str) -> None:
        """The user pressed Enter in the input box."""
        self.busy = True
        self._inputs.put(text)

    def quit(self) -> None:
        self._inputs.put(None)

    def cancel(self) -> bool:
        """Interrupt the reply being generated, as Ctrl+C would in a terminal."""
        thread = self._thread
        if not (self.busy and thread and thread.is_alive() and thread.ident):
            return False
        changed = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(thread.ident), ctypes.py_object(KeyboardInterrupt)
        )
        return changed == 1

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # --- the chat command's edges, replaced ----------------------------------

    def _write(self, text: str) -> None:
        tail = text.rsplit("\n", 1)[-1]
        self._last_line = (self._last_line + tail) if "\n" not in text else tail
        self.hooks.output(text)

    def _read_chat_input(self, prompt: str = "", **_kwargs: Any) -> str | None:
        self.busy = False
        self.hooks.ready_for_input(clean_terminal_text(str(prompt)))
        return self._inputs.get()

    def _input(self, prompt: str = "") -> str:
        """``input()`` inside the chat thread: a question for the interface."""
        if threading.current_thread() is not self._thread:
            return _real_input(prompt)
        if prompt:
            self._write(str(prompt))
        from rich.text import Text

        question_text = Text.from_ansi(
            clean_terminal_text(self._last_line)
        ).plain.strip()
        question = Question(
            kind="input",
            prompt=question_text,
            yes_no=bool(_YES_NO.search(question_text)),
        )
        self.busy = False
        self.hooks.ask(question)
        answer = question.wait()
        self.busy = True
        if answer is None:
            raise EOFError
        self._write(f"{answer}\n")
        return str(answer)

    def _select_from_list(
        self, title: str, options: Sequence[str], *_a: Any, **_k: Any
    ):
        question = Question(kind="choose", prompt=str(title), options=list(options))
        self.hooks.ask(question)
        return question.wait()

    # --- the worker ----------------------------------------------------------

    def _console_factory(self):
        from rich.console import Console

        sink = _ForwardingFile(self._write)

        def make_console(*_args: Any, theme: Any = None, **_kwargs: Any) -> Console:
            return Console(
                file=sink,
                force_terminal=True,
                color_system="truecolor",
                width=self.width,
                theme=theme,
                legacy_windows=False,
                soft_wrap=False,
            )

        return make_console

    def _run(self) -> None:
        code = 0
        import click.termui

        from grandpa.cli import chat_cmd

        command = self._chat_command or chat_cmd.chat
        patches = {
            # click.prompt (first-run name questions) reads through this.
            (click.termui, "visible_prompt_func"): self._input,
            (chat_cmd, "Console"): self._console_factory(),
            (chat_cmd, "read_chat_input"): self._read_chat_input,
            (chat_cmd, "select_from_list"): self._select_from_list,
        }
        saved = {key: getattr(*key) for key in patches}
        for (module, name), value in patches.items():
            setattr(module, name, value)
        builtins.input = self._input
        try:
            command.main(
                args=["--no-fullscreen", *self.chat_args],
                prog_name="grandpa",
                standalone_mode=False,
            )
        except SystemExit as exc:
            code = int(exc.code or 0) if isinstance(exc.code, int) else 1
        except Exception:  # noqa: BLE001 - shown in the interface, never a crash
            logger.exception("chat stopped")
            import traceback

            self._write("\n" + traceback.format_exc() + "\n")
            code = 1
        finally:
            builtins.input = _real_input
            for (module, name), value in saved.items():
                setattr(module, name, value)
            self.busy = False
            self.hooks.finished(code)


_real_input = builtins.input

__all__ = ["ChatBridge", "Question", "UiHooks", "clean_terminal_text"]
