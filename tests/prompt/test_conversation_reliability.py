"""Acceptance contract for ordinary Grandpa conversation."""

from __future__ import annotations

import pytest

from grandpa.core.types import Message, Role
from grandpa.prompt.identity import ensure_grandpa_identity, resolve_identity_response


@pytest.mark.parametrize(
    "user_text",
    (
        "Name some Indian cartoons.",
        "What is Python?",
        "What is DNS?",
        "What is the capital of India?",
        "Hi",
        "Tell me a joke.",
        "How are you?",
        "What is 15 + 27?",
        "Who was the mayor of an obscure fictional town in 1842?",
    ),
)
def test_general_conversation_receives_reliability_contract(user_text: str) -> None:
    messages = ensure_grandpa_identity(
        [Message(role=Role.USER, content=user_text)],
        "grandpa-mini:latest",
    )

    assert messages[-1] == Message(role=Role.USER, content=user_text)
    system = messages[0].content
    assert "Answer harmless general-knowledge" in system
    assert "not a reason to refuse" in system
    assert "Never invent names, dates, affiliations" in system
    assert "say so briefly" in system


@pytest.mark.parametrize(
    "question",
    (
        "Who are you?",
        "What is your name?",
        "Are you Qwen?",
        "Are you Gemini?",
        "Who is Odin?",
    ),
)
def test_identity_acceptance_questions_are_resolved_locally(question: str) -> None:
    response = resolve_identity_response(question, "grandpa-mini:latest")

    assert response is not None
    assert "Google's Grandpa" not in response
    assert "OpenAI Grandpa" not in response
    assert "Microsoft Grandpa" not in response


def test_reliability_contract_preserves_real_safety_boundary() -> None:
    system = ensure_grandpa_identity([], "grandpa-mini:latest")[0].content

    assert "Reserve safety refusals for genuinely unsafe requests" in system
    assert (
        "An unfamiliar, broad, or imperfectly phrased question is not unsafe" in system
    )
