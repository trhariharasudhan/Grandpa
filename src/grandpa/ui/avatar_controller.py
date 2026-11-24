"""What the avatar window shows, decided in Python and published as messages.

The page is a renderer and nothing else: it never infers a state from text. This
controller owns the state machine and hands every change to ``publish`` -- in the
running app that is the WebSocket server's broadcast, in tests a list.

Text reaches Grandpa through :class:`grandpa.ui.bridge.InProcessBridge`, the
same seam the tkinter bubble uses, so the avatar has exactly the consent gates
the voice path has and adds none. A confirmation is Grandpa's own question
(reply status ``requires_confirmation``); the page's Yes/No buttons just send
the words "yes" or "no" through the same ``send`` as anything typed.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from grandpa.ui.avatar_states import (
    AvatarState,
    ChatMessage,
    ModeMessage,
    StateMessage,
)
from grandpa.ui.bubble import completed_an_operation

logger = logging.getLogger(__name__)

HISTORY_SIZE = 50
"""Chat lines replayed to a page that (re)connects."""

CONFIRM_STATUSES = frozenset({"requires_confirmation", "needs_confirmation"})

NO_MICROPHONE = "Talking is off here (no microphone). Please type instead."
NOTHING_HEARD = "I did not catch that. Click Talk and try again, or type it."
RING_ONLY_NOTE = "To keep your PC fast I will show only my ring for now"


Publish = Callable[[StateMessage | ChatMessage | ModeMessage], None]


def state_for_reply(reply: Any) -> StateMessage:
    """The resting state after a reply, from its status -- never its prose."""
    status = str(getattr(reply, "status", "") or "")
    text = str(getattr(reply, "text", "") or "")
    if status in CONFIRM_STATUSES:
        return StateMessage(AvatarState.CONFIRM, question=text)
    if getattr(reply, "failed", False):
        return StateMessage(AvatarState.ERROR)
    if completed_an_operation(reply):
        return StateMessage(AvatarState.DONE)
    return StateMessage(AvatarState.IDLE)


@dataclass
class AvatarController:
    bridge: Any
    publish: Publish
    bus: Any = None
    """An EventBus, for the action layer's running/finished announcements."""
    speaker: Any = None
    """A :class:`grandpa.ui.lipsync.LipSyncSpeaker` to say replies aloud with a
    moving mouth (A4); ``None`` keeps the avatar silent."""
    listener: Callable[[], Any] | None = None
    """Click-to-talk (A6): records one line and returns its words (a str or a
    :class:`grandpa.ui.bridge.BridgeTranscript`). ``None``: no microphone."""

    state: StateMessage = field(default_factory=lambda: StateMessage(AvatarState.IDLE))
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    mode: ModeMessage = field(default_factory=ModeMessage)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _busy: bool = field(default=False, init=False)
    _watching: bool = field(default=False, init=False)

    # --- state ----------------------------------------------------------------

    def _enter(self, message: StateMessage) -> None:
        self.state = message
        self._emit(message)

    def _chat(self, message: ChatMessage) -> None:
        self.history.append(message)
        self._emit(message)

    def _emit(self, message: StateMessage | ChatMessage | ModeMessage) -> None:
        try:
            self.publish(message)
        except Exception:  # noqa: BLE001 - a dead page must not break a request
            logger.debug("avatar publish failed", exc_info=True)

    def snapshot(self) -> list[StateMessage | ChatMessage | ModeMessage]:
        """What a page that just connected needs: the mode, the chat, the state."""
        head = [] if self.mode.character else [self.mode]
        return [*head, *self.history, self.state]

    # --- A7: the performance gate ----------------------------------------------

    def ring_only(self, reason: str, *, announce: bool = True) -> bool:
        """Show only the ring from now on (A7). Returns False if it already was.

        Once per run: a fallback that flapped back would cost the PC more than
        it saves. ``announce`` says why in the chat.
        """
        with self._lock:
            if not self.mode.character:
                return False
            self.mode = ModeMessage(character=False, reason=reason)
        self._emit(self.mode)
        if announce:
            self._chat(ChatMessage("grandpa", f"{RING_ONLY_NOTE} ({reason})"))
        return True

    @property
    def busy(self) -> bool:
        return self._busy

    # --- requests -------------------------------------------------------------

    def submit(self, text: str) -> bool:
        """Route one line. Returns False, doing nothing, while one is in flight."""
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        try:
            self._route(cleaned)
            return True
        finally:
            with self._lock:
                self._busy = False

    def talk(self, listener=None) -> bool:
        """Click-to-talk (A6): listen for one line, then route it like a typed one.

        ``listening`` shows while the microphone records. What was heard goes
        through :meth:`_route`, the same path as :meth:`submit`, so a spoken
        line meets exactly the confirmations a typed one does. Nothing heard,
        or a microphone that fails, is said in the chat and nothing is routed.
        Returns False, doing nothing, while a request is in flight.
        """
        listener = listener or self.listener
        if listener is None:
            self._chat(ChatMessage("grandpa", NO_MICROPHONE, True))
            return False
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        try:
            self._enter(StateMessage(AvatarState.LISTENING))
            try:
                heard = listener()
            except Exception as exc:  # noqa: BLE001 - a dead mic is not a crash
                logger.warning("avatar listen failed", exc_info=True)
                first = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
                self._chat(
                    ChatMessage(
                        "grandpa", f"I could not use the microphone: {first}", True
                    )
                )
                self._enter(StateMessage(AvatarState.ERROR))
                return True
            text = str(getattr(heard, "text", heard) or "").strip()
            if not text:
                self._chat(ChatMessage("grandpa", NOTHING_HEARD))
                self._enter(StateMessage(AvatarState.IDLE))
                return True
            self._route(text)
            return True
        finally:
            with self._lock:
                self._busy = False

    def _route(self, cleaned: str) -> None:
        """One line through the bridge. The caller holds ``_busy``."""
        self._chat(ChatMessage("user", cleaned))
        self._enter(StateMessage(AvatarState.THINKING))
        try:
            reply = self.bridge.send(cleaned)
        except Exception as exc:  # noqa: BLE001 - the bridge should not raise
            logger.exception("avatar send failed")
            self._chat(ChatMessage("grandpa", f"That did not work: {exc}", True))
            self._enter(StateMessage(AvatarState.ERROR))
            return
        reply_text = str(getattr(reply, "text", "") or "").strip()
        self._chat(
            ChatMessage(
                "grandpa",
                reply_text or "(no reply)",
                bool(getattr(reply, "failed", False)),
            )
        )
        if reply_text:
            self._say(reply_text)
        self._enter(state_for_reply(reply))

    def _say(self, text: str) -> None:
        """Speak the reply, showing ``speaking`` with its mouth track meanwhile.

        The reply is already on screen; speech only adds sound. A question
        Grandpa asks is spoken too, and the yes/no buttons show once it ends.
        """
        if self.speaker is None:
            return

        def _started(track: Any, start_ms: float) -> None:
            self._enter(
                StateMessage(
                    AvatarState.SPEAKING,
                    visemes=tuple(track),
                    speech_start_ms=float(start_ms),
                )
            )

        try:
            self.speaker.speak(text, _started)
        except Exception:  # noqa: BLE001 - a silent reply is still a reply
            logger.warning("avatar speech failed", exc_info=True)

    # --- the action layer's announcements -------------------------------------

    def watch_actions(self) -> bool:
        if self._watching:
            return True
        try:
            from grandpa.core.events import EventType, get_event_bus

            bus = self.bus or get_event_bus()
            bus.subscribe(EventType.TOOL_CALL_START, self._on_action_started)
            bus.subscribe(EventType.TOOL_CALL_END, self._on_action_finished)
        except Exception:  # noqa: BLE001 - no bus is not a broken avatar
            return False
        self.bus = bus
        self._watching = True
        return True

    def unwatch_actions(self) -> None:
        if not self._watching:
            return
        from grandpa.core.events import EventType

        try:
            self.bus.unsubscribe(EventType.TOOL_CALL_START, self._on_action_started)
            self.bus.unsubscribe(EventType.TOOL_CALL_END, self._on_action_finished)
        except Exception:  # noqa: BLE001
            pass
        self._watching = False

    def _on_action_started(self, event: Any = None) -> None:
        # Only for the request this window sent; other callers in the process
        # do not make this orb say "working".
        if not self._busy:
            return
        action = str((getattr(event, "data", None) or {}).get("action", "") or "")
        self._enter(StateMessage(AvatarState.WORKING, action=action))

    def _on_action_finished(self, _event: Any = None) -> None:
        if self._busy and self.state.state is AvatarState.WORKING:
            self._enter(StateMessage(AvatarState.THINKING))


__all__ = [
    "AvatarController",
    "HISTORY_SIZE",
    "NOTHING_HEARD",
    "NO_MICROPHONE",
    "RING_ONLY_NOTE",
    "state_for_reply",
]
