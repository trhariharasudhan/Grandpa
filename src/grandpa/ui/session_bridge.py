"""The orb's brain is the app's brain.

The orb used to answer through :class:`grandpa.voice.assistant.
VoiceCommandProcessor`, an older keyword path of its own: it could not reach
volume, brightness, battery, the model's tool calls, or the chat engine's
confirmations, and the model then *said* it had done things it never did.

:class:`SessionBridge` gives the orb the same chat engine as the desktop app
and the terminal (:class:`grandpa.app.session.AppSession`): same routes, same
action layer, same tools, same risk rules and the same yes/no questions. One
brain, three screens.

A spoken turn: the words go in with ``send``; this waits until the engine is
idle again, or asks something, and returns what it said. A question ("Close
Notepad?") is returned as the reply, and the next thing said answers it --
"yes", "seri", "no", "venam", or a new request, which drops the question.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Callable

from grandpa.ui.bridge import BridgeReply, BridgeTranscript, InProcessBridge

logger = logging.getLogger(__name__)

TURN_SECONDS = 300.0
START_SECONDS = 180.0
_DONE = {"idle", "asking", "stopped"}


class SessionBridge:
    """``GrandpaBridge`` over an :class:`AppSession` (thread-safe, one turn at a time)."""

    def __init__(
        self,
        *,
        session_factory: Callable[[Callable[[dict], None]], Any] | None = None,
        transcriber: InProcessBridge | None = None,
        chat_args: list[str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cond = threading.Condition()
        self._turn = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._state = "starting"
        self._clock = clock
        self._listeners: list[Callable[[dict], None]] = []
        self._speech = transcriber or InProcessBridge()
        factory = session_factory or (
            lambda publish: _app_session(publish, chat_args or [])
        )
        self.session = factory(self._publish)
        self._started = False

    # --- the GrandpaBridge shape ------------------------------------------------

    @property
    def stt_model(self) -> Any:
        return getattr(self._speech, "stt_model", None)

    @stt_model.setter
    def stt_model(self, value: Any) -> None:
        self._speech.stt_model = value

    def ensure_transcriber(self) -> Any:
        return self._speech.ensure_transcriber()

    def speech_ready(self) -> bool:
        return self._speech.speech_ready()

    def transcribe(self, audio: Any) -> BridgeTranscript:
        return self._speech.transcribe(audio)

    def warm(self) -> tuple[bool, str]:
        """Start the chat engine and wait for its first prompt."""
        self.start()
        deadline = self._clock() + START_SECONDS
        with self._cond:
            while self._state == "starting" and self._clock() < deadline:
                self._cond.wait(timeout=0.5)
            state = self._state
        if state == "stopped":
            reason = next(
                (e.get("reason", "") for e in reversed(self._events) if e.get("type") == "engine_down"),
                "",
            )
            return False, (reason.splitlines() or ["The chat engine stopped."])[0]
        return state != "starting", "" if state != "starting" else "Still starting."

    def start(self) -> None:
        if not self._started:
            self._started = True
            self.session.start()

    def stop(self) -> None:
        try:
            self.session.stop()
        except Exception:  # noqa: BLE001
            pass

    def add_listener(self, listener: Callable[[dict], None]) -> None:
        """Also see every message (the orb's panel shows the same chat)."""
        self._listeners.append(listener)

    def send(self, text: str) -> BridgeReply:
        cleaned = (text or "").strip()
        if not cleaned:
            return BridgeReply("", status="empty", failed=False)
        with self._turn:
            self.start()
            with self._cond:
                deadline = self._clock() + START_SECONDS
                while self._state == "starting" and self._clock() < deadline:
                    self._cond.wait(timeout=0.5)
                if self._state == "stopped":
                    return BridgeReply(
                        "My chat engine is not running. Is Ollama started?",
                        status="error",
                        failed=True,
                    )
                mark = len(self._events)
            if not self.session.send(cleaned):
                return BridgeReply("I am still busy with the last thing.", status="busy", failed=True)
            deadline = self._clock() + TURN_SECONDS
            with self._cond:
                # session.send already announced "thinking"; wait for the end
                while self._clock() < deadline:
                    if self._finished_since(mark):
                        break
                    self._cond.wait(timeout=0.5)
                events = self._events[mark:]
            return _reply_from(events)

    def cancel(self) -> None:
        try:
            self.session.bridge.interrupt()
        except Exception:  # noqa: BLE001
            pass

    # --- engine messages ------------------------------------------------------------

    def _finished_since(self, mark: int) -> bool:
        seen_work = False
        for event in self._events[mark:]:
            if event.get("type") == "state":
                state = event.get("state")
                if state == "thinking":
                    seen_work = True
                elif state in _DONE and seen_work:
                    return True
        return False

    def _publish(self, message: dict) -> None:
        with self._cond:
            if message.get("type") == "state":
                self._state = str(message.get("state", self._state))
            self._events.append(message)
            if len(self._events) > 2000:
                del self._events[:1000]
            self._cond.notify_all()
        for listener in list(self._listeners):
            try:
                listener(message)
            except Exception:  # noqa: BLE001
                logger.debug("bridge listener failed", exc_info=True)


def _reply_from(events: list[dict[str, Any]]) -> BridgeReply:
    """What to say for one turn: the replies; else the notes; plus any question."""
    replies = [str(e.get("text", "")) for e in events if e.get("type") == "reply"]
    notes = [
        str(e.get("text", ""))
        for e in events
        if e.get("type") == "note" and not str(e.get("text", "")).lstrip().startswith("·")
    ]
    asks = [e for e in events if e.get("type") == "ask"]
    if asks:
        # the engine also prints the question it asks: say it once
        asked = _spoken_question(str(asks[-1].get("prompt", "")))
        notes = [n for n in notes if _spoken_question(n) != asked and asked not in _spoken_question(n)]
    failed = any(e.get("type") == "note" and e.get("failed") for e in events)
    parts = [t for t in replies if t.strip()] or [t for t in notes if t.strip()]
    status = "ok"
    if asks:
        ask = asks[-1]
        prompt = str(ask.get("prompt", "")).strip()
        options = [str(o).strip() for o in ask.get("options") or [] if str(o).strip()]
        if ask.get("kind") == "confirm" or not options:
            prompt = _spoken_question(prompt)
            question = f"{prompt} Say yes or no." if ask.get("kind") == "confirm" else prompt
        else:
            question = prompt + " " + ", ".join(options)
        parts.append(question)
        status = "pending_confirmation"
    text = "\n\n".join(p.strip() for p in parts if p.strip())
    # never "Done." on silence: saying something happened when nothing was
    # reported is exactly the fake-success bug this path exists to remove
    return BridgeReply(text or "I have no answer for that.", status=status, failed=failed and not replies)


_TECH = re.compile(
    r"\s*\((?:requires_confirmation|(?:low|medium|high|blocked) risk)\)|\s*\[y/N\]",
    re.IGNORECASE,
)


def _spoken_question(text: str) -> str:
    """"Confirm: Close Calculator? ... (requires_confirmation) [y/N]" ->
    "Close Calculator? Unsaved work may be lost." -- words meant to be heard."""
    cleaned = _TECH.sub("", text or "")
    cleaned = re.sub(r"^\s*confirm(?: [a-z ]+)?:\s*", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip()


def _app_session(publish: Callable[[dict], None], chat_args: list[str]) -> Any:
    from grandpa.app.session import AppSession

    return AppSession(publish, chat_args=chat_args)


__all__ = ["SessionBridge"]
