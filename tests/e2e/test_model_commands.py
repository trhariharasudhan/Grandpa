"""Commands that need a local model: ask, telemetry, chat and agents.

Each test is given a model the ``e2e_model`` fixture proved, straight through the
Ollama API, can repeat a token. So when the CLI fails to return a nonce, the CLI
is at fault and the test FAILS rather than reporting COULD NOT RUN.
"""

from __future__ import annotations

import json
import re

import pytest

from tests.e2e.harness import chat_replies, ollama_models, sqlite_rows

# ...and out of the default-deny actuation fixture (tests/actuation_guard.py).
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.real_actions(
        reason="runs the real CLI as a subprocess in a throwaway sandbox, which is what this suite is for; the sandbox has its own HOME and the harness records launches and window actions instead of performing them"
    ),
]

ATTEMPTS = 3


def echo_prompt(token: str) -> str:
    return f"Reply with exactly this word and nothing else: {token}"


def _note_titles(grandpa_home) -> list[str]:
    notes_dir = grandpa_home / "notes"
    if not notes_dir.is_dir():
        return []
    return [
        match.group(1)
        for path in notes_dir.glob("*.md")
        if (match := re.search(r'"title": "([^"]+)"', path.read_text(encoding="utf-8")))
    ]


# 1 ---------------------------------------------------------------------------
# Plain `ask` goes through the configured default agent; `--agent ""` goes
# straight to the engine. They print from different code, so both are covered.
@pytest.mark.parametrize(
    "mode", [(), ("--agent", "")], ids=["default-agent", "direct-engine"]
)
def test_ask_returns_what_the_model_generated(cli, e2e_model, make_nonce, mode) -> None:
    outputs = []
    for _ in range(ATTEMPTS):
        token = make_nonce("zebra")
        run = cli.run_model(
            "ask",
            *mode,
            "--no-context",
            "--no-stream",
            "-m",
            e2e_model,
            echo_prompt(token),
        )
        assert run.returncode == 0, run.text
        if token.lower() in run.stdout.lower():
            return
        outputs.append(run.tail(200))
    pytest.fail(
        f"ask never returned the nonce {e2e_model} was asked to repeat: {outputs}"
    )


def test_model_list_marks_exactly_the_installed_models(cli, ollama) -> None:
    """`model list` called catalog entries "available" though they were not installed."""
    run = cli("model", "list", "--json", timeout=300)

    assert run.returncode == 0, run.text
    rows = json.loads(run.stdout[run.stdout.index("[") :])
    marked = {row["model_id"] for row in rows if row["installed"]}
    tags = set(ollama_models() or [])
    assert marked == tags, (
        f"installed per CLI {sorted(marked)} vs Ollama {sorted(tags)}"
    )
    listed_but_absent = [row["model_id"] for row in rows if not row["installed"]]
    assert all(model not in tags for model in listed_but_absent)

    table = cli("model", "list", timeout=300)
    assert f"{len(tags)} installed" in table.stdout, table.text


# 2 ---------------------------------------------------------------------------
def test_telemetry_stats_reports_the_call_ask_recorded(
    cli, e2e_model, make_nonce
) -> None:
    db = cli.grandpa_home / "telemetry.db"
    assert not sqlite_rows(db, "telemetry")

    cli.run_model(
        "ask",
        "--no-context",
        "--no-stream",
        "-m",
        e2e_model,
        echo_prompt(make_nonce("t")),
    )

    rows = sqlite_rows(db, "telemetry")
    assert [r["model_id"] for r in rows] == [e2e_model], rows
    assert rows[0]["total_tokens"] > 0, rows[0]
    stats = cli("telemetry", "stats")
    assert stats.returncode == 0, stats.text
    assert re.search(r"Total Calls\s*│\s*1\b", stats.text), stats.text
    assert e2e_model in stats.text, stats.text


# 3 ---------------------------------------------------------------------------
def test_chat_answers_with_what_the_model_generated(cli, e2e_model, make_nonce) -> None:
    outputs = []
    for _ in range(ATTEMPTS):
        token = make_nonce("heron")
        run = cli.chat(e2e_model, echo_prompt(token))
        replies = chat_replies(run.text)
        assert run.returncode == 0, run.text
        if replies and token.lower() in replies[0].lower():
            return
        outputs.append(replies)
    pytest.fail(f"chat never replied with the nonce: {outputs}")


