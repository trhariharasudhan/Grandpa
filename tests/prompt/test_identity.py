import pytest

from grandpa.core.types import Message, Role
from grandpa.prompt.identity import (
    GENERAL_CONVERSATION_PROMPT,
    ensure_grandpa_identity,
    identity_prompt,
    resolve_identity_response,
)


def test_identity_names_grandpa_and_discloses_known_base_truthfully() -> None:
    prompt = identity_prompt("grandpa-mini:latest")
    assert "Your name and product identity are Grandpa" in prompt
    assert "Active Grandpa role: mini" in prompt
    assert "Underlying foundation family: Qwen2.5" in prompt


def test_identity_extends_role_prompt_instead_of_replacing_it() -> None:
    messages = [
        Message(role=Role.SYSTEM, content="You are operating in coding mode."),
        Message(role=Role.USER, content="Help me."),
    ]
    result = ensure_grandpa_identity(messages, "coder")
    assert len(result) == 2
    assert "Canonical Grandpa Identity" in result[0].content
    assert "coding mode" in result[0].content
    assert "Active Grandpa role: coder" in result[0].content


def test_identity_injection_is_idempotent() -> None:
    messages = [Message(role=Role.USER, content="Hello")]
    once = ensure_grandpa_identity(messages, "mini")
    twice = ensure_grandpa_identity(once, "mini")
    assert once == twice


def test_identity_prompt_sets_general_conversation_reliability_contract() -> None:
    prompt = identity_prompt("grandpa-mini:latest")

    assert GENERAL_CONVERSATION_PROMPT in prompt
    assert "Answer harmless general-knowledge" in prompt
    assert "Lack of live web access is not a reason to refuse" in prompt
    assert "Never invent names, dates, affiliations" in prompt
    assert "Reserve safety refusals for genuinely unsafe requests" in prompt


@pytest.mark.parametrize(
    ("question", "expected"),
    (
        ("Who are you?", "I'm Grandpa, your local AI assistant."),
        ("What is your name?", "I'm Grandpa, your local AI assistant."),
        ("Are you Qwen?", "No. I'm Grandpa, your local AI assistant."),
        ("Are you Gemini?", "No. I'm Grandpa, your local AI assistant."),
        ("Are you Google Gemini?", "No. I'm Grandpa, your local AI assistant."),
        ("Who is Odin?", "Odin is the internal codename for Grandpa's model family."),
    ),
)
def test_identity_questions_have_canonical_deterministic_answers(
    question: str,
    expected: str,
) -> None:
    assert resolve_identity_response(question, "grandpa-mini:latest") == expected


def test_model_identity_discloses_product_role_and_foundation() -> None:
    response = resolve_identity_response(
        "What model powers you?",
        "grandpa-mini:latest",
    )

    assert response is not None
    assert "I'm Grandpa" in response
    assert "Grandpa Mini" in response
    assert "Qwen2.5" in response
    assert "through Ollama" in response


def test_unrelated_conversation_is_left_to_the_model() -> None:
    assert resolve_identity_response("What is Python?", "grandpa-mini:latest") is None
