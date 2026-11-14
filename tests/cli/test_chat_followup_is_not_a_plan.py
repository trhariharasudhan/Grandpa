"""A conversational follow-up belongs to the model, not to a plan.

Reported, and reproduced through the real chat loop:

    me:      tell me about the Chola dynasty
    Grandpa: <an answer>
    me:      summarise that in 3 points
    Grandpa: Agent plan goal completed: browser research.
             - Phase: completed
             - Confidence: 82%
             - Risk: LOW
             - Skills: browser.diagnostics, browser.search_plan, ...
             - Actions taken: 3
             Goal completed with 3 safe step(s).

Two defects met there. ``planner.classify_goal`` read the bare word
"summarise" anywhere in a request as a research intent, so a follow-up with
no subject of its own became a three-step browser plan; and once a plan ran,
``legacy_adapter``/``local.execute`` printed the plan object as the reply.

Behind the first one stood a second claimant: ``file_assistant`` matched
``summari[sz]e (.+)`` and handed the rest of the sentence to its document
search, which answered "I could not find a document matching that in 3
points". A fix to the planner alone moved the bug rather than closing it,
which is why these tests go through ``chat`` rather than through either
classifier.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from grandpa.cli.chat_cmd import chat
from grandpa.core.config import GrandpaConfig
from grandpa.planner import classify_goal, refers_to_prior_turn

PLAN_INTERNALS = ("Phase:", "Confidence:", "Risk:", "Skills:", "Actions taken")


def _stub_engine(answer: str) -> MagicMock:
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.supports_streaming = False
    engine.generate.return_value = {"content": answer}
    engine.health.return_value = True
    return engine


def _chat(lines: str, answer: str = "Model answer.") -> tuple[str, MagicMock]:
    """Drive the real chat loop, default agent and all, over ``lines``."""
    from click.testing import CliRunner

    engine = _stub_engine(answer)
    config = GrandpaConfig()
    config.intelligence.default_model = "test-model"

    with (
        patch("grandpa.cli.chat_cmd.load_config", return_value=config),
        patch("grandpa.engine.get_engine", return_value=("mock", engine)),
        patch("grandpa.intelligence.register_builtin_models"),
    ):
        result = CliRunner().invoke(chat, ["--model", "test-model"], input=lines)

    assert result.exit_code == 0, result.output
    return result.output, engine


# --- the reported turn -------------------------------------------------------


def test_a_follow_up_in_chat_is_answered_rather_than_planned() -> None:
    """The defect in one test: turn 2 must not come back as a plan."""
    output, engine = _chat(
        "tell me about the Chola dynasty\nsummarise that in 3 points\n/quit\n",
        answer="The Cholas ruled from Thanjavur.",
    )

    assert "browser research" not in output
    assert "Goal completed" not in output
    for internal in PLAN_INTERNALS:
        assert internal not in output, f"{internal!r} is internal to the planner"
    assert "could not find a document" not in output, (
        "the document search is the second claimant on a bare 'summarise'"
    )
    assert engine.generate.call_count == 2, (
        "both turns are questions for the model, so both have to reach it"
    )


def test_the_follow_up_reaches_the_model_with_the_question_it_follows() -> None:
    """The word "that" only means something next to the turn before it."""
    _, engine = _chat(
        "tell me about the Chola dynasty\nsummarise that in 3 points\n/quit\n"
    )

    second = engine.generate.call_args_list[1]
    sent = " ".join(message.content for message in second.args[0])
    assert "Chola" in sent
    assert "summarise that in 3 points" in sent


# --- the classifier, which is where the first defect was ---------------------


@pytest.mark.parametrize(
    "request_text",
    (
        "summarise that in 3 points",
        "summarize that",
        "can you summarise that in 3 points",
        "explain it again",
        "shorten this",
        "rephrase that more briefly",
        "recap the above",
        "expand on that",
        "summarise your answer",
        "research that",
    ),
)
def test_a_request_whose_only_object_is_the_last_turn_is_not_a_goal(
    request_text: str,
) -> None:
    assert refers_to_prior_turn(request_text) is True
    assert classify_goal(request_text) == "general"


@pytest.mark.parametrize(
    "request_text",
    (
        "research python tutorials and summarize them",
        "research the chola dynasty",
        "summarize current webpage and save notes",
        "find a tutorial on rust",
    ),
)
def test_a_request_that_names_its_own_subject_still_reaches_the_planner(
    request_text: str,
) -> None:
    """Here "them" points at the tutorials the same sentence just named."""
    assert refers_to_prior_turn(request_text) is False
    assert classify_goal(request_text) == "browser_research"


def test_a_sentence_shape_cannot_step_around_the_dangerous_class() -> None:
    """The class that exists to refuse is not something a follow-up suppresses."""
    assert classify_goal("delete that") == "dangerous"
    assert classify_goal("summarise that and then wipe the disk") == "dangerous"


# --- the leak, which any plan path could hit ---------------------------------


@pytest.mark.real_actions(
    reason="the plan's first step is the real browser diagnostics, which only "
    "reads adapter state; the goal store is redirected to tmp_path"
)
def test_a_plan_turn_states_what_was_done_without_the_plan_object(
    tmp_path, monkeypatch
) -> None:
    """A real plan still runs; what it prints is a sentence."""
    monkeypatch.setenv("GRANDPA_AGENT_GOALS_DB", str(tmp_path / "goals.db"))

    output, _ = _chat("research python tutorials and summarize\n/quit\n")

    for internal in PLAN_INTERNALS:
        assert internal not in output, f"{internal!r} is internal to the planner"
    assert "browser.diagnostics" not in output
    assert "Research plan prepared" in output


def test_the_renderer_speaks_for_a_goal_in_every_state() -> None:
    from grandpa.agents.goal_mode import AgentGoal, describe_goal

    def goal(**fields) -> AgentGoal:
        base = {
            "goal_id": "goal_1",
            "user_request": "research python tutorials",
            "status": "completed",
            "plan": {
                "intent": "browser research",
                "confidence": 0.82,
                "estimated_risk": "LOW",
                "required_skills": ["browser.diagnostics"],
            },
            "current_phase": "completed",
        }
        base.update(fields)
        return AgentGoal(**base)

    done = describe_goal(goal(result_summary="Goal completed with 3 safe step(s)."))
    assert done == "Goal completed with 3 safe step(s)."

    waiting = describe_goal(
        goal(
            status="waiting_approval",
            current_phase="waiting_approval",
            approvals_needed=[{"step_id": "step_2", "skill": "desktop.keyboard_type"}],
        )
    )
    assert "approval" in waiting.lower()
    assert "step_2" not in waiting, "a step id is not something a user can act on"

    failed = describe_goal(goal(status="failed", current_phase="failed"))
    assert failed == "I could not complete that."

    for text in (done, waiting, failed):
        assert "0.82" not in text and "82%" not in text
        assert "browser.diagnostics" not in text
        assert "LOW" not in text
