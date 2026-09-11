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
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
OLLAMA_URL = "http://localhost:11434"

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

CLI_TIMEOUT = 420
OLLAMA_START_TIMEOUT = 60

PASS, FAIL, SKIP, NORUN = "PASS", "FAIL", "SKIP", "COULD NOT RUN"


class CouldNotRun(Exception):
    """A prerequisite is missing; the probes cannot produce evidence."""


@dataclass
class Verdict:
    probe: str
    status: str
    reason: str


# --------------------------------------------------------------------------
# Prerequisites
# --------------------------------------------------------------------------


def _ollama_models(timeout: float = 3.0) -> list[str] | None:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return [m["name"] for m in data.get("models", []) if m.get("name")]


class OllamaServer:
    """Reuse a running Ollama, or start ``ollama serve`` and stop it afterwards."""

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.models: list[str] = []

    @property
    def started_here(self) -> bool:
        return self.process is not None

    def __enter__(self) -> OllamaServer:
        models = _ollama_models()
        if models is not None:
            self.models = models
            return self
        exe = shutil.which("ollama")
        if exe is None:
            raise CouldNotRun(
                f"Ollama is not reachable at {OLLAMA_URL} and the `ollama` "
                "executable is not on PATH."
            )
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        # Deliberately the real environment: Ollama locates its models via HOME.
        self.process = subprocess.Popen(
            [exe, "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        deadline = time.monotonic() + OLLAMA_START_TIMEOUT
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                code = self.process.returncode
                self.process = None
                raise CouldNotRun(
                    f"`ollama serve` exited with code {code} before it became reachable."
                )
            models = _ollama_models()
            if models is not None:
                self.models = models
                return self
            time.sleep(1)
        self.stop()
        raise CouldNotRun(
            f"`ollama serve` did not become reachable within {OLLAMA_START_TIMEOUT}s."
        )

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=15)


# --------------------------------------------------------------------------
# Sandbox and CLI invocation
# --------------------------------------------------------------------------


class Sandbox:
    def __init__(self, keep: bool) -> None:
        self.keep = keep
        self.root = Path(tempfile.mkdtemp(prefix="grandpa-confirm-probe-"))
        self.home = self.root / "home"
        self.home.mkdir()
        self._counter = 0

    def workdir(self, label: str) -> Path:
        self._counter += 1
        path = self.root / f"{self._counter:02d}-{label}"
        path.mkdir()
        return path

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        for key in list(env):
            if key.upper() in {"GRANDPA_CONFIG", "GRANDPA_HOME"}:
                del env[key]
        existing = env.get("PYTHONPATH")
        env.update(
            HOME=str(self.home),
            USERPROFILE=str(self.home),
            GRANDPA_HOME=str(self.home / ".grandpa"),
            PYTHONPATH=str(SRC_DIR) + (os.pathsep + existing if existing else ""),
            PYTHONIOENCODING="utf-8",
            NO_COLOR="1",
        )
        return env

    def cleanup(self) -> None:
        if not self.keep:
            shutil.rmtree(self.root, ignore_errors=True)


@dataclass
class CliRun:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def text(self) -> str:
        return self.stdout + "\n" + self.stderr

    def tail(self, limit: int = 240) -> str:
        return " ".join(self.text.split())[-limit:]


def run_python(
    sandbox: Sandbox,
    argv: list[str],
    *,
    cwd: Path,
    stdin_text: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> CliRun:
    env = sandbox.env()
    if extra_env:
        env.update(extra_env)
    kwargs: dict = (
        {"input": stdin_text}
        if stdin_text is not None
        else {"stdin": subprocess.DEVNULL}
    )
    try:
        proc = subprocess.run(
            [sys.executable, *argv],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLI_TIMEOUT,
            **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        err = exc.stderr if isinstance(exc.stderr, str) else ""
        return CliRun(None, out, err, timed_out=True)
    return CliRun(proc.returncode, proc.stdout, proc.stderr)


def run_cli(sandbox: Sandbox, args: list[str], **kwargs) -> CliRun:
    return run_python(sandbox, ["-m", "grandpa.cli", "--quiet", *args], **kwargs)


def verify_checkout(sandbox: Sandbox) -> Path:
    run = run_python(
        sandbox,
        ["-c", "import grandpa, sys; sys.stdout.write(grandpa.__file__)"],
        cwd=sandbox.root,
    )
    if run.returncode != 0:
        raise CouldNotRun(
            f"grandpa is not importable with {sys.executable}: {run.tail()}"
        )
    imported = Path(run.stdout.strip()).resolve()
    if SRC_DIR.resolve() not in imported.parents:
        raise CouldNotRun(
            f"The CLI subprocess imported grandpa from {imported}, not this checkout "
            f"({SRC_DIR}); probing it would test different code."
        )
    return imported


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


def candidate_models(available: list[str], requested: str | None) -> list[str]:
    if requested:
        if requested not in available:
            raise CouldNotRun(
                f"Requested model {requested!r} is not installed. Installed: {available}"
            )
        return [requested]
    usable = [m for m in available if "embed" not in m.lower()]
    if not usable:
        raise CouldNotRun(
            f"No chat model is installed in Ollama (found only: {available})."
        )

    def rank(name: str) -> tuple[int, str]:
        for index, prefix in enumerate(PREFERRED_MODELS):
            if name.lower().startswith(prefix):
                return index, name
        return len(PREFERRED_MODELS), name

    return sorted(usable, key=rank)


def select_model(
    sandbox: Sandbox, available: list[str], requested: str | None, log
) -> str:
    """Pick a model that demonstrably issues shell_exec calls through ``ask``."""
    for model in candidate_models(available, requested)[:4]:
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
    name = "P5b chat synthetic input reaches desktop_automation with a confirm callback"
    work = sandbox.workdir("p5b")
    # The only local_actions synthetic-input phrase that chat does not hand to
    # Screen Automation V2 first. 'n' declines, so no keystroke is sent.
    run = run_cli(
        sandbox,
        ["chat", "--no-fullscreen", "-m", model],
        cwd=work,
        stdin_text="copy selected text\nyes\nn\nexit\n",
    )
    if run.timed_out or "Goodbye" not in run.text:
        return Verdict(name, NORUN, f"chat did not complete the session: {run.tail()}")
    if CHAT_LOCAL_PENDING not in run.text:
        return Verdict(
            name,
            NORUN,
            f"'copy selected text' did not reach local_actions: {run.tail()}",
        )
    if CHAT_CALLBACK_PROMPT in run.text:
        if CHAT_COPY_DONE in run.text:
            return Verdict(
                name, FAIL, "callback prompted, but the copy ran after answering 'n'."
            )
        return Verdict(
            name,
            PASS,
            f"'copy selected text' -> 'yes' reached desktop_automation, which invoked chat's "
            f"callback ({CHAT_CALLBACK_PROMPT!r}); answered 'n', nothing copied.",
        )
    if CHAT_COPY_DONE in run.text:
        return Verdict(name, FAIL, "copy executed with no confirm-callback prompt.")
    if "There is no pending local action" in run.text:
        return Verdict(name, NORUN, "the approval turn found no pending action.")
    return Verdict(
        name,
        FAIL,
        f"approval reached desktop_automation without invoking a confirm callback: {run.tail()}",
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
    sandbox = Sandbox(keep=args.keep_sandbox)
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
