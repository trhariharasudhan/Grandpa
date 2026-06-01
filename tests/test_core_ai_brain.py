from __future__ import annotations

from grandpa.core_ai_brain import (
    BrainAnalysis,
    BrainStore,
    analyze_user_text,
    build_brain_context,
    detect_language,
    detect_tone,
    record_assistant_outcome,
)
from grandpa.memory_context import MemoryStore, handle_memory_command


def test_follow_up_resolves_close_that(tmp_path):
    store = BrainStore(tmp_path / "brain.db")
    first = analyze_user_text("open notepad", store=store)
    record_assistant_outcome(
        first,
        assistant_text="Opening Notepad.",
        kind="app",
        target="notepad",
        status="handled",
        store=store,
    )

    follow = analyze_user_text("close that", store=store)

    assert follow.follow_up_resolved is True
    assert follow.effective_text == "close Notepad"
    assert follow.confidence >= 0.8


def test_summarize_again_resolves_browser_context(tmp_path):
    store = BrainStore(tmp_path / "brain.db")
    first = analyze_user_text("summarize this webpage", store=store)
    record_assistant_outcome(
        first,
        assistant_text="Visible page summary: Hello.",
        kind="browser",
        target="summary|visible",
        status="handled",
        store=store,
    )

    follow = analyze_user_text("summarize again", store=store)

    assert follow.effective_text == "summarize this webpage"


def test_tamil_english_language_continuity():
    assert detect_language("Grandpa open pannuda") == "en"
    assert detect_language("Grandpa என்ன project?") == "ta-en"


def test_tone_detection():
    assert detect_tone("this is broken again") == "frustrated"
    assert detect_tone("urgent, open chrome now") == "urgent"
    assert detect_tone("why is this happening?") == "confused"


def test_habit_learning_counts_repeated_apps(tmp_path):
    store = BrainStore(tmp_path / "brain.db")
    for _ in range(3):
        analysis = analyze_user_text("open chrome", store=store)
        record_assistant_outcome(
            analysis,
            assistant_text="Opening Chrome.",
            kind="app",
            target="chrome",
            status="handled",
            store=store,
        )

    habits = store.habits()

    chrome = next(item for item in habits if item["key"] == "chrome")
    assert chrome["count"] == 3
    assert store.habit_score("Chrome browser") > 0


def test_brain_context_contains_habits_and_tone(tmp_path):
    store = BrainStore(tmp_path / "brain.db")
    store.upsert_habit("preferred_tool", "vs_code", "VS Code")
    analysis = BrainAnalysis(
        original_text="enna da use panren?",
        effective_text="enna da use panren?",
        language="ta-en",
        tone="casual",
        confidence=0.7,
        follow_up_resolved=False,
    )

    context = build_brain_context(analysis, store=store)

    assert "ta-en" in context
    assert "casual" in context
    assert "VS Code" in context


def test_memory_ranking_uses_habit_boost(tmp_path, monkeypatch):
    brain_db = tmp_path / "brain.db"
    monkeypatch.setattr("grandpa.core_ai_brain.DEFAULT_BRAIN_DB", brain_db)
    BrainStore(brain_db).upsert_habit("preferred_tool", "vs_code", "VS Code")
    store = MemoryStore(tmp_path / "memory.db")
    handle_memory_command("remember I use VS Code", store=store)

    results = store.search_memories("what editor do I prefer?")

    assert results
    assert results[0]["score"] >= 0.7


def test_low_confidence_follow_up_does_not_guess(tmp_path):
    store = BrainStore(tmp_path / "brain.db")

    analysis = analyze_user_text("open it", store=store)

    assert analysis.effective_text == "open it"
    assert analysis.confidence < 0.5
