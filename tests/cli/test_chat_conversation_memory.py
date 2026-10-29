"""The chat path has to remember the question it just asked.

Reported, and reproduced exactly:

    me:      give me 5 pint of weather today
    Grandpa: ...which city or region you're interested in?
    me:      salem
    Grandpa: Hello, Salem! How can I assist you today?

Dumped from a real session, the second request was literally
``[system, user:"salem"]`` and nothing else. ``chat_cmd`` did assemble
``model_history`` with the full conversation -- and then used it only on the
no-agent branch, while ``agent.run(effective_user_input)`` took the current
message alone. With the default agent configured, every turn was a fresh
single-turn prompt.

These tests pin the mechanism rather than the model's wording. A model's reply
is not a test fixture; what is testable is whether the prior exchange reaches
the request, which is the thing that was missing.
"""

from __future__ import annotations

import inspect

from grandpa.cli import chat_cmd
from grandpa.cli.theme import ACCENT, CHAT_THEME, INLINE_CODE, TEXT_ACCENT
from grandpa.core.types import CONVERSATION_WINDOW_MESSAGES, Message, Role


def _exchange(count: int) -> list[Message]:
    """``count`` user/assistant pairs, then a trailing user turn."""
    history = [Message(role=Role.SYSTEM, content="system prompt")]
    for index in range(count):
        history.append(Message(role=Role.USER, content=f"question {index}"))
        history.append(Message(role=Role.ASSISTANT, content=f"answer {index}"))
    history.append(Message(role=Role.USER, content="salem"))
    return history


# --- what the agent is handed ------------------------------------------------


def test_the_prior_exchange_is_carried_into_the_next_turn() -> None:
    """The defect in one assertion: the question must still be there."""
    history = [
        Message(role=Role.SYSTEM, content="system prompt"),
        Message(role=Role.USER, content="give me 5 pint of weather today"),
        Message(
            role=Role.ASSISTANT,
            content="Could you share the city or region you're interested in?",
        ),
        Message(role=Role.USER, content="salem"),
    ]

    carried = chat_cmd._recent_exchanges(history)

    assert [m.role for m in carried] == [Role.USER, Role.ASSISTANT]
    assert "weather" in carried[0].content
    assert "city or region" in carried[1].content, (
        "the assistant's own question is what makes 'salem' an answer rather "
        "than a greeting"
    )


def test_the_current_turn_is_not_sent_twice() -> None:
    """``BaseAgent._build_messages`` appends the input itself.

    Passing it in the context as well would put "salem" in the request twice,
    which reads as the user repeating themselves.
    """
    carried = chat_cmd._recent_exchanges(_exchange(1))

    assert all(m.content != "salem" for m in carried)


def test_the_system_message_is_not_carried() -> None:
    """The agent supplies its own system prompt.

    A second one in the context either duplicates it or, through
    ``_build_messages``'s ``_context_has_system`` branch, silently suppresses
    the agent's -- changing behaviour by accident.
    """
    carried = chat_cmd._recent_exchanges(_exchange(2))

    assert all(m.role != Role.SYSTEM for m in carried)


def test_the_window_is_capped() -> None:
    """This path pays ~20s a turn and prompt evaluation scales with length."""
    carried = chat_cmd._recent_exchanges(_exchange(40))

    assert len(carried) <= CONVERSATION_WINDOW_MESSAGES
    # The cap keeps the NEWEST turns; dropping the recent ones would lose the
    # question being answered, which is the whole point.
    assert carried[-1].content == "answer 39"


def test_an_empty_conversation_carries_nothing() -> None:
    """The first turn of a session has no prior exchange, and that is fine."""
    assert chat_cmd._recent_exchanges([]) == []
    assert (
        chat_cmd._recent_exchanges(
            [Message(role=Role.SYSTEM, content="system prompt")]
        )
        == []
    )


def test_the_agent_call_site_passes_a_context() -> None:
    """Mechanical, because the failure was mechanical.

    ``model_history`` sat two lines above the call and was not passed. A future
    edit that drops the context argument restores the reported defect exactly,
    and no unit test of a pure helper would notice.
    """
    # .callback, because click wraps the function in a Command object.
    source = inspect.getsource(chat_cmd.chat.callback)
    call = source[source.index("if agent is not None:") :]
    call = call[: call.index("else:")]

    assert "context=" in call, (
        "agent.run must be given the conversation; without it every turn is a "
        "fresh single-turn prompt"
    )
    assert "_recent_exchanges" in call


# --- the panel and the CLI agree ---------------------------------------------


def test_the_panel_windows_to_the_same_number() -> None:
    """They diverged in opposite directions.

    Chat sent no history at all. The voice path -- which the panel uses --
    sent ``*self.history`` unbounded, growing for the life of the process. One
    constant now governs both, so a follow-up behaves the same whichever
    surface asked it.
    """
    from grandpa.voice import assistant as voice_assistant

    source = inspect.getsource(voice_assistant.VoiceCommandProcessor)

    assert "self.history[-CONVERSATION_WINDOW_MESSAGES:]" in source, (
        "the voice path must window its history to the shared number"
    )
    assert "*self.history," not in source, (
        "an unbounded history is sent on a path that already costs ~20s a turn"
    )


# --- the banner says what the product is, diagnostics say what is running ----


def test_the_banner_does_not_name_the_runtime_vendor() -> None:
    from grandpa.cli import interactive_tui

    source = inspect.getsource(interactive_tui.render_startup_header)

    assert "engine_label" not in source
    assert "engine_name" not in source, (
        "the startup banner is the product speaking; which backend serves the "
        "model is an implementation detail"
    )


def test_diagnostics_still_name_the_runtime() -> None:
    """Display-only, and only display.

    This project already has a bug where a model is told it is a different
    model. The surfaces whose job is to report reality must keep doing it.
    """
    from grandpa.cli import interactive_tui

    for function in (interactive_tui._doctor, interactive_tui._config):
        assert "engine_name" in inspect.getsource(function), (
            f"{function.__name__} must still report the real engine"
        )


# --- inline code reads as a literal, not as emphasis ------------------------


def test_inline_code_is_a_muted_cyan_distinct_from_name_and_amber() -> None:
    assert CHAT_THEME.styles["markdown.code"].color.triplet.hex.lower() == (
        INLINE_CODE.lower()
    )
    assert INLINE_CODE != TEXT_ACCENT, "inline code must not reuse the name blue"
    assert INLINE_CODE != ACCENT, "inline code must not be the orb's thinking amber"


def test_inline_code_has_no_background_and_no_bold() -> None:
    """The black box and the bold were what made a literal read as emphasis."""
    style = CHAT_THEME.styles["markdown.code"]

    assert style.bgcolor is None
    assert not style.bold


def test_inline_code_is_readable_on_a_dark_terminal() -> None:
    """Measured, not assumed: WCAG contrast against the usual dark grounds."""

    def _channel(value: float) -> float:
        value /= 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    def _luminance(colour: str) -> float:
        raw = colour.lstrip("#")
        r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)

    def _contrast(one: str, two: str) -> float:
        a, b = _luminance(one), _luminance(two)
        return (max(a, b) + 0.05) / (min(a, b) + 0.05)

    for background in ("#0c0c0c", "#1e1e1e"):
        ratio = _contrast(INLINE_CODE, background)
        assert ratio >= 4.5, (
            f"{INLINE_CODE} on {background} is {ratio:.2f}:1, below the 4.5:1 "
            "AA threshold for body text"
        )
