"""`grandpa ask --tool-loop` doing something the keyword waterfall cannot.

The goal is one instruction with three dependent file steps. The old path
cannot do it at all: `file_create` is one of the capabilities the audit found
with no route to it (section 6, item 8), and nothing in the waterfall carries a
result from one step into the next.

Everything here is real except the model: the CLI runs as a subprocess, the
action layer resolves and calls the real file service, and the assertions are
on files that actually exist afterwards. The *model* is a scripted HTTP server
standing in for Ollama, because a local model is not a fixture -- it is the
thing being measured. Measured separately, the installed models disagree about
this very goal: some issue all three calls in one turn, some stop after the
first and narrate the rest, and one copied by creating a second file instead.
Pinning the suite to that would test the weather. What is pinned here is the
layer: given a model that asks for three actions, three actions happen, in
order, with the effects on disk to prove it.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from tests.e2e.harness import run_cli

pytestmark = pytest.mark.e2e

MODEL = "scripted-tool-model"


class _ScriptedOllama:
    """The subset of Ollama's HTTP API the action loop uses.

    ``/api/tags`` so the engine reports healthy, ``/api/show`` so the loop's
    capability check finds ``tools``, and ``/api/chat`` replaying one prepared
    turn per request.
    """

    def __init__(
        self, turns: list[dict], capabilities: tuple[str, ...] = ("completion", "tools")
    ) -> None:
        self.turns = list(turns)
        self.capabilities = list(capabilities)
        self.requests: list[dict] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):  # noqa: N802 - quiet the test output
                return

            def _send(self, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
                if self.path.startswith("/api/tags"):
                    self._send({"models": [{"name": MODEL}]})
                else:
                    self._send({"status": "ok"})

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if self.path.startswith("/api/show"):
                    self._send({"capabilities": server.capabilities})
                    return
                server.requests.append(payload)
                turn = (
                    server.turns.pop(0)
                    if server.turns
                    else {"content": "Nothing further."}
                )
                self._send({"model": MODEL, "message": turn, "done": True})

        self._httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> _ScriptedOllama:
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def _call(index: int, name: str, arguments: dict) -> dict:
    return {
        "id": f"call_{index}",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def test_one_instruction_creates_copies_and_renames_a_file(cli) -> None:
    work = cli.sandbox.workdir("tool-loop")
    note = work / "note.txt"
    backup = work / "backup.txt"
    archive = work / "archive.txt"

    turns = [
        {
            "content": "",
            "tool_calls": [
                _call(
                    0,
                    "file_create",
                    {"path": str(note), "content": "eggs, milk, bread"},
                )
            ],
        },
        {
            "content": "",
            "tool_calls": [
                _call(1, "file_copy", {"path": str(note), "destination": str(backup)})
            ],
        },
        {
            "content": "",
            "tool_calls": [
                _call(
                    2, "file_rename", {"path": str(backup), "new_name": "archive.txt"}
                )
            ],
        },
        {"content": "Created the note, copied it, and renamed the copy."},
    ]

    with _ScriptedOllama(turns) as ollama:
        run = run_cli(
            cli.sandbox,
            ["ask", "--tool-loop", "--model", MODEL, "--json", "make and file a note"],
            cwd=cli.sandbox.root,
            extra_env={"OLLAMA_HOST": ollama.url},
            timeout=120,
        )

    assert run.returncode == 0, run.text
    payload = json.loads(run.stdout)

    # The real effect, on disk, after the CLI process has exited.
    assert note.read_text(encoding="utf-8") == "eggs, milk, bread", run.text
    assert archive.read_text(encoding="utf-8") == "eggs, milk, bread", run.text
    assert not backup.exists(), "the copy was renamed, so the old name is gone"

    # And the trace says it did exactly that, in that order.
    assert [entry["action"] for entry in payload["trace"]] == [
        "file_create",
        "file_copy",
        "file_rename",
    ]
    assert all(entry["success"] for entry in payload["trace"]), payload["trace"]
    assert payload["steps"] == 4
    assert payload["stopped_at_limit"] is False
    assert payload["content"].startswith("Created the note")


def test_each_result_is_carried_back_to_the_model(cli) -> None:
    """Multi-step only means anything if step two can see step one's outcome."""
    work = cli.sandbox.workdir("tool-loop-feedback")
    note = work / "carried.txt"

    turns = [
        {
            "content": "",
            "tool_calls": [
                _call(0, "file_create", {"path": str(note), "content": "one"})
            ],
        },
        {"content": "The file exists now."},
    ]

    with _ScriptedOllama(turns) as ollama:
        run = run_cli(
            cli.sandbox,
            ["ask", "--tool-loop", "--model", MODEL, "--json", "create it"],
            cwd=cli.sandbox.root,
            extra_env={"OLLAMA_HOST": ollama.url},
            timeout=120,
        )
        second_request = ollama.requests[1]

    assert run.returncode == 0, run.text
    tool_messages = [
        message
        for message in second_request["messages"]
        if message.get("role") == "tool"
    ]
    assert tool_messages, second_request["messages"]
    assert json.loads(tool_messages[0]["content"])["success"] is True


