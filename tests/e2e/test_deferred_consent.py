"""Closing a window: chat asks inline, voice stages and waits for its own yes.

Window actions are recorded, never performed, so nothing here closes a real
window. The voice tests drive the voice processor a turn per process -- no CLI
command takes typed text into it -- which also proves a staged action survives
between turns in the sandbox's real approval store, not an in-memory one.
"""

from __future__ import annotations

import json
import secrets

import pytest

from tests.e2e.harness import (
    run_cli,
    run_cli_recording_launches,
    run_script_recording_launches,
    sqlite_execute,
    sqlite_rows,
)

# ...and out of the default-deny actuation fixture (tests/actuation_guard.py).
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.real_actions(
        reason="runs the real CLI as a subprocess in a throwaway sandbox, which is what this suite is for; the sandbox has its own HOME and the harness records launches and window actions instead of performing them"
    ),
]

CLOSE_NOTEPAD = {"kind": "window", "value": "close|notepad"}


def _chat(cli, model, *lines):
    return run_cli_recording_launches(
        cli.sandbox,
        ["chat", "--no-fullscreen", "-m", model],
        cwd=cli.sandbox.root,
        stdin_text="\n".join([*lines, "exit"]) + "\n",
        timeout=420,
    )


# Chat's "close notepad" is claimed by its automation route, which pins the
# window and asks "Close ...? Yes / No"; the answer is the next line.
CHAT_CLOSE_PROMPT = "Unsaved work may be lost"


def test_chat_close_notepad_declined_closes_nothing(cli, e2e_model) -> None:
    run, attempts = _chat(cli, e2e_model, "close notepad", "no")

    assert CHAT_CLOSE_PROMPT in run.text, run.tail(400)
    assert attempts == [], f"a window was acted on after answering no: {attempts}"


def test_chat_close_notepad_accepted_closes_it(cli, e2e_model) -> None:
    run, attempts = _chat(cli, e2e_model, "close notepad", "yes")

    assert CHAT_CLOSE_PROMPT in run.text, run.tail(400)
    assert attempts == [CLOSE_NOTEPAD], run.tail(400)


# --- voice -------------------------------------------------------------------

_VOICE_TURN = r"""
from grandpa.voice.assistant import VoiceAssistantResponse, VoiceCommandProcessor

# The model is not what is under test; a turn that reaches it says so.
VoiceCommandProcessor._generate_response = (
    lambda self, text, **kwargs: VoiceAssistantResponse(
        "LLM fallback", status="handled", kind="chat"
    )
)
reply = VoiceCommandProcessor().handle_user_input(TURN)
print("TURN-RESULT " + json.dumps({"status": reply.status, "text": reply.text}))
"""

_LOCAL_TURN = r"""
from grandpa.local import handle_local_action

reply = handle_local_action(TURN, deferred_origin=ORIGIN)
print("TURN-RESULT " + json.dumps({
    "status": reply.status,
    "text": reply.message,
    "pending": reply.pending_action,
}))
"""


class _Voice:
    """Turns sent to one sandbox, sharing one record of what was acted on."""

    def __init__(self, sandbox) -> None:
        self.sandbox = sandbox
        self.log = sandbox.root / f"launches-{secrets.token_hex(4)}.jsonl"

    def _run(self, script: str) -> tuple[dict, list[dict]]:
        run, attempts = run_script_recording_launches(
            self.sandbox, script, cwd=self.sandbox.root, log=self.log, timeout=180
        )
        lines = [
            line for line in run.stdout.splitlines() if line.startswith("TURN-RESULT ")
        ]
        assert run.returncode == 0 and lines, run.tail(600)
        return json.loads(lines[-1].removeprefix("TURN-RESULT ")), attempts

    def say(self, text: str) -> tuple[dict, list[dict]]:
        return self._run(f"TURN = {text!r}\n" + _VOICE_TURN)

    def local(self, text: str, origin: str) -> tuple[dict, list[dict]]:
        return self._run(f"TURN = {text!r}\nORIGIN = {origin!r}\n" + _LOCAL_TURN)

    @property
    def store(self):
        return self.sandbox.grandpa_home / "pc_control_approvals.db"

    def deferred_rows(self) -> list[dict]:
        return [
            row
            for row in sqlite_rows(self.store, "pc_control_approvals")
            if row.get("consent") == "deferred"
        ]


def test_voice_stages_and_the_next_turn_yes_runs_it(sandbox) -> None:
    voice = _Voice(sandbox)

    staged, attempts = voice.say("close notepad")

    assert staged["status"] == "requires_confirmation", staged
    assert attempts == [], f"closed before the yes: {attempts}"
    assert [(r["origin"], r["status"]) for r in voice.deferred_rows()] == [
        ("voice", "pending")
    ]

    approved, attempts = voice.say("yes")

    assert approved["status"] == "handled", approved
    assert approved["text"] != "LLM fallback", approved
    assert attempts == [CLOSE_NOTEPAD]
    assert [r["status"] for r in voice.deferred_rows()] == ["approved"]


def test_a_voice_action_cannot_be_approved_from_another_origin(sandbox) -> None:
    voice = _Voice(sandbox)
    voice.say("close notepad")
    (row,) = voice.deferred_rows()

    # Chat's and the HTTP API's "yes".
    for origin in ("chat", "http"):
        reply, attempts = voice.local("yes", origin)
        assert reply["status"] == "unsupported", (origin, reply)
        assert attempts == [], (origin, attempts)

    # The CLI's approval command: it does not list the action, and refuses it
    # by id whatever code is given.
    listed = run_cli(sandbox, ["approve", "--list"], cwd=sandbox.root)
    assert row["action_id"] not in listed.text, listed.tail(400)
    refused = run_cli(
        sandbox, ["approve", row["action_id"], "--code", "000000"], cwd=sandbox.root
    )
    assert "cannot be approved with a code" in refused.text, refused.tail(400)

    assert [r["status"] for r in voice.deferred_rows()] == ["pending"]
    _, attempts = voice.say("hello")  # any turn; still nothing acted on
    assert attempts == []

    # ...and it is still voice's to approve.
    approved, attempts = voice.say("yes")
    assert approved["status"] == "handled", approved
    assert attempts == [CLOSE_NOTEPAD]


def test_a_staged_action_past_its_expiry_cannot_be_approved(sandbox) -> None:
    voice = _Voice(sandbox)
    voice.say("close notepad")
    (row,) = voice.deferred_rows()

    # Wind the clock rather than wait out PENDING_TTL_SECONDS: move the one
    # expiry the store keeps into the past.
    sqlite_execute(
        voice.store,
        "UPDATE pc_control_approvals SET expires_at = created_at - 1 "
        "WHERE action_id = ?",
        (row["action_id"],),
    )

    reply, attempts = voice.say("yes")

    assert reply["status"] != "handled", reply
    assert attempts == []
    assert [r["status"] for r in voice.deferred_rows()] == ["expired"]