# 4 ---------------------------------------------------------------------------
def test_chat_create_a_note_writes_the_note_file(cli, e2e_model, make_nonce) -> None:
    title = f"e2e groceries {make_nonce('')}"

    run = cli.chat(e2e_model, f"create a note called {title}")

    assert title in _note_titles(cli.grandpa_home), (
        f"no note file for {title!r}; chat said: {chat_replies(run.text)}"
    )


# 5 ---------------------------------------------------------------------------
def test_chat_remembers_a_personal_fact_and_recalls_it(
    cli, e2e_model, make_nonce
) -> None:
    colour = make_nonce("teal")

    run = cli.chat(
        e2e_model, f"my favorite color is {colour}", "what is my favorite color"
    )

    stored = sqlite_rows(cli.grandpa_home / "personal_memory.db", "memories")
    assert [(r["key"], r["value"]) for r in stored] == [("favorite_color", colour)], (
        stored
    )
    replies = chat_replies(run.text)
    assert len(replies) == 2 and colour in replies[1], replies


# 6 ---------------------------------------------------------------------------
def test_chat_reminder_stores_exactly_the_schedule_it_announces(
    cli, e2e_model, make_nonce
) -> None:
    """PARTIAL: chat reminders are daily-only. The reply must say so and match the store."""
    who = make_nonce("mom")

    run = cli.chat(e2e_model, f"remind me to call {who} at 5pm")

    reply = chat_replies(run.text)[0]
    rows = sqlite_rows(cli.grandpa_home / "scheduler.db", "reminders")
    assert [r["text"] for r in rows] == [f"call {who}"], (
        f"rows {rows}; chat said {reply!r}"
    )
    announced = re.search(r"\(daily at (\d{2}):(\d{2})\)", reply)
    assert announced, f"reply does not state the recurrence: {reply!r}"
    assert rows[0]["schedule"] == f"daily:{announced.group(1)}:{announced.group(2)}", (
        rows[0],
        reply,
    )
    assert rows[0]["enabled"] == 1


# 7 ---------------------------------------------------------------------------
def test_chat_delete_file_is_blocked_and_the_file_survives(
    cli, e2e_model, make_nonce
) -> None:
    """PARTIAL (safe): deleting via chat is blocked; nothing may be removed."""
    target = cli.home / "Desktop" / f"{make_nonce('keep-')}.txt"
    target.write_text("keep me", encoding="utf-8")

    run = cli.chat(e2e_model, f"delete {target.name} from my desktop")

    reply = chat_replies(run.text)[0]
    assert target.read_text(encoding="utf-8") == "keep me", (
        f"file gone; chat said {reply!r}"
    )
    assert "blocked" in reply.lower(), reply
    assert "deleted" not in reply.lower(), reply


# 8 ---------------------------------------------------------------------------
def test_agents_ask_runs_the_agent_and_records_its_answer(
    cli, e2e_model, make_nonce
) -> None:
    cli.use_default_model(e2e_model)
    name = make_nonce("e2e-agent-")
    created = cli("agents", "create", "--name", name, "--type", "simple")
    agent_id = re.search(r"Created agent: (\w+)", created.text)
    assert created.returncode == 0 and agent_id, created.text
    db = cli.grandpa_home / "agents.db"
    assert [r["name"] for r in sqlite_rows(db, "managed_agents")] == [name]

    outputs = []
    for _ in range(ATTEMPTS):
        token = make_nonce("walrus")
        run = cli.run_model("agents", "ask", agent_id.group(1), echo_prompt(token))
        assert run.returncode == 0, run.text
        (agent,) = sqlite_rows(db, "managed_agents")
        if token.lower() in run.stdout.lower():
            assert token.lower() in agent["summary_memory"].lower(), (
                f"answer printed but not recorded on the agent: {agent}"
            )
            return
        outputs.append(run.tail(200))
    pytest.fail(f"agents ask never returned the nonce: {outputs}")
