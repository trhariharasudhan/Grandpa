"""A memory miss must not answer. Only a hit may.

Reported, three turns:

    Q: what is my sister name and is she elder or younger
    A: I do not know your sister name and is she elder or younger yet.
    Q: she name is Swaathi Sri
    A: Your sister's name is Swaathi Sri. However, I don't have any
       information about her age relative to you.
    Q: what is my sister name and is she elder or younger   (same as turn 1)
    A: I do not know your sister name and is she elder or younger yet.

Turn 2 proves the model could answer -- the name was one turn back in the
conversation. Turns 1 and 3 never reached it.

Three layers had to be opened, each hiding the next:

1. ``_recall_personal_attribute`` returned ``MemoryCommandResult("handled",
   ...)`` on a miss, and ``should_fallback`` defaults to False.
2. chat does not call ``handle_memory_command`` at all -- it goes through
   ``build_memory_request`` and ``execute_action`` and continued on any
   request it could BUILD, never asking whether the lookup found anything.
3. the action-layer executor copied ``status``, ``target`` and ``kind`` out of
   the domain result and dropped ``should_fallback``, so even once chat looked
   for the flag it was not there.
"""

from __future__ import annotations

import inspect

import pytest

from grandpa.action_layer.executor import execute
from grandpa.cli._memory_route import memory_is_miss, memory_request
from grandpa.memory_context import MemoryCommandResult, _unknown


def _run(text: str):
    request, _subject = memory_request(text)
    assert request is not None, f"no memory request built for {text!r}"
    return execute(request, lambda *_: True)


# --- the miss falls through -------------------------------------------------


def test_unknown_sets_should_fallback() -> None:
    result = _unknown("sister", 'I have no saved value for "sister" yet.')

    assert result.should_fallback is True
    # The message is kept for the brain record; it just stops being the answer.
    assert "sister" in result.message


def test_a_plain_handled_result_still_answers() -> None:
    """A hit must keep answering directly. The fix is not "never answer"."""
    hit = MemoryCommandResult("handled", "memory", "colour", "green", "green")

    assert hit.should_fallback is False


@pytest.mark.real_actions(
    reason="runs the real memory domain against the per-test sandbox store; "
    "it reads an empty SQLite file and writes nothing"
)
def test_the_reported_question_is_a_miss_and_falls_through() -> None:
    """The exact question from the report, through the real action layer."""
    result = _run("what is my sister name and is she elder or younger")

    assert memory_is_miss(result) is True, (
        "a lookup that found nothing must not be the user's answer"
    )


@pytest.mark.real_actions(reason="same real memory domain, empty sandbox store")
def test_the_executor_carries_the_flag() -> None:
    """Layer three. The executor copied three scalars and dropped this one."""
    result = _run("what is my name")

    assert result.data.get("should_fallback") is True
    # And the three it always carried are still there.
    assert result.data.get("status") == "handled"
    assert result.data.get("kind") == "memory"


def test_the_executor_does_not_invent_the_flag() -> None:
    """Only a domain that asks for fall-through gets it.

    A blanket default would send every successful action back to the model.
    """
    # _as_result, not execute: the adaptation from a domain's own result type
    # into an ActionResult is where the three scalars were copied and this one
    # was dropped.
    from grandpa.action_layer.executor import _as_result

    source = inspect.getsource(_as_result)

    assert "should_fallback" in source
    assert "isinstance(fallback, bool)" in source


def test_chat_answers_only_on_a_hit() -> None:
    """Layer two, pinned mechanically.

    The branch continued on any request it could build. A future edit that
    drops the miss check restores the reported defect, and no unit test of the
    memory domain alone would notice.
    """
    from grandpa.cli import chat_cmd

    source = inspect.getsource(chat_cmd.chat.callback)
    start = source.index("build_memory_request(")
    window = source[start : start + 1800]

    assert "memory_is_miss(" in window, (
        "chat must ask whether the lookup found anything before answering"
    )
    guard = window.index("memory_is_miss(")
    render = window.index("render_assistant_response", guard)
    assert guard < render, "the miss check must come before the reply is drawn"


# --- how many layers could do this -----------------------------------------


def test_every_personal_knowledge_miss_falls_through() -> None:
    """Twelve deterministic negative answers were found; nine are these.

    The other three -- "I could not find a routine named X", "I could not find
    a document matching X", "I could not find <path>" -- are deliberately left
    answering directly. They are about state the product OWNS, where the model
    cannot know better and would invent a routine or a file. Different failure
    mode, opposite fix.
    """
    import grandpa.memory_context as memory

    for name in (
        "_recall",
        "_preference_recall",
        "_project_recall",
        "_recall_personal_attribute",
        "_apps_opened_today",
        "_recent_activity",
        "_continue_project",
        "_recall_specific",
    ):
        source = inspect.getsource(getattr(memory, name))
        assert "_unknown(" in source, f"{name} still answers its own miss"


def test_a_named_thing_that_does_not_exist_still_answers_directly() -> None:
    """The deliberate exception, so the distinction is recorded as a decision
    rather than looking like an oversight."""
    from pathlib import Path

    scheduler = Path("src/grandpa/task_scheduler.py").read_text(encoding="utf-8")

    assert "I could not find a routine named" in scheduler
    # And it is NOT routed through the fall-through helper.
    assert "_unknown(" not in scheduler


# --- the template ------------------------------------------------------------


def test_a_reply_built_from_the_users_words_quotes_them() -> None:
    """The attribute capture is ``(.+)$`` -- everything after "my" -- so for
    "what is my sister name and is she elder or younger" it is a whole clause,
    not a noun. Inlined, it produced "I do not know your sister name and is
    she elder or younger yet." Quoted, any capture reads as a sentence."""
    import grandpa.memory_context as memory

    source = inspect.getsource(memory._recall_personal_attribute)

    assert 'f\'I have no saved value for "{attribute.strip()}" yet.\'' in source, (
        "the user's words must be quoted, not inlined into a sentence frame"
    )
    assert "I do not know your {attribute" not in source
