"""The desktop app's side of a conversation: the chat engine, as messages.

The app runs the same chat engine as the terminal (``grandpa chat`` through
:class:`grandpa.tui.bridge.ChatBridge`): same routing, tools, slash commands,
``/model`` picker, confirmations, memory fallback and warm-up. It is the CLI
with a different screen, so it adds no new way to make Grandpa act.

What the page receives (JSON, via :class:`grandpa.ui.avatar_server.AvatarServer`):

* ``{"type": "state", "state": "starting|idle|thinking|asking|stopped"}``
* ``{"type": "reply", "format": "markdown"|"text", "text": ...}`` one answer
* ``{"type": "note", "text": ...}`` anything else the engine printed (tool
  steps such as ``· open_app ok``, warnings), as plain text
* ``{"type": "ask", "kind": "confirm"|"choose"|"input", "prompt": ...,
  "options": [...]}`` a question that needs an answer before anything happens
* ``{"type": "model", "name": ...}`` the model in use, after a switch
* ``{"type": "delta", "text": ...}`` words of the reply being written
  (``{"type": "delta", "reset": true}``: drop them, it was a tool call)

What the page sends is only what :func:`grandpa.ui.avatar_states.parse_inbound`
allows: a line of text, or "talk". A line sent while a question is open is
the answer to it.
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
from collections.abc import Callable
from typing import Any

from rich.text import Text

from grandpa.tui.bridge import ChatBridge, Question, UiHooks, clean_terminal_text

logger = logging.getLogger(__name__)

MAX_SNAPSHOT = 200
_MODEL_SWITCH = re.compile(r"(?:Model changed to|so)[^()\n]*\(([\w.:/\-]+)\)")


def _plain(ansi: str) -> str:
    text = Text.from_ansi(clean_terminal_text(ansi)).plain
    return "\n".join(line.rstrip() for line in text.split("\n")).strip("\n")


class AppSession:
    """One chat engine for the app; thread-safe; publishes dict messages."""

    def __init__(
        self,
        publish: Callable[[dict[str, Any]], None],
        *,
        chat_args: list[str] | None = None,
        bridge_factory: Callable[[UiHooks], ChatBridge] | None = None,
        width: int = 100,
    ) -> None:
        self._publish = publish
        self._lock = threading.Lock()
        self._history: list[dict[str, Any]] = []
        # Every recorded message is numbered, with an id for this run, so a
        # page that reconnects skips exactly the ones it already has.
        self._run = secrets.token_hex(4)
        self._seq = 0
        self._question: Question | None = None
        self._pending_output: list[str] = []
        self._started = False  # the engine's startup banner is not shown
        self.state = "starting"
        self.model: str | None = None
        self._talk = None
        self._after_question: str = ""
        #: Files picked in the window's file dialog: those may be attached
        #: from any folder, because choosing them there is the permission.
        self.picked_files: set[str] = set()
        #: Context for the next message only: a project's instructions and the
        #: chat's earlier messages when Grandpa starts fresh on an old chat.
        #: Sent to the model with it, never shown as typed text.
        self.next_context: str = ""
        hooks = UiHooks(
            output=self._on_output,
            ready_for_input=self._on_ready,
            ask=self._on_ask,
            finished=self._on_finished,
            turn=self._on_turn,
            reply=self._on_reply,
            stream=self._on_stream,
        )
        self._hooks = hooks
        self._make_bridge = (
            (lambda: bridge_factory(hooks))
            if bridge_factory is not None
            else (lambda: ChatBridge(hooks, width=width, chat_args=chat_args or []))
        )
        self.bridge = self._make_bridge()

    # --- lifecycle --------------------------------------------------------------

    def start(self) -> None:
        self._emit({"type": "state", "state": "starting"})
        self.bridge.start()

    def restart(self) -> bool:
        """Start the chat engine again after it stopped (Ollama was not up).

        Only from "stopped": a running engine is never replaced under the user.
        """
        with self._lock:
            if self.state != "stopped":
                return False
            self._started = False
            self._pending_output.clear()
            self._question = None
        self.bridge = self._make_bridge()
        self.start()
        return True

    def stop(self) -> None:
        try:
            self.bridge.quit()
        except Exception:  # noqa: BLE001
            pass

    def snapshot(self) -> list[dict[str, Any]]:
        """What a page that (re)connects is sent first."""
        with self._lock:
            messages = list(self._history)
            state = {"type": "state", "state": self.state}
            question = self._question
        out = [*messages, state]
        if self.model:
            out.append({"type": "model", "name": self.model})
        if question is not None:
            out.append(self._ask_message(question))
        return out

    # --- from the page --------------------------------------------------------------

    def send(self, text: str) -> bool:
        """A line from the page: the answer to an open question, or a message."""
        text = (text or "").strip()
        if not text:
            return False
        with self._lock:
            question = self._question
            if question is None and self.state != "idle":
                return False  # one message at a time, like the terminal
            self._question = None
        if question is not None:
            answer = self._answer_for(question, text)
            if question.yes_no:
                from grandpa.core.consent import read_consent

                if read_consent(text) is None:
                    # Not a yes or a no: something new. The question is
                    # answered "no" (nothing risky runs on a guess) and the
                    # new words are sent as soon as Grandpa is free again.
                    with self._lock:
                        self._after_question = text
            self._set_state("thinking")
            question.answer(answer)
            return True
        message, attached, notes = self._attach(text)
        context = ""
        if not text.lstrip().startswith("/"):  # commands never carry it (or use it up)
            with self._lock:
                context, self.next_context = self.next_context, ""
        if context:
            message = (
                "Context for this conversation (from the app; the user's new "
                f"message follows the line):\n{context}\n\n---\n\n{message}"
            )
        self._record({"type": "user", "text": text, "attached": attached})
        for note in notes:
            self._record({"type": "note", "text": note, "failed": True})
        self._set_state("thinking")
        self.bridge.send(message)
        return True

    def allow_file(self, path: str) -> str:
        """Remember a file the user picked in the dialog; returns its full path."""
        from pathlib import Path

        resolved = str(Path(path).resolve())
        self.picked_files.add(resolved)
        return resolved

    def _attach(self, text: str) -> tuple[str, list[str], list[str]]:
        """``@path`` attaches a text file, exactly as in the terminal.

        The page's Add files button puts ``@"<path>"`` in the message; the file is
        read here, read-only, with the terminal's limits (text only, 100 KB,
        the current folder or the home folder).
        """
        from grandpa.tui.helpers import expand_file_mentions

        return expand_file_mentions(text, allowed=self.picked_files)

    # --- voice ------------------------------------------------------------------

    def talk(self) -> bool:
        """The mic button: record one phrase; the words go to the page's typing box."""
        if self._talk is None:
            from grandpa.tui.voice import PushToTalk

            self._talk = PushToTalk(
                on_text=lambda text: self._emit({"type": "heard", "text": text}),
                on_error=lambda message: self._emit(
                    {"type": "heard", "error": message}
                ),
                on_level=None,
            )
        if self._talk.recording:
            self._talk.stop()
            return True
        started = self._talk.start()
        if started:
            self._emit({"type": "listening"})
        return started

    def cancel(self) -> bool:
        with self._lock:
            question = self._question
            self._question = None
        if question is not None:
            question.answer("n" if question.yes_no else None)
            return True
        return bool(self.bridge.cancel())

    @staticmethod
    def _answer_for(question: Question, text: str) -> str | None:
        if question.yes_no:
            from grandpa.core.consent import read_consent

            return "y" if read_consent(text) == "yes" else "n"
        if question.kind == "choose":
            # The page's text arrives trimmed; options may start with spaces
            # ("  Fast ..."), so compare trimmed and answer with the original.
            wanted = text.strip()
            for option in question.options:
                if str(option).strip() == wanted:
                    return str(option)
            return None
        return text

    # --- from the engine (worker thread) -------------------------------------------

    def _on_stream(self, text: str) -> None:
        # Shown while it is written, never stored: the finished reply follows
        # as a normal "reply" message and replaces it.
        if text:
            self._emit({"type": "delta", "text": text})
        else:
            self._emit({"type": "delta", "reset": True})

    def _on_output(self, text: str) -> None:
        # Before the first prompt this is the big ASCII banner, which the app
        # replaces with its own header -- unless startup fails, when it holds
        # the reason and is shown (see _on_finished).
        self._pending_output.append(text)
        if not self._started:
            return
        switched = _MODEL_SWITCH.search(clean_terminal_text(text))
        if switched:
            self.model = switched.group(1)
            self._emit({"type": "model", "name": self.model})

    def _flush_output(self) -> None:
        if not self._pending_output:
            return
        note = _plain("".join(self._pending_output))
        self._pending_output.clear()
        if note.strip():
            self._record({"type": "note", "text": note})

    def _on_turn(self, role: str) -> None:
        self._flush_output()

    def _on_reply(self, fmt: str, text: str) -> None:
        self._flush_output()
        self._record({"type": "reply", "format": fmt, "text": text})
        switched = _MODEL_SWITCH.search(text)
        if switched:
            self.model = switched.group(1)
            self._emit({"type": "model", "name": self.model})

    def _on_ready(self, _prompt: str) -> None:
        if not self._started:
            self._started = True
            self._pending_output.clear()
            if self.model is None:
                self.model = self._configured_model()
                if self.model:
                    self._emit({"type": "model", "name": self.model})
        self._flush_output()
        with self._lock:
            follow, self._after_question = self._after_question, ""
            if follow:
                # Free for the follow-up, but "idle" is not announced: the
                # turn is not over until the new words are answered too.
                self.state = "idle"
        if follow:
            # off the engine's thread: send() hands the line back to it
            threading.Thread(target=self.send, args=(follow,), daemon=True).start()
            return
        self._set_state("idle")

    def _on_ask(self, question: Question) -> None:
        self._flush_output()
        with self._lock:
            self._question = question
        self._set_state("asking")
        self._emit(self._ask_message(question))

    def _on_finished(self, code: int) -> None:
        at_start = not self._started
        if at_start:
            # What was printed is the reason it never started. Shown, but as a
            # notice the page does not keep in the chat.
            self._started = True
            reason = _plain("".join(self._pending_output)).strip()
            self._pending_output.clear()
            self._set_state("stopped")
            self._emit(
                {
                    "type": "engine_down",
                    "reason": reason or "The chat engine stopped.",
                    "ollama": "inference engine" in reason.lower()
                    or "ollama" in reason.lower(),
                }
            )
            return
        self._flush_output()
        self._set_state("stopped")
        if code:
            self._record(
                {
                    "type": "note",
                    "text": "Grandpa stopped. The reason is above.",
                    "failed": True,
                }
            )

    # --- helpers -----------------------------------------------------------------

    @staticmethod
    def _ask_message(question: Question) -> dict[str, Any]:
        kind = "confirm" if question.yes_no else question.kind
        return {
            "type": "ask",
            "kind": kind,
            "prompt": _plain(question.prompt or "") or "Grandpa asks:",
            "options": [str(o) for o in question.options],
        }

    @staticmethod
    def _configured_model() -> str | None:
        try:
            from grandpa.core.config import load_config

            return str(load_config().intelligence.default_model or "") or None
        except Exception:  # noqa: BLE001
            return None

    def _set_state(self, state: str) -> None:
        with self._lock:
            self.state = state
        self._emit({"type": "state", "state": state})

    def _record(self, message: dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            message = {**message, "run": self._run, "seq": self._seq}
            self._history.append(message)
            del self._history[:-MAX_SNAPSHOT]
        self._emit(message)

    def _emit(self, message: dict[str, Any]) -> None:
        try:
            self._publish({"v": 1, **message})
        except Exception:  # noqa: BLE001
            logger.debug("app publish failed", exc_info=True)


__all__ = ["AppSession"]
