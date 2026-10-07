"""The two methods a UI needs from Grandpa, and nothing else.

Defined before the UI exists so the UI is written against an interface rather
than against internals. Two methods, both in-process:

    send(text)      -> BridgeReply       route text as the CLI routes it
    transcribe(...) -> BridgeTranscript  audio in, words out

In-process was chosen over the local API because the UI is already a Python
process: a direct call needs no port, no auth decision, no second process to
supervise, and no server-down path. The seam exists anyway so that an HTTP
implementation can be added later -- for the Pironman or a phone -- without the
UI changing. It is one interface, not an architecture.

**The UI must not become a new actuation surface.** Nothing here widens what can
actuate. ``send`` routes through :class:`VoiceCommandProcessor`, the same object
``grandpa voice`` uses, so the UI inherits exactly the consent gates the voice
path has and gains none of its own. In particular it does not add an origin to
``focus_witness.WITNESS_ORIGINS``, which remains ``{"voice"}`` -- a UI that could
type into a window the CLI could not would be a privilege escalation wearing a
button. ``tests/ui/test_ui_is_not_a_new_actuation_surface.py`` enumerates the
catalogue and asserts it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class BridgeReply:
    """What came back from routing text."""

    text: str
    status: str = "ok"
    #: True when the reply is a refusal or an error rather than an answer, so a
    #: UI can style it without parsing the prose.
    failed: bool = False
    detail: str = ""


@dataclass(frozen=True)
class BridgeTranscript:
    """What came back from transcribing audio.

    ``text`` empty is a legitimate outcome, not an error: the audio was recorded
    deliberately and "nothing recognisable was in it" is an answer. ``reason``
    names which gate emptied it, so a UI can say so instead of showing a blank.
    """

    text: str
    reason: str = ""
    explanation: str = ""

    @property
    def empty(self) -> bool:
        return not self.text.strip()


@runtime_checkable
class GrandpaBridge(Protocol):
    """The whole surface the UI is allowed to use."""

    def send(self, text: str) -> BridgeReply:
        """Route text through Grandpa and return the reply."""

    def transcribe(self, audio: Any) -> BridgeTranscript:
        """Turn captured audio into words."""


@dataclass
class InProcessBridge:
    """Calls Grandpa directly. No port, no auth, no second process.

    Both collaborators are constructed lazily, because building them loads a
    model and reads config, and a UI should be able to exist before either has
    happened -- the status line's whole job is to say "not ready yet".
    """

    responder: Any = None
    transcriber: Any = None
    #: Replaced in tests. Kept as attributes rather than imported at call time
    #: so a test can supply doubles without patching module globals.
    responder_factory: Any = None
    transcriber_factory: Any = None
    _ready: bool = field(default=False, init=False)

    def ensure_responder(self) -> Any:
        if self.responder is None:
            factory = self.responder_factory or _default_responder
            self.responder = factory()
        return self.responder

    def ensure_transcriber(self) -> Any:
        if self.transcriber is None:
            factory = self.transcriber_factory or _default_transcriber
            self.transcriber = factory()
        return self.transcriber

    def warm(self) -> tuple[bool, str]:
        """Load the speech model now, so it is not loaded mid-interaction.

        The same reasoning as ``grandpa voice accuracy-test``: a surface that
        looks ready while the model is still downloading measures, or routes,
        against a transcriber that does not exist yet. Returns
        ``(ready, detail)`` rather than raising, so the caller can put the
        detail in a status line.
        """
        from grandpa.voice.accuracy import quiet_model_downloads, warm_transcriber

        quiet_model_downloads()
        try:
            transcriber = self.ensure_transcriber()
        except Exception as exc:  # pragma: no cover - depends on local install
            self._ready = False
            return False, f"{type(exc).__name__}: {exc}"
        ready, detail = warm_transcriber(transcriber)
        self._ready = bool(ready)
        return ready, detail

    @property
    def speech_ready(self) -> bool:
        return self._ready

    def send(self, text: str) -> BridgeReply:
        """Route text exactly as the voice path does.

        Errors are returned, not raised. A UI that has to catch exceptions from
        its own model layer ends up showing a traceback in a 300-pixel window,
        which is the desktop version of the bug fixed in `grandpa voice`.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return BridgeReply("", status="empty", failed=False)
        from grandpa.voice.errors import VoiceError

        try:
            response = self.ensure_responder().handle_user_input(cleaned)
        except VoiceError as exc:
            return BridgeReply(
                str(exc).splitlines()[0], status="error", failed=True,
                detail=getattr(exc, "detail", "") or "",
            )
        except Exception as exc:  # noqa: BLE001 - a UI must not die of a reply
            return BridgeReply(
                f"That did not work: {type(exc).__name__}",
                status="error",
                failed=True,
                detail=str(exc),
            )
        reply_text = str(getattr(response, "text", "") or "").strip()
        status = str(getattr(response, "status", "ok") or "ok")
        return BridgeReply(
            reply_text,
            status=status,
            failed=status in {"error", "refused", "blocked"},
        )

    def transcribe(self, audio: Any) -> BridgeTranscript:
        """Transcribe audio the user deliberately recorded.

        Prefers ``transcribe_trusted``, which disables the suppression that
        would otherwise discard quiet-but-real speech and returns an empty
        string with a reason rather than raising.
        """
        from grandpa.voice.errors import VoiceError

        transcriber = self.ensure_transcriber()
        trusted = getattr(transcriber, "transcribe_trusted", None)
        if callable(trusted):
            outcome = trusted(audio)
            return BridgeTranscript(
                text=(outcome.text or "").strip(),
                reason=getattr(outcome, "reason", ""),
                explanation=getattr(outcome, "explanation", ""),
            )
        try:
            return BridgeTranscript(
                text=(transcriber.transcribe(audio) or "").strip()
            )
        except VoiceError as exc:
            return BridgeTranscript(
                text="", reason="error", explanation=str(exc).splitlines()[0]
            )


def _default_responder() -> Any:
    from grandpa.voice.assistant import VoiceCommandProcessor

    return VoiceCommandProcessor(model_name=None)


def _default_transcriber() -> Any:
    from grandpa.voice.config import load_voice_assistant_config
    from grandpa.voice.speech_to_text import FasterWhisperSpeechToText

    config = load_voice_assistant_config(tts_enabled=False)
    return FasterWhisperSpeechToText(
        language=config.language,
        model=config.stt_model,
        device=config.device,
        compute_type=config.compute_type,
    )


__all__ = [
    "BridgeReply",
    "BridgeTranscript",
    "GrandpaBridge",
    "InProcessBridge",
]
