"""The seam, driven directly. Two methods, both in-process.

Defined before the UI so the UI is written against an interface. Tested
separately from the controller for the same reason: if ``send`` and
``transcribe`` behave, a later HTTP implementation has a specification to meet
rather than a controller to reverse-engineer.

Nothing here opens a microphone or loads a model -- both collaborators are
injected, and the lazy factories are only inspected, never called.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from grandpa.ui.bridge import (
    BridgeReply,
    BridgeTranscript,
    GrandpaBridge,
    InProcessBridge,
)
from grandpa.voice.errors import VoiceRecognitionError

pytestmark = pytest.mark.core


@dataclass
class Reply:
    text: str
    status: str = "ok"


@dataclass
class Responder:
    reply: Any = field(default_factory=lambda: Reply("done"))
    raises: Exception | None = None
    seen: list[str] = field(default_factory=list)

    def handle_user_input(self, text: str):
        self.seen.append(text)
        if self.raises is not None:
            raise self.raises
        return self.reply


@dataclass
class Trusted:
    text: str = "open notepad"
    reason: str = ""
    explanation: str = "nothing recognisable was in it"


@dataclass
class Transcriber:
    outcome: Trusted = field(default_factory=Trusted)
    seen: list[Any] = field(default_factory=list)

    def transcribe_trusted(self, audio: Any) -> Trusted:
        self.seen.append(audio)
        return self.outcome


# --- the contract -----------------------------------------------------------------


def test_the_in_process_bridge_satisfies_the_protocol() -> None:
    assert isinstance(InProcessBridge(), GrandpaBridge)


def test_the_protocol_is_two_methods() -> None:
    """Widening it widens what a UI may reach."""
    methods = {
        name
        for name in dir(GrandpaBridge)
        if not name.startswith("_") and callable(getattr(GrandpaBridge, name, None))
    }

    assert methods == {"send", "transcribe"}


# --- send -------------------------------------------------------------------------


def test_send_routes_text_and_returns_the_reply() -> None:
    responder = Responder()

    reply = InProcessBridge(responder=responder).send("open notepad")

    assert responder.seen == ["open notepad"]
    assert reply == BridgeReply("done", status="ok", failed=False)


def test_send_trims_and_refuses_nothing_for_empty_text() -> None:
    responder = Responder()

    reply = InProcessBridge(responder=responder).send("   ")

    assert responder.seen == []
    assert reply.status == "empty"
    assert reply.failed is False


def test_a_voice_error_is_returned_not_raised() -> None:
    """A UI that has to catch its own model layer shows a traceback in a
    300-pixel window."""
    responder = Responder(raises=VoiceRecognitionError())

    reply = InProcessBridge(responder=responder).send("hello")

    assert reply.failed is True
    assert reply.status == "error"
    assert "\n" not in reply.text, "only the first line belongs in a bubble"


def test_an_unexpected_exception_is_also_returned() -> None:
    responder = Responder(raises=RuntimeError("engine exploded"))

    reply = InProcessBridge(responder=responder).send("hello")

    assert reply.failed is True
    assert "RuntimeError" in reply.text
    assert "engine exploded" in reply.detail


@pytest.mark.parametrize("status", ["error", "refused", "blocked"])
def test_a_refusing_status_is_marked_failed(status: str) -> None:
    """So a UI can style it without parsing prose."""
    responder = Responder(reply=Reply("I will not do that.", status=status))

    reply = InProcessBridge(responder=responder).send("do it")

    assert reply.failed is True


def test_an_ordinary_status_is_not_marked_failed() -> None:
    responder = Responder(reply=Reply("Sure.", status="ok"))

    assert InProcessBridge(responder=responder).send("hi").failed is False


# --- transcribe -------------------------------------------------------------------


def test_transcribe_prefers_the_trusted_path() -> None:
    """It disables the suppression that discards quiet-but-real speech."""
    transcriber = Transcriber()

    outcome = InProcessBridge(transcriber=transcriber).transcribe("audio")

    assert transcriber.seen == ["audio"]
    assert outcome == BridgeTranscript(
        "open notepad", reason="", explanation="nothing recognisable was in it"
    )
    assert outcome.empty is False


def test_an_empty_transcript_is_an_answer_with_a_reason() -> None:
    transcriber = Transcriber(
        outcome=Trusted(
            text="", reason="repetition_filtered",
            explanation="the decode came back as a repetition loop",
        )
    )

    outcome = InProcessBridge(transcriber=transcriber).transcribe("audio")

    assert outcome.empty is True
    assert outcome.reason == "repetition_filtered"
    assert "repetition loop" in outcome.explanation


def test_a_transcriber_without_the_trusted_path_still_works() -> None:
    class Old:
        def transcribe(self, audio: Any) -> str:
            return "  hello  "

    assert InProcessBridge(transcriber=Old()).transcribe("a").text == "hello"


def test_a_raising_transcriber_is_caught() -> None:
    class Raising:
        def transcribe(self, audio: Any) -> str:
            raise VoiceRecognitionError()

    outcome = InProcessBridge(transcriber=Raising()).transcribe("a")

    assert outcome.empty is True
    assert outcome.reason == "error"
    assert outcome.explanation


# --- warming ----------------------------------------------------------------------


def test_warm_reports_failure_rather_than_raising() -> None:
    """The caller puts the detail in a status line."""
    bridge = InProcessBridge(transcriber_factory=lambda: (_ for _ in ()).throw(
        RuntimeError("no model")
    ))

    ready, detail = bridge.warm()

    assert ready is False
    assert "no model" in detail
    assert bridge.speech_ready is False


def test_speech_ready_is_false_until_warmed() -> None:
    bridge = InProcessBridge(transcriber=Transcriber())

    assert bridge.speech_ready is False


def test_warm_silences_the_download_progress_bars() -> None:
    """They used to draw over the prompt in accuracy-test."""
    import inspect

    source = inspect.getsource(InProcessBridge.warm)

    assert "quiet_model_downloads" in source


# --- the collaborators are built lazily -------------------------------------------


def test_nothing_is_constructed_until_it_is_needed() -> None:
    """A UI must be able to exist before a model has loaded.

    The status line's whole job is to say "not ready yet", which it cannot do if
    constructing the bridge already blocked on a download.
    """
    bridge = InProcessBridge()

    assert bridge.responder is None
    assert bridge.transcriber is None


def test_the_factories_are_injectable_so_no_test_loads_a_model() -> None:
    built: list[str] = []
    bridge = InProcessBridge(
        responder_factory=lambda: built.append("responder") or Responder(),
        transcriber_factory=lambda: built.append("transcriber") or Transcriber(),
    )

    bridge.send("hello")
    bridge.transcribe("audio")

    assert built == ["responder", "transcriber"]
