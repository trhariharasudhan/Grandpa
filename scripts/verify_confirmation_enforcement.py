"""End-to-end probe: tool and synthetic-input confirmation in the real Grandpa CLI.

Every probe launches the CLI as a subprocess against this checkout's ``src/``
inside a throwaway sandbox (its own ``GRANDPA_HOME``/``HOME``/``USERPROFILE``
and working directory), so nothing touches the repo root or your real
``~/.grandpa``.

Verdicts per probe:
  PASS           the confirmation behaviour was observed, with positive evidence
  FAIL           the gate let an action through, or refused one it should allow
  SKIP           the probe cannot exist on this platform (stated reason)
  COULD NOT RUN  no conclusive evidence either way (engine down, model never
                 issued the tool call, CLI crashed, ...). Never counted as a pass.

A missing marker file alone is never a PASS: the engine could be down or the
model could simply not call the tool. Refusal probes require evidence that the
tool call was issued and refused.

Exit codes: 0 = every probe PASS or SKIP, 1 = any FAIL, 2 = could not run.

Usage: python scripts/verify_confirmation_enforcement.py [--model NAME]

The sandbox, Ollama and CLI machinery is shared with the e2e suite in
``tests/e2e/harness.py``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.e2e.harness import (  # noqa: E402
    CLI_TIMEOUT,
    OLLAMA_URL,
    CouldNotRun,
    OllamaServer,
    Sandbox,
    candidate_models,
    run_cli,
    run_python,
    verify_checkout,
)

MARKER = "probemarker"
TOOL_PROMPT = f"Call the shell_exec tool exactly once with the command: mkdir {MARKER}"
ASK_BASE = ["ask", "--no-context", "--json", "--agent", "orchestrator"]

# Strings emitted by the code under test.
REFUSAL = "requires confirmation but no confirmation callback is available"
DENIED = "execution denied by user"
YES_WARNING = "--yes: auto-approving tool execution without prompting"
CHAT_LOCAL_PENDING = "Reply with yes/confirm to approve"
CHAT_CALLBACK_PROMPT = "Confirm desktop action:"
CHAT_COPY_DONE = "Copied the selected text"
NO_INPUT_SENT = "No input was sent"

# ToolExecutor rejections that happen before the confirmation gate: the gate
# was never exercised, so the attempt is inconclusive rather than PASS/FAIL.
PRE_GATE_REJECTIONS = (
    "Unknown tool:",
    "Invalid arguments JSON:",
    "Security block:",
    "Capability '",
    "Taint violation:",
)

# Measured on the development machine: grandpa-brain issued a well-formed
# shell_exec call 3/3; grandpa-mini 1/3 (malformed); gemma3:4b and
# grandpa-coder 0/3. Any other installed model is still tried afterwards.
PREFERRED_MODELS = ("grandpa-brain", "grandpa-mini", "qwen2.5", "qwen3", "llama3")

PASS, FAIL, SKIP, NORUN = "PASS", "FAIL", "SKIP", "COULD NOT RUN"


@dataclass
class Verdict:
    probe: str
    status: str
    reason: str


# --------------------------------------------------------------------------
# Evidence helpers
# --------------------------------------------------------------------------


def shell_results_from_ask_json(stdout: str) -> list[dict] | None:
    """``shell_exec`` tool results from ``ask --json`` output, or None if unparseable."""
    start, end = stdout.find("{"), stdout.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(stdout[start : end + 1])
    except ValueError:
        return None
    return [
        r for r in payload.get("tool_results", []) if r.get("tool_name") == "shell_exec"
    ]


def classify_results(results: list[dict]) -> str:
    """'refused', 'denied', 'executed', 'pre_gate' or 'none'."""
    if not results:
        return "none"
    contents = [str(r.get("content", "")) for r in results]
    if any(
        REFUSAL not in c and DENIED not in c and not c.startswith(PRE_GATE_REJECTIONS)
        for c in contents
    ):
        return "executed"
    if any(REFUSAL in c for c in contents):
        return "refused"
    if any(DENIED in c for c in contents):
        return "denied"
    return "pre_gate"


def first_content(results: list[dict]) -> str:
    return " ".join(str(results[0].get("content", "")).split())[:120] if results else ""


# --------------------------------------------------------------------------
# Model selection
# --------------------------------------------------------------------------


def select_model(
    sandbox: Sandbox, available: list[str], requested: str | None, log
) -> str:
    """Pick a model that demonstrably issues shell_exec calls through ``ask``."""
    for model in candidate_models(available, requested, PREFERRED_MODELS)[:4]:
        for attempt in (1, 2):
            work = sandbox.workdir("preflight")
            run = run_cli(
                sandbox,
                [*ASK_BASE, "-m", model, "--tools", "shell_exec", TOOL_PROMPT],
                cwd=work,
            )
            results = shell_results_from_ask_json(run.stdout)
            if results:
                log(
                    f"  preflight: {model} issued a shell_exec call (attempt {attempt})."
                )
                return model
            why = (
                "timed out"
                if run.timed_out
                else ("no JSON output" if results is None else "no tool call")
            )
            log(f"  preflight: {model} attempt {attempt}: {why}.")
    raise CouldNotRun(
        "No installed model issued a shell_exec tool call during preflight, so the "
        "confirmation gate cannot be exercised. Re-run with --model NAME."
    )


# --------------------------------------------------------------------------
# Probes
# --------------------------------------------------------------------------


def probe_p1(sandbox: Sandbox, model: str, attempts: int) -> Verdict:
    name = "P1 ask --tools shell_exec, non-tty, no --yes"
    notes = []
    for attempt in range(1, attempts + 1):
        work = sandbox.workdir("p1")
        run = run_cli(
            sandbox,
            [*ASK_BASE, "-m", model, "--tools", "shell_exec", TOOL_PROMPT],
            cwd=work,
        )
        if (work / MARKER).exists():
            return Verdict(
                name, FAIL, f"marker created without confirmation (attempt {attempt})."
            )
        results = shell_results_from_ask_json(run.stdout)
        if results is None:
            notes.append(
                f"attempt {attempt}: no JSON (exit {run.returncode}): {run.tail(120)}"
            )
            continue
        kind = classify_results(results)
        if kind == "executed":
            return Verdict(
                name,
                FAIL,
                f"shell_exec reached execution without confirmation: {first_content(results)!r}",
            )
        if kind == "refused":
            return Verdict(
                name,
                PASS,
                f"marker absent; tool result: {first_content(results)!r} (attempt {attempt}).",
            )
        notes.append(
            f"attempt {attempt}: {'model made no shell_exec call' if kind == 'none' else 'rejected before the gate: ' + first_content(results)}"
        )
    return Verdict(name, NORUN, "; ".join(notes))


def probe_p2(sandbox: Sandbox, model: str, attempts: int) -> Verdict:
    name = "P2 ask --yes --tools shell_exec, non-tty"
    notes = []
    for attempt in range(1, attempts + 1):
        work = sandbox.workdir("p2")
        run = run_cli(
            sandbox,
            [*ASK_BASE, "--yes", "-m", model, "--tools", "shell_exec", TOOL_PROMPT],
            cwd=work,
        )
        warned = YES_WARNING in run.stderr
        results = shell_results_from_ask_json(run.stdout) or []
        if (work / MARKER).exists():
            if warned:
                return Verdict(
                    name,
                    PASS,
                    f"marker created and stderr warned {YES_WARNING!r} (attempt {attempt}).",
                )
            return Verdict(
                name,
                FAIL,
                "marker created but the --yes warning did not appear on stderr.",
            )
        kind = classify_results(results)
        if kind in {"refused", "denied"}:
            return Verdict(
                name,
                FAIL,
                f"--yes was passed but the tool was refused: {first_content(results)!r}",
            )
        if kind == "executed":
            notes.append(
                f"attempt {attempt}: executed but model sent a malformed command: {first_content(results)!r}"
            )
        else:
            notes.append(
                f"attempt {attempt}: no conclusive tool call (exit {run.returncode}): {run.tail(120)}"
            )
    return Verdict(name, NORUN, "; ".join(notes))


def probe_p3(sandbox: Sandbox, model: str, attempts: int) -> Verdict:
    name = "P3 ask --tools shell_exec on a tty, answer 'n'"
    if os.name == "nt" or importlib.util.find_spec("termios") is None:
        return Verdict(
            name,
            SKIP,
            "no pseudo-terminal on this platform: Python's pty module requires termios "
            "(POSIX only), and pywinpty/pexpect are not installed. Not simulated.",
        )
    import pty
    import select

    notes = []
    for attempt in range(1, attempts + 1):
        work = sandbox.workdir("p3")
        argv = [
            sys.executable,
            "-m",
            "grandpa.cli",
            "--quiet",
            *ASK_BASE,
            "-m",
            model,
            "--tools",
            "shell_exec",
            TOOL_PROMPT,
        ]
        env = sandbox.env()
        pid, fd = pty.fork()
        if pid == 0:  # child
            os.chdir(work)
            os.execve(sys.executable, argv, env)
        output, answered = b"", False
        deadline = time.monotonic() + CLI_TIMEOUT
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 1.0)
            if fd not in ready:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            output += chunk
            if not answered and b"[y/N]" in output:
                os.write(fd, b"n\n")
                answered = True
        else:
            os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        text = output.decode("utf-8", "replace")
        if (work / MARKER).exists():
            return Verdict(
                name, FAIL, f"marker created after answering 'n' (attempt {attempt})."
            )
        if answered:
            return Verdict(
                name,
                PASS,
                f"prompted on the tty, answered 'n', marker absent (attempt {attempt}).",
            )
        notes.append(
            f"attempt {attempt}: no [y/N] prompt: {' '.join(text.split())[-120:]}"
        )
    return Verdict(name, NORUN, "; ".join(notes))


_RECORDING_RUNNER = """
import json, os, runpy, sys
from grandpa.tools import _stubs
_original = _stubs.ToolExecutor.execute
def _recording_execute(self, tool_call):
    result = _original(self, tool_call)
    with open(os.environ["GRANDPA_PROBE_TOOL_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"tool_name": tool_call.name, "success": bool(result.success), "content": str(result.content)[:300]}) + "\\n")
    return result
_stubs.ToolExecutor.execute = _recording_execute
sys.argv = ["grandpa", "--verbose", *sys.argv[1:]]
runpy.run_module("grandpa.cli", run_name="__main__")
"""

_AGENT_FIXTURE = """
import sys
from grandpa.agents.manager import AgentManager
from grandpa.core.config import load_config
config = load_config()
manager = AgentManager(db_path=config.agent_manager.db_path)
agent = manager.create_agent(
    name="confirmation-probe",
    agent_type="orchestrator",
    config={"tools": ["shell_exec"], "model": sys.argv[1]},
)
sys.stdout.write(agent["id"])
"""


def probe_p4(sandbox: Sandbox, model: str, attempts: int) -> Verdict:
    name = "P4 agents ask, no flags, confirmation-gated tool"
    setup = run_python(sandbox, ["-c", _AGENT_FIXTURE, model], cwd=sandbox.root)
    agent_id = setup.stdout.strip()
    if setup.returncode != 0 or not agent_id:
        return Verdict(
            name, NORUN, f"could not create the fixture agent: {setup.tail()}"
        )
    notes = []
    for attempt in range(1, attempts + 1):
        work = sandbox.workdir("p4")
        log = work.parent / f"{work.name}-tools.jsonl"
        run = run_python(
            sandbox,
            ["-c", _RECORDING_RUNNER, "agents", "ask", agent_id, TOOL_PROMPT],
            cwd=work,
            extra_env={"GRANDPA_PROBE_TOOL_LOG": str(log)},
        )
        if (work / MARKER).exists():
            return Verdict(
                name,
                FAIL,
                f"marker created: agents ask auto-approved the tool (attempt {attempt}).",
            )
        results = []
        if log.exists():
            for line in log.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if record.get("tool_name") == "shell_exec":
                    results.append(record)
        kind = classify_results(results)
        if kind == "executed":
            return Verdict(
                name,
                FAIL,
                f"shell_exec reached execution without confirmation: {first_content(results)!r}",
            )
        if kind == "refused":
            return Verdict(
                name,
                PASS,
                f"marker absent; recorded tool result: {first_content(results)!r} (attempt {attempt}).",
            )
        tick_errors = [
            line for line in run.stderr.splitlines() if "Tick failed" in line
        ]
        if tick_errors:
            # Deterministic: the agent never ran, so retrying cannot help.
            detail = " ".join(tick_errors[-1].split())[-220:]
            return Verdict(
                name,
                NORUN,
                f"agents ask ran no agent, so the gate was never reached "
                f"(CLI exit {run.returncode}): {detail}",
            )
        if run.returncode not in (0, None) or "Executor not available" in run.text:
            notes.append(
                f"attempt {attempt}: agents ask failed (exit {run.returncode}): {run.tail(120)}"
            )
        else:
            notes.append(f"attempt {attempt}: agent ran but issued no shell_exec call")
    return Verdict(name, NORUN, "; ".join(notes))


def probe_p5a(sandbox: Sandbox, model: str) -> Verdict:
    name = "P5a chat 'type hello' sends no input without confirmation"
    work = sandbox.workdir("p5a")
    run = run_cli(
        sandbox,
        ["chat", "--no-fullscreen", "-m", model],
        cwd=work,
        stdin_text="type hello\nexit\n",
    )
    if run.timed_out or "Goodbye" not in run.text:
        return Verdict(name, NORUN, f"chat did not complete the session: {run.tail()}")
    if NO_INPUT_SENT in run.text:
        return Verdict(
            name,
            PASS,
            f"refused by Screen Automation V2 ({NO_INPUT_SENT!r}); "
            "this phrase never reaches desktop_automation.",
        )
    if CHAT_LOCAL_PENDING in run.text:
        return Verdict(
            name, PASS, "local_actions held it for confirmation; no input was sent."
        )
    if "Typed" in run.text:
        return Verdict(
            name, FAIL, f"chat reports typing without confirmation: {run.tail()}"
        )
    return Verdict(name, NORUN, f"unrecognised chat response: {run.tail()}")


def probe_p5b(sandbox: Sandbox, model: str) -> Verdict:
    name = "P5b chat synthetic input is asked for once, at the moment it runs"
    work = sandbox.workdir("p5b")
    # The only local_actions synthetic-input phrase that chat does not hand to
    # Screen Automation V2 first.
    #
    # This probe used to type "copy selected text", then "yes", and require a
    # SECOND prompt as the copy ran: local_actions held the action for a
    # turn-based yes, and desktop_automation asked again underneath it.
    # Synthetic input is no longer staged for a later yes -- a keystroke goes
    # wherever focus is at the instant it is sent -- so there is one prompt, at
    # the point of action, and "n" at that prompt sends nothing.
    run = run_cli(
        sandbox,
        ["chat", "--no-fullscreen", "-m", model],
        cwd=work,
        stdin_text="copy selected text\nn\nexit\n",
    )
    if run.timed_out or "Goodbye" not in run.text:
        return Verdict(name, NORUN, f"chat did not complete the session: {run.tail()}")
    if CHAT_LOCAL_PENDING in run.text:
        return Verdict(
            name,
            FAIL,
            "synthetic input was staged for a later yes instead of being asked "
            "for as it ran.",
        )
    if CHAT_CALLBACK_PROMPT not in run.text:
        if CHAT_COPY_DONE in run.text:
            return Verdict(name, FAIL, "copy executed with no confirm-callback prompt.")
        return Verdict(
            name,
            NORUN,
            f"'copy selected text' did not reach desktop_automation: {run.tail()}",
        )
    if CHAT_COPY_DONE in run.text:
        return Verdict(
            name, FAIL, "callback prompted, but the copy ran after answering 'n'."
        )
    return Verdict(
        name,
        PASS,
        f"'copy selected text' invoked chat's callback once "
        f"({CHAT_CALLBACK_PROMPT!r}); answered 'n', nothing copied.",
    )


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--model", help="Ollama model to use (default: auto-select via preflight)."
    )
    parser.add_argument(
        "--attempts", type=int, default=3, help="Attempts per model-dependent probe."
    )
    parser.add_argument(
        "--keep-sandbox",
        action="store_true",
        help="Keep the temporary sandbox for inspection.",
    )
    args = parser.parse_args()

    def log(message: str) -> None:
        print(message, flush=True)

    log("Grandpa confirmation-enforcement probe")
    log(f"  checkout:   {REPO_ROOT}")
    log(f"  python:     {sys.executable}")
    verdicts: list[Verdict] = []
    sandbox = Sandbox(keep=args.keep_sandbox, prefix="grandpa-confirm-probe-")
    try:
        with OllamaServer() as ollama:
            log(
                f"  ollama:     {'started by this script' if ollama.started_here else 'already running'} at {OLLAMA_URL}"
            )
            imported = verify_checkout(sandbox)
            log(f"  grandpa:    {imported}")
            log(f"  sandbox:    {sandbox.root}")
            model = select_model(sandbox, ollama.models, args.model, log)
            log(f"  model:      {model}")
            log("")
            for probe in (probe_p1, probe_p2, probe_p3, probe_p4):
                verdict = probe(sandbox, model, args.attempts)
                verdicts.append(verdict)
                log(f"[{verdict.status}] {verdict.probe}: {verdict.reason}")
            for probe in (probe_p5a, probe_p5b):
                verdict = probe(sandbox, model)
                verdicts.append(verdict)
                log(f"[{verdict.status}] {verdict.probe}: {verdict.reason}")
    except CouldNotRun as exc:
        log(f"\nCOULD NOT RUN: {exc}")
        log("No probe result was produced; this is not a pass.")
        return 2
    finally:
        sandbox.cleanup()
        log(
            f"  sandbox {'kept at ' + str(sandbox.root) if args.keep_sandbox else 'removed'}"
        )

    counts = {
        status: sum(v.status == status for v in verdicts)
        for status in (PASS, FAIL, SKIP, NORUN)
    }
    log("")
    log(
        "Summary: " + ", ".join(f"{count} {status}" for status, count in counts.items())
    )
    if counts[FAIL]:
        log("RESULT: FAIL")
        return 1
    if counts[NORUN]:
        log("RESULT: COULD NOT RUN (some probes produced no evidence; not a pass)")
        return 2
    log("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
