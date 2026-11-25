"""Yes/no reading and the "never claim what did not run" guard.

Every case here is a line from Captain's spoken test of 2026-11-25.
"""

from __future__ import annotations

import pytest

from grandpa.core.claims import HONEST, claims_an_action, honest_reply
from grandpa.core.consent import read_consent


@pytest.mark.parametrize(
    "said",
    [
        "yes", "Yes.", "yeah", "ok", "okay", "sure", "go ahead", "do it", "confirm",
        "Yes, confirming open Chrome.", "Confirming such a goal for Bengal weather.",
        "seri", "sari", "aama", "ok pannu", "podu", "Grandpa yes", "Hey Grandpa, yes",
    ],
)
def test_yes(said: str) -> None:
    assert read_consent(said) == "yes"


@pytest.mark.parametrize(
    "said",
    ["no", "No.", "nope", "cancel", "stop", "never mind", "don't", "wait",
     "venam", "vendam", "illa", "yes no", "yes, no wait"],
)
def test_no(said: str) -> None:
    assert read_consent(said) == "no"


@pytest.mark.parametrize(
    "said",
    [
        "", "Who is the CM of Tamil Nadu?", "How old is he?", "Notepad Open Funny.",
        "Play a YouTube video for 5 minutes.", "ok what is the weather in Salem today",
        "Open Calculator",
    ],
)
def test_a_new_request_is_not_an_answer(said: str) -> None:
    assert read_consent(said) is None


@pytest.mark.parametrize(
    "reply",
    [
        "Ok, I'm up to 100%.",
        "Ok, I'm down to 50%.",
        "Ok, brightness is set to 50%, and the sound is set to a deeper level.",
        "Chrome is now open in the foreground.",
        "Understood, I will block your computer.",
        "Google is now searching for 'Bangalore' in the search results.",
        "I've opened Notepad for you.",
        "Notepad has been closed.",
    ],
)
def test_fake_actions_are_caught(reply: str) -> None:
    assert claims_an_action(reply)
    assert honest_reply(reply, acted=False) == HONEST
    assert honest_reply(reply, acted=True) == reply  # a real action may say so


@pytest.mark.parametrize(
    "reply",
    [
        "Hello! How can I help you today?",
        "I can open apps, set reminders and search the web.",
        "2 + 2 equals 4.",
        "To open Chrome, click its icon on the taskbar.",
        "I will remember that.",
        "Your favourite colour is blue.",
        "I'll vlog now. Can you tell me what you're working on?",
    ],
)
def test_ordinary_answers_pass(reply: str) -> None:
    assert honest_reply(reply, acted=False) == reply


def test_a_waiting_plan_never_traps_the_conversation(monkeypatch) -> None:
    """Lines 120-129 of the test: every new question got "Continue?" again."""
    from grandpa.planner import routing
    from grandpa.planner.models import PlanStatus

    class Waiting:
        status = PlanStatus.WAITING_FOR_CONFIRMATION
        confirmation = None

    class Planner:
        def __init__(self):
            self.cancelled = 0
            self.waiting = True

        def current(self):
            return Waiting() if self.waiting else None

        def cancel(self):
            self.cancelled += 1
            self.waiting = False

            class R:
                message = "Cancelled."

            return R()

    planner = Planner()
    session = "chat:" + str(id(None))
    monkeypatch.setitem(routing._PLANNERS, session, planner)
    out = routing.handle_executive_goal("Who is the CM of Tamil Nadu?")
    assert planner.cancelled == 1 and not planner.waiting
    assert out is None  # a one-step question: handled by the normal chat after this
