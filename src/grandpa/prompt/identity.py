"""Canonical Grandpa product identity for conversational model requests."""

from __future__ import annotations

import re
from collections.abc import Sequence

from grandpa.core.types import Message, Role
from grandpa.intelligence.grandpa_models import get_model_role

GRANDPA_IDENTITY_PROMPT = """## Canonical Grandpa Identity
Your name and product identity are Grandpa, a local AI assistant.
Odin is the internal name of Grandpa's model family; do not introduce yourself as Grandpa Odin unless technical architecture is explicitly requested.
In ordinary conversation, identify yourself as Grandpa. Do not spontaneously identify as Qwen, Gemma, DeepSeek, Llama, LLaVA, Ollama, Alibaba, Google, or Meta.
Do not claim that Grandpa created or owns the underlying foundation-model weights.
If explicitly asked what model or technology powers this session, answer truthfully: state that you are Grandpa, name the active Grandpa role when available, and describe the underlying local model family without pretending it is your product identity.
Preserve the user's configured name and profile handling. Never invent a personal name."""

GENERAL_CONVERSATION_PROMPT = """## General Conversation Reliability
Answer harmless general-knowledge, educational, casual, and mathematical questions normally.
Lack of live web access is not a reason to refuse a harmless question; answer from established knowledge when reasonably confident.
Never invent names, dates, affiliations, quotations, or technical details to make an answer sound complete.
When a fact is uncertain or outside reliable knowledge, say so briefly and distinguish what is known from what is uncertain.
Reserve safety refusals for genuinely unsafe requests. An unfamiliar, broad, or imperfectly phrased question is not unsafe.
Keep answers concise and directly responsive unless the user asks for detail."""


def identity_prompt(model: str | None = None) -> str:
    """Return canonical identity plus truthful runtime-role metadata."""

    entry = get_model_role(model)
    if entry is None:
        return f"{GRANDPA_IDENTITY_PROMPT}\n\n{GENERAL_CONVERSATION_PROMPT}"
    return (
        f"{GRANDPA_IDENTITY_PROMPT}\n"
        f"Active Grandpa role: {entry.role}.\n"
        f"Runtime tag: {entry.ollama_tag}.\n"
        f"Underlying foundation family: {entry.base_family}.\n\n"
        f"{GENERAL_CONVERSATION_PROMPT}"
    )


def resolve_identity_response(text: str, model: str | None = None) -> str | None:
    """Return deterministic product identity answers for conversational clients."""

    normalized = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
    if normalized in {"who are you", "what are you", "what is your name"}:
        return "I'm Grandpa, your local AI assistant."
    if normalized == "who is odin":
        return "Odin is the internal codename for Grandpa's model family."
    if normalized in {
        "are you chatgpt",
        "are you gemini",
        "are you google gemini",
        "are you qwen",
    }:
        return "No. I'm Grandpa, your local AI assistant."
    if normalized in {
        "what model powers you",
        "which model powers you",
        "what model are you using",
    }:
        entry = get_model_role(model)
        if entry is None:
            return "I'm Grandpa, running on a local AI model."
        return (
            f"I'm Grandpa. This session uses {entry.display_name}, backed by "
            f"a local {entry.base_family} foundation model through Ollama."
        )
    return None


def ensure_grandpa_identity(
    messages: Sequence[Message], model: str | None = None
) -> list[Message]:
    """Prepend identity or extend the first system message without replacing it."""

    result = list(messages)
    prompt = identity_prompt(model)
    if result and result[0].role == Role.SYSTEM:
        if "## Canonical Grandpa Identity" not in result[0].content:
            result[0] = Message(
                role=Role.SYSTEM,
                content=f"{prompt}\n\n## Role Instructions\n{result[0].content}",
            )
        return result
    return [Message(role=Role.SYSTEM, content=prompt), *result]


__all__ = [
    "GENERAL_CONVERSATION_PROMPT",
    "GRANDPA_IDENTITY_PROMPT",
    "ensure_grandpa_identity",
    "identity_prompt",
    "resolve_identity_response",
]
