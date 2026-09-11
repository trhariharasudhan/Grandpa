"""Shared machinery for running the real Grandpa CLI end to end.

Used by the ``tests/e2e`` suite and by ``scripts/verify_confirmation_enforcement.py``.
It deliberately does not import pytest, so scripts can use it directly.

Every CLI invocation is a subprocess against this checkout's ``src/``, inside a
throwaway sandbox with its own ``GRANDPA_HOME``/``HOME``/``USERPROFILE`` and
working directory, so nothing touches the repo root or the real ``~/.grandpa``.

"Could not run" is kept distinct from pass: a missing prerequisite raises
:class:`CouldNotRun`, and callers must never report that as success.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
OLLAMA_URL = "http://localhost:11434"

CLI_TIMEOUT = 420
OLLAMA_START_TIMEOUT = 60


class CouldNotRun(Exception):
    """A prerequisite is missing, so no evidence either way was produced."""


# --------------------------------------------------------------------------
# Ollama
# --------------------------------------------------------------------------


def ollama_models(timeout: float = 3.0) -> list[str] | None:
    """Installed model names, or None when Ollama is unreachable."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return [m["name"] for m in data.get("models", []) if m.get("name")]


def ollama_generate(model: str, prompt: str, timeout: float = 300.0) -> str | None:
    """One non-streamed completion straight from the Ollama API, bypassing Grandpa."""
    body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return str(json.load(resp).get("response", ""))
    except (urllib.error.URLError, OSError, ValueError):
        return None


class OllamaServer:
    """Reuse a running Ollama, or start ``ollama serve`` and stop it afterwards."""

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.models: list[str] = []

    @property
    def started_here(self) -> bool:
        return self.process is not None

    def __enter__(self) -> OllamaServer:
        models = ollama_models()
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
            models = ollama_models()
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


def candidate_models(
    available: list[str], requested: str | None, preferred: Iterable[str]
) -> list[str]:
    """Chat models to try, the requested one only, or all ranked by ``preferred`` prefix."""
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
    prefixes = tuple(preferred)

    def rank(name: str) -> tuple[int, str]:
        for index, prefix in enumerate(prefixes):
            if name.lower().startswith(prefix):
                return index, name
        return len(prefixes), name

    return sorted(usable, key=rank)


# --------------------------------------------------------------------------
# Sandbox and CLI invocation
# --------------------------------------------------------------------------


class Sandbox:
    def __init__(self, keep: bool = False, prefix: str = "grandpa-e2e-") -> None:
        self.keep = keep
        self.root = Path(tempfile.mkdtemp(prefix=prefix))
        self.home = self.root / "home"
        self.home.mkdir()
        self._counter = 0

    @property
    def grandpa_home(self) -> Path:
        return self.home / ".grandpa"

    def workdir(self, label: str) -> Path:
        self._counter += 1
        path = self.root / f"{self._counter:02d}-{label}"
        path.mkdir()
        return path

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        for key in list(env):
            if key.upper() in {
                "GRANDPA_CONFIG",
                "GRANDPA_HOME",
                "GRANDPA_DOWNLOADS_DIR",
            }:
                del env[key]
        existing = env.get("PYTHONPATH")
        env.update(
            HOME=str(self.home),
            USERPROFILE=str(self.home),
            GRANDPA_HOME=str(self.grandpa_home),
            PYTHONPATH=str(SRC_DIR) + (os.pathsep + existing if existing else ""),
            PYTHONIOENCODING="utf-8",
            NO_COLOR="1",
            # Rich tables otherwise truncate cells to the default 80 columns.
            COLUMNS="200",
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
    timeout: float = CLI_TIMEOUT,
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
            timeout=timeout,
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
    """Prove the CLI subprocess imports this checkout's grandpa, not another install."""
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


def nonce(prefix: str) -> str:
    """A token no hardcoded output could contain."""
    return f"{prefix}{secrets.randbelow(900000) + 100000}"


def chat_replies(text: str) -> list[str]:
    """Grandpa's turns in a piped chat transcript, without the echoed user lines."""
    parts = re.split(r"Username >|Goodbye", text)
    return [
        " ".join(part.split("Grandpa >", 1)[1].split())
        for part in parts
        if "Grandpa >" in part
    ]


def sqlite_rows(db_path: Path, table: str) -> list[dict]:
    """Every row of ``table``, read directly rather than through Grandpa."""
    if not db_path.exists():
        return []
    con = sqlite3.connect(db_path)
    try:
        con.row_factory = sqlite3.Row
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            return []
        return [dict(row) for row in con.execute(f'SELECT * FROM "{table}"')]
    finally:
        con.close()


def sqlite_execute(db_path: Path, sql: str, params: tuple = ()) -> None:
    con = sqlite3.connect(db_path)
    try:
        con.execute(sql, params)
        con.commit()
    finally:
        con.close()
