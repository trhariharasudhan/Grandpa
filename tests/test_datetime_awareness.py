import datetime
import pytest
from grandpa.core.runtime_context import (
    set_mock_now,
    get_runtime_context,
    get_runtime_context_prompt,
    handle_datetime_intent,
)
from grandpa.core_ai_brain import build_brain_context, BrainAnalysis
from grandpa.prompt.builder import SystemPromptBuilder


@pytest.fixture
def mock_frozen_time():
    # Freeze time to: Sunday, August 2, 2026 at 6:30:00 PM with Asia/Kolkata timezone offset (+5:30)
    tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="Asia/Kolkata")
    dt = datetime.datetime(2026, 8, 2, 18, 30, 0, tzinfo=tz)
    set_mock_now(dt)
    yield dt
    set_mock_now(None)


def test_frozen_time_expected_values(mock_frozen_time):
    ctx = get_runtime_context()
    assert "Sunday" in ctx["local_date"]
    assert "August 2, 2026" in ctx["local_date"]
    assert "6:30 PM" == ctx["local_time"]
    assert "Asia/Kolkata" == ctx["timezone"]
    assert "2026-08-02T18:30:00+05:30" == ctx["iso_timestamp"]


def test_date_intent_variations(mock_frozen_time):
    # Standard date queries
    assert handle_datetime_intent("What is today's date?") == "Today is Sunday, August 2, 2026."
    assert handle_datetime_intent("what date is it today?") == "Today is Sunday, August 2, 2026."
    assert handle_datetime_intent("date today") == "Today is Sunday, August 2, 2026."
    assert handle_datetime_intent("todays date") == "Today is Sunday, August 2, 2026."

    # Day queries
    assert handle_datetime_intent("What day is it today?") == "Today is Sunday, August 2, 2026."
    assert handle_datetime_intent("what day today?") == "Today is Sunday, August 2, 2026."
    assert handle_datetime_intent("Which day today?") == "Today is Sunday, August 2, 2026."
    assert handle_datetime_intent("what is that day today?") == "Today is Sunday, August 2, 2026."
    assert handle_datetime_intent("todays day?") == "Today is Sunday, August 2, 2026."


def test_time_intent_variations(mock_frozen_time):
    assert handle_datetime_intent("What is the current time?") == "It is 6:30 PM on Sunday, August 2, 2026."
    assert handle_datetime_intent("what time is it?") == "It is 6:30 PM on Sunday, August 2, 2026."
    assert handle_datetime_intent("current timing") == "It is 6:30 PM on Sunday, August 2, 2026."
    assert handle_datetime_intent("current time") == "It is 6:30 PM on Sunday, August 2, 2026."


def test_year_and_month_intents(mock_frozen_time):
    assert handle_datetime_intent("what year is it?") == "The current year is 2026."
    assert handle_datetime_intent("what year is this?") == "The current year is 2026."
    assert handle_datetime_intent("which month is this?") == "The current month is August."
    assert handle_datetime_intent("current month") == "The current month is August."


def test_user_dispute_override(mock_frozen_time):
    # User tries to correct date/time to a false value
    response = handle_datetime_intent("No, today is May 20, 2023")
    assert response == "According to this computer's system clock, today is Sunday, August 2, 2026."

    response = handle_datetime_intent("No, that date is wrong. Today is August 15, 2023.")
    assert response == "According to this computer's system clock, today is Sunday, August 2, 2026."


def test_intent_false_positives(mock_frozen_time):
    # Phrases containing day/time/year but not asking for current clock
    assert handle_datetime_intent("Tell me about a day in history") is None
    assert handle_datetime_intent("Do you have time for a game?") is None
    assert handle_datetime_intent("Happy New Year!") is None
    assert handle_datetime_intent("what is your name") is None


def test_prompt_injection_brain_context(mock_frozen_time):
    analysis = BrainAnalysis(
        original_text="hello",
        effective_text="hello",
        language="en",
        tone="neutral",
        confidence=1.0,
        follow_up_resolved=False,
    )
    brain_prompt = build_brain_context(analysis)
    assert "## Trusted Runtime Context" in brain_prompt
    assert "Current local date: Sunday, August 2, 2026" in brain_prompt
    assert "Current local time: 6:30 PM" in brain_prompt


def test_prompt_injection_builder(mock_frozen_time):
    builder = SystemPromptBuilder(agent_template="You are a helper.")
    prompt = builder.build()
    assert "## Trusted Runtime Context" in prompt
    assert "Current local date: Sunday, August 2, 2026" in prompt
    assert "Current local time: 6:30 PM" in prompt


from grandpa.voice.cli_session import is_prompt_echo, is_exit_phrase
from grandpa.voice.text_to_speech import GrandpaTextToSpeech
import sys
import threading
from unittest.mock import MagicMock, patch

def test_whisper_prompt_echo():
    assert is_prompt_echo("Grandpa assistant.") is True
    assert is_prompt_echo("Ollama. The current year") is True
    assert is_prompt_echo("may be 2026") is True
    assert is_prompt_echo("Grandpa assistant. Ollama. The current year may be 2026.") is True
    
    assert is_prompt_echo("what is today's date") is False
    assert is_prompt_echo("goodbye") is False
    assert is_prompt_echo("stop listening") is False
    assert is_prompt_echo("hello") is False
    assert is_prompt_echo("grandpa") is False
    assert is_prompt_echo("current year") is False
    assert is_prompt_echo("year 2026") is False

def test_exit_phrase_variations():
    assert is_exit_phrase("stop listening") is True
    assert is_exit_phrase("please stop listening") is True
    assert is_exit_phrase("stop listen") is True
    assert is_exit_phrase("goodbye") is True
    assert is_exit_phrase("exit voice") is True
    assert is_exit_phrase("exit voice mode") is True
    
    assert is_exit_phrase("Grandpa assistant. Ollama.") is False

def test_tts_worker_thread_com_init():
    fake_engine = MagicMock()
    fake_result = MagicMock()
    fake_result.status = "completed"
    fake_engine.speak.return_value = fake_result
    
    tts = GrandpaTextToSpeech(enabled=True)
    tts._engine = fake_engine
    
    co_init_mock = MagicMock()
    co_uninit_mock = MagicMock()
    
    modules = {
        "pythoncom": MagicMock(CoInitialize=co_init_mock, CoUninitialize=co_uninit_mock)
    }
    
    with patch.dict(sys.modules, modules):
        stop_event = threading.Event()
        with patch("sys.platform", "win32"):
            tts.speak("test audio", stop_event=stop_event)
            assert co_init_mock.called
            assert co_uninit_mock.called

def test_tts_fallback_raises_exception():
    fake_engine = MagicMock()
    fake_result = MagicMock()
    fake_result.status = "fallback"
    fake_result.message = "Speech output failed"
    fake_result.error = "COM Error"
    fake_engine.speak.return_value = fake_result
    
    tts = GrandpaTextToSpeech(enabled=True)
    tts._engine = fake_engine
    
    with pytest.raises(RuntimeError, match="TTS backend failed"):
        tts.speak("test text")
        
    stop_event = threading.Event()
    with pytest.raises(RuntimeError, match="TTS backend failed"):
        tts.speak("test text", stop_event=stop_event)
