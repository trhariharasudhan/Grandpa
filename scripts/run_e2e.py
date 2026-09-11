"""Run the end-to-end CLI suite in ``tests/e2e``.

The suite runs the real ``grandpa`` CLI as subprocesses in throwaway sandboxes
and asserts on real effects: files, database rows, exit codes and model output.
It is excluded from the default ``pytest`` run because it is slow and its
model-backed tests need a local Ollama with at least one chat model.

Exit codes:
  0  every test passed (or was skipped for a stated platform reason)
  1  a test failed
  2  some tests could not run (no Ollama, no usable model, no network, ...)
     and nothing failed; this is not a pass
  other  pytest's own codes (usage error, no tests collected, ...)

Usage:
  python scripts/run_e2e.py [--model NAME] [--keep-sandbox] [-- PYTEST_ARGS...]

Equivalent without the script:
  python -m pytest tests/e2e -m e2e -rsxX
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--model",
        help="Ollama model for model-backed tests (default: smallest that passes preflight).",
    )
    parser.add_argument(
        "--keep-sandbox",
        action="store_true",
        help="Keep each test's temporary sandbox for inspection.",
    )
    args, pytest_args = parser.parse_known_args()
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]

    env = dict(os.environ)
    if args.model:
        env["GRANDPA_E2E_MODEL"] = args.model
    if args.keep_sandbox:
        env["GRANDPA_E2E_KEEP"] = "1"
    # Node ids or paths narrow the run; otherwise run the whole suite.
    targets = [] if any(not a.startswith("-") for a in pytest_args) else ["tests/e2e"]
    command = [
        sys.executable,
        "-m",
        "pytest",
        *targets,
        "-m",
        "e2e",
        "-rsxX",
        "-p",
        "no:cacheprovider",
        *pytest_args,
    ]
    print("+", " ".join(command), flush=True)
    code = subprocess.run(command, cwd=REPO_ROOT, env=env).returncode
    if code == 2:
        print(
            "\nRESULT: COULD NOT RUN - some tests produced no evidence (see the "
            "COULD NOT RUN section above). This is not a pass."
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
