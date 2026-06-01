"""Daily-use validation runner for Grandpa.

This script exercises the real CLI and frontend build paths without deleting,
overwriting, or editing user files. It may open a safe allowlisted app unless
``--skip-app-launch`` is passed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ValidationStep:
    name: str
    command: list[str]
    cwd: Path = ROOT
    timeout: int = 180
    required: bool = True
    expected_text: str | None = None


@dataclass
class ValidationResult:
    name: str
    status: str
    detail: str


def _run_step(step: ValidationStep) -> ValidationResult:
    try:
        completed = subprocess.run(
            step.command,
            cwd=step.cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
            timeout=step.timeout,
        )
    except FileNotFoundError as exc:
        status = "fail" if step.required else "warn"
        return ValidationResult(step.name, status, f"Command not found: {exc}")
    except subprocess.TimeoutExpired:
        status = "fail" if step.required else "warn"
        return ValidationResult(step.name, status, f"Timed out after {step.timeout}s")

    output = "\n".join(
        part.strip()
        for part in (completed.stdout or "", completed.stderr or "")
        if part.strip()
    )
    if completed.returncode != 0:
        status = "fail" if step.required else "warn"
        return ValidationResult(
            step.name,
            status,
            f"exit {completed.returncode}: {_tail(output)}",
        )
    if step.expected_text and step.expected_text.lower() not in output.lower():
        status = "fail" if step.required else "warn"
        return ValidationResult(
            step.name,
            status,
            f"expected {step.expected_text!r}; got: {_tail(output)}",
        )
    return ValidationResult(step.name, "ok", _tail(output) or "completed")


def _tail(text: str, *, max_chars: int = 500) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return "..." + text[-max_chars:]


def _console_safe(text: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _docker_daemon_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        completed = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return False
    return completed.returncode == 0


def _npm_command() -> list[str] | None:
    """Return a subprocess-safe npm command for the current platform."""
    if os.name == "nt":
        npm = shutil.which("npm.cmd") or shutil.which("npm.exe")
    else:
        npm = shutil.which("npm")
    if not npm:
        return None
    return [npm]


def build_steps(args: argparse.Namespace) -> list[ValidationStep]:
    steps = [
        ValidationStep("doctor dashboard", ["uv", "run", "grandpa", "doctor"], timeout=240),
        ValidationStep(
            "normal AI question",
            ["uv", "run", "grandpa", "ask", "What is Python?"],
            timeout=240,
        ),
        ValidationStep(
            "memory remember",
            ["uv", "run", "grandpa", "ask", "remember my project is Grandpa"],
            timeout=120,
            expected_text="will remember",
        ),
        ValidationStep(
            "memory recall",
            ["uv", "run", "grandpa", "ask", "what is my project?"],
            timeout=120,
            expected_text="Grandpa",
        ),
        ValidationStep(
            "file assistant",
            ["uv", "run", "grandpa", "ask", "show recent files"],
            timeout=120,
        ),
        ValidationStep(
            "capability foundations",
            ["uv", "run", "python", "-c", _CAPABILITY_DIAGNOSTICS],
            timeout=120,
            expected_text="capabilities ok",
        ),
        ValidationStep(
            "routine reminder",
            ["uv", "run", "grandpa", "ask", "remind me every hour to drink water"],
            timeout=120,
        ),
        ValidationStep(
            "blocked dangerous command",
            ["uv", "run", "grandpa", "ask", "delete all files"],
            timeout=120,
            expected_text="blocked this action for safety",
        ),
    ]

    if args.skip_app_launch:
        steps.append(
            ValidationStep(
                "safe app command parser",
                ["uv", "run", "python", "-c", _LOCAL_ACTION_DRY_RUN],
                timeout=120,
                expected_text="handled",
            )
        )
    else:
        steps.insert(
            2,
            ValidationStep(
                "open safe app command",
                ["uv", "run", "grandpa", "ask", "open notepad"],
                timeout=120,
            ),
        )

    if not args.skip_frontend:
        npm = _npm_command()
        frontend_dir = ROOT / "frontend"
        frontend_command = (
            [*npm, "run", "build"]
            if npm
            else ["npm", "run", "build"]
        )
        steps.append(
            ValidationStep(
                "frontend build",
                frontend_command,
                cwd=frontend_dir,
                timeout=240,
                required=(frontend_dir / "package.json").exists(),
            )
        )

    if not args.skip_docker:
        if _docker_daemon_ready():
            steps.append(
                ValidationStep(
                    "docker build",
                    [
                        "docker",
                        "build",
                        "-f",
                        "deploy/docker/Dockerfile",
                        "-t",
                        "grandpa:local",
                        ".",
                    ],
                    timeout=600,
                )
            )
        else:
            steps.append(
                ValidationStep(
                    "docker build",
                    ["docker", "version"],
                    timeout=30,
                    required=False,
                    expected_text="Server",
                )
            )

    return steps


_LOCAL_ACTION_DRY_RUN = (
    "from grandpa.local_actions import handle_local_action; "
    "result = handle_local_action('open notepad', execute=False); "
    "print(result.status)"
)

_CAPABILITY_DIAGNOSTICS = (
    "from grandpa import communication_integration, future_features, iot_smart_home, "
    "mobile_integration, real_world_tasks; "
    "checks=[mobile_integration.diagnostics()['status'], "
    "communication_integration.diagnostics()['status'], "
    "real_world_tasks.diagnostics()['status'], "
    "iot_smart_home.diagnostics()['status'], "
    "future_features.diagnostics()['status']]; "
    "assert all(item == 'ready' for item in checks), checks; "
    "print('capabilities ok')"
)


def run_validation(args: argparse.Namespace) -> int:
    results = [_run_step(step) for step in build_steps(args)]
    for result in results:
        icon = {"ok": "PASS", "warn": "WARN", "fail": "FAIL"}[result.status]
        print(_console_safe(f"{icon} {result.name}: {result.status}"))
        if result.detail and (args.verbose or result.status != "ok"):
            print(_console_safe(f"  {result.detail}"))

    failures = sum(1 for result in results if result.status == "fail")
    warnings = sum(1 for result in results if result.status == "warn")
    passed = sum(1 for result in results if result.status == "ok")
    print()
    print(
        _console_safe(
            f"Daily-use validation: {passed} passed, "
            f"{warnings} warnings, {failures} failures"
        )
    )
    return 1 if failures else 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Grandpa daily-use validation.")
    parser.add_argument(
        "--skip-app-launch",
        action="store_true",
        help="Dry-run the safe app command parser instead of opening Notepad.",
    )
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Skip `npm run build` in frontend/.",
    )
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Skip Docker build validation.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print command output snippets for passing steps too.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run_validation(parse_args(argv or sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