def test_a_confirmable_action_is_refused_when_nobody_can_be_asked(cli) -> None:
    """The loop runs with no terminal here, so keyboard input must not happen."""
    turns = [
        {
            "content": "",
            "tool_calls": [_call(0, "keyboard_type", {"text": "hello"})],
        },
        {"content": "I could not type without confirmation."},
    ]

    with _ScriptedOllama(turns) as ollama:
        run = run_cli(
            cli.sandbox,
            ["ask", "--tool-loop", "--model", MODEL, "--json", "type hello"],
            cwd=cli.sandbox.root,
            extra_env={"OLLAMA_HOST": ollama.url},
            timeout=120,
        )

    payload = json.loads(run.stdout)
    assert payload["trace"][0]["error"] == "confirmation_required", run.text
    assert payload["trace"][0]["success"] is False


def test_a_model_that_cannot_call_tools_is_named_and_refused(cli) -> None:
    """No silent fallback to chatting about the desktop instead of touching it.

    ollama_adapter.py drops the tools and retries when the server rejects
    them, which would turn a desktop command into a conversation about one.
    """
    turns = [{"content": "Sure, I turned the volume up!"}]

    with _ScriptedOllama(turns, capabilities=("completion",)) as ollama:
        run = run_cli(
            cli.sandbox,
            ["ask", "--tool-loop", "--model", MODEL, "turn the volume up"],
            cwd=cli.sandbox.root,
            extra_env={"OLLAMA_HOST": ollama.url},
            timeout=120,
        )
        asked = list(ollama.requests)

    assert run.returncode == 1, run.text
    assert MODEL in run.text and "cannot call tools" in run.text, run.text
    assert asked == [], "it asked the model anyway and would have believed the reply"


def test_the_action_is_written_to_the_shared_audit_log(cli) -> None:
    """The layer appends to the same JSONL log pc_control reads."""
    work = cli.sandbox.workdir("tool-loop-audit")
    note = work / "audited.txt"
    log = cli.sandbox.root / "audit" / "local_actions.jsonl"

    turns = [
        {
            "content": "",
            "tool_calls": [
                _call(0, "file_create", {"path": str(note), "content": "x"})
            ],
        },
        {"content": "Done."},
    ]

    with _ScriptedOllama(turns) as ollama:
        run = run_cli(
            cli.sandbox,
            ["ask", "--tool-loop", "--model", MODEL, "--json", "create it"],
            cwd=cli.sandbox.root,
            extra_env={
                "OLLAMA_HOST": ollama.url,
                "GRANDPA_LOCAL_ACTION_LOG": str(log),
            },
            timeout=120,
        )

    assert run.returncode == 0, run.text
    records = [
        json.loads(line)
        for line in Path(log).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records, "nothing was audited"
    assert records[0]["action_type"] == "file_create"
    assert records[0]["origin"] == "user_cli"
    assert records[0]["source"] == "action_layer"
    assert records[0]["ok"] is True
