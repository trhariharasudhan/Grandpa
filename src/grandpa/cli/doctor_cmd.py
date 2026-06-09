"""``Grandpa doctor`` — run diagnostic checks on the Grandpa installation."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from rich.console import Console
from rich.table import Table

from grandpa.core.config import DEFAULT_CONFIG_PATH, load_config


@dataclass
class CheckResult:
    """Result of a single diagnostic check."""

    name: str
    status: str  # "ok", "warn", "fail"
    message: str
    details: Optional[str] = None


@dataclass
class DoctorSection:
    """A grouped section in the doctor readiness dashboard."""

    name: str
    checks: List[CheckResult]


# -- Individual checks -------------------------------------------------------


def _check_python_version() -> CheckResult:
    """Check that Python version is >= 3.10."""
    ver = sys.version_info
    version_str = f"{ver.major}.{ver.minor}.{ver.micro}"
    if (ver.major, ver.minor) >= (3, 10):
        return CheckResult("Python version", "ok", version_str)
    return CheckResult("Python version", "fail", f"{version_str} (requires >= 3.10)")


def _check_config_exists() -> CheckResult:
    """Check that the config file exists."""
    if DEFAULT_CONFIG_PATH.exists():
        return CheckResult("Config file", "ok", str(DEFAULT_CONFIG_PATH))
    return CheckResult(
        "Config file",
        "warn",
        f"Not found at {DEFAULT_CONFIG_PATH}",
        details="Run `Grandpa init` to generate a config file.",
    )


def _windows_setup_hint(tool: str) -> str:
    hints = {
        "ollama": "Install Ollama from https://ollama.com/download and run `ollama serve`.",
        "docker": "Install Docker Desktop and wait until the engine is running.",
        "node": "Install Node.js 22+ from https://nodejs.org/.",
        "pillow": "Run `uv sync --extra server --link-mode=copy`; Pillow is a project dependency.",
        "pyautogui": (
            "Run `uv sync --extra server --link-mode=copy`; "
            "pyautogui is a project dependency."
        ),
        "pytesseract": (
            "Run `uv sync --extra server --link-mode=copy`; "
            "pytesseract is a project dependency."
        ),
        "tesseract": "Install Tesseract OCR for Windows and add tesseract.exe to PATH.",
    }
    return hints[tool]


def _check_config_parses() -> CheckResult:
    """Check that the config file parses successfully."""
    if not DEFAULT_CONFIG_PATH.exists():
        return CheckResult("Config parsing", "warn", "Skipped (no config file)")
    try:
        load_config()
        return CheckResult("Config parsing", "ok", "Config loaded successfully")
    except Exception as exc:
        return CheckResult("Config parsing", "fail", f"Parse error: {exc}")


def _ensure_engines_imported() -> None:
    """Import engine modules to trigger registration decorators."""
    try:
        import grandpa.engine  # noqa: F401
    except Exception:
        pass


def _get_config() -> Any:
    """Load config or return a default if parsing fails."""
    try:
        return load_config()
    except Exception:
        from grandpa.core.config import GrandpaConfig

        return GrandpaConfig()


def _check_engines() -> List[CheckResult]:
    """Probe each registered engine for health."""
    results: List[CheckResult] = []

    _ensure_engines_imported()

    from grandpa.core.registry import EngineRegistry
    from grandpa.engine import _discovery

    config = _get_config()

    for key in sorted(EngineRegistry.keys()):
        try:
            engine = _discovery._make_engine(key, config)
            if engine.health():
                results.append(CheckResult(f"Engine: {key}", "ok", "Reachable"))
            else:
                results.append(CheckResult(f"Engine: {key}", "warn", "Unreachable"))
        except Exception as exc:
            results.append(
                CheckResult(f"Engine: {key}", "warn", f"Unreachable ({exc})")
            )

    if not results:
        results.append(CheckResult("Engines", "warn", "No engines registered"))

    return results


def _check_models() -> List[CheckResult]:
    """List models from healthy engines."""
    results: List[CheckResult] = []

    _ensure_engines_imported()

    from grandpa.core.registry import EngineRegistry
    from grandpa.engine import _discovery

    config = _get_config()

    for key in sorted(EngineRegistry.keys()):
        try:
            engine = _discovery._make_engine(key, config)
            if engine.health():
                models = engine.list_models()
                if models:
                    model_list = ", ".join(models[:5])
                    suffix = f" (+{len(models) - 5} more)" if len(models) > 5 else ""
                    results.append(
                        CheckResult(
                            f"Models: {key}",
                            "ok",
                            f"{model_list}{suffix}",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            f"Models: {key}",
                            "warn",
                            "No models available",
                            details="Pull a model (e.g. `ollama pull qwen3.5:2b`).",
                        )
                    )
        except Exception:
            continue

    return results


def _check_default_model() -> CheckResult:
    """Check whether the configured default model is available."""
    try:
        config = load_config()
    except Exception:
        return CheckResult("Default model", "warn", "Skipped (config unavailable)")

    default_model = config.intelligence.default_model
    if not default_model:
        return CheckResult(
            "Default model",
            "ok",
            "Not configured (auto-routing enabled)",
            details="Router will select a model dynamically.",
        )

    _ensure_engines_imported()

    from grandpa.core.registry import EngineRegistry
    from grandpa.engine import _discovery

    preferred = config.intelligence.preferred_engine or config.engine.default
    check_order = []
    if preferred:
        check_order.append(preferred)
    check_order += [k for k in sorted(EngineRegistry.keys()) if k != preferred]

    for key in check_order:
        try:
            engine = _discovery._make_engine(key, config)
            if engine.health():
                models = engine.list_models()
                if default_model in models:
                    return CheckResult(
                        "Default model",
                        "ok",
                        f"{default_model} (on {key})",
                    )
        except Exception:
            continue

    return CheckResult(
        "Default model",
        "warn",
        f"{default_model} not found on any engine",
    )


def _check_optional_deps() -> List[CheckResult]:
    """Check availability of optional dependency packages."""
    results: List[CheckResult] = []
    optional_packages = [
        ("fastapi", "Grandpa[server]", "REST API server"),
        ("torch", "pip install torch", "SFT/GRPO training"),
        ("pynvml", "Grandpa[gpu-metrics]", "NVIDIA energy monitoring"),
        ("amdsmi", "Grandpa[energy-amd]", "AMD energy monitoring"),
        ("colbert", "Grandpa[memory-colbert]", "ColBERT memory backend"),
        ("zeus", "Grandpa[energy-apple]", "Apple Silicon energy monitoring"),
    ]
    for pkg, install_hint, description in optional_packages:
        try:
            __import__(pkg)
            results.append(CheckResult(f"Optional: {description}", "ok", "Installed"))
        except Exception:
            results.append(
                CheckResult(
                    f"Optional: {description}",
                    "warn",
                    f"Not installed ({install_hint})",
                )
            )
    return results


def _check_security_profile() -> CheckResult:
    """Check if a security profile is configured."""
    try:
        from grandpa.core.config import load_config

        config = load_config()
        if config.security.profile:
            return CheckResult(
                name="Security profile",
                status="ok",
                message=f"Profile '{config.security.profile}' active",
            )
        return CheckResult(
            name="Security profile",
            status="warn",
            message="No security profile set",
            details="Recommended: add security.profile = 'personal' to config.toml",
        )
    except Exception as exc:
        return CheckResult(
            name="Security profile",
            status="fail",
            message=f"Could not check: {exc}",
        )


def _check_nodejs() -> CheckResult:
    """Check Node.js version for Node-backed integrations."""
    node_path = shutil.which("node")
    if not node_path:
        return CheckResult(
            "Node.js",
            "warn",
            "Not found",
            details=_windows_setup_hint("node"),
        )
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version_str = result.stdout.strip()
        # Parse "v22.1.0" -> (22, 1, 0)
        parts = version_str.lstrip("v").split(".")
        major = int(parts[0])
        if major >= 22:
            return CheckResult("Node.js", "ok", version_str)
        return CheckResult(
            "Node.js",
            "warn",
            f"{version_str} (requires >= v22)",
            details=_windows_setup_hint("node"),
        )
    except Exception as exc:
        return CheckResult("Node.js", "warn", f"Error checking version: {exc}")


def _ollama_host(config: Any | None = None) -> str:
    config = config or _get_config()
    host = getattr(getattr(getattr(config, "engine", None), "ollama", None), "host", "")
    return (host or "http://localhost:11434").rstrip("/")


def _fetch_ollama_models(host: str, timeout: float = 1.5) -> tuple[bool, list[str], str]:
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = []
        for item in payload.get("models", []):
            name = item.get("name") if isinstance(item, dict) else None
            if name:
                models.append(name)
        return True, models, "Reachable"
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return False, [], str(exc)


def _check_ollama_reachable() -> CheckResult:
    host = _ollama_host()
    ok, _, detail = _fetch_ollama_models(host)
    if ok:
        return CheckResult("Ollama reachable", "ok", f"Ready ({host})")
    return CheckResult(
        "Ollama reachable",
        "warn",
        "Missing/optional",
        details=f"{_windows_setup_hint('ollama')} Last error: {detail}",
    )


def _check_daily_default_model() -> CheckResult:
    config = _get_config()
    model = getattr(getattr(config, "intelligence", None), "default_model", "")
    if not model:
        return CheckResult("Default model available", "ok", "Ready (auto-routing)")
    host = _ollama_host(config)
    ok, models, detail = _fetch_ollama_models(host)
    if ok and model in models:
        return CheckResult("Default model available", "ok", f"Ready ({model})")
    if ok:
        return CheckResult(
            "Default model available",
            "warn",
            "Missing/optional",
            details=f"Pull the model with `ollama pull {model}`.",
        )
    return CheckResult(
        "Default model available",
        "warn",
        "Missing/optional",
        details=f"{_windows_setup_hint('ollama')} Last error: {detail}",
    )


def _check_rest_api_installed() -> CheckResult:
    missing = []
    for pkg in ("fastapi", "uvicorn"):
        try:
            __import__(pkg)
        except Exception:
            missing.append(pkg)
    if not missing:
        return CheckResult("REST API server installed", "ok", "Ready")
    return CheckResult(
        "REST API server installed",
        "warn",
        "Missing/optional",
        details="Run `uv sync --extra server --link-mode=copy`.",
    )


def _check_windows_app_resolver_ready() -> CheckResult:
    try:
        from grandpa.windows_app_resolver import APP_DEFINITIONS

        count = len(APP_DEFINITIONS)
        return CheckResult("Windows app resolver ready", "ok", f"Ready ({count} allowlisted apps)")
    except Exception as exc:
        return CheckResult("Windows app resolver ready", "fail", "Failed", details=str(exc))


def _check_known_app(app_name: str) -> CheckResult:
    try:
        from grandpa.windows_app_resolver import resolve_app

        result = resolve_app(app_name)
        if result.status == "found":
            return CheckResult(
                f"Known app: {result.display_name}",
                "ok",
                "Ready",
                result.launch_target,
            )
        if result.status == "unsupported":
            return CheckResult(
                f"Known app: {result.display_name}",
                "warn",
                "Missing/optional",
                details="Windows app detection is only available on Windows desktop.",
            )
        return CheckResult(
            f"Known app: {result.display_name}",
            "warn",
            "Missing/optional",
            details=result.message,
        )
    except Exception as exc:
        return CheckResult(f"Known app: {app_name}", "fail", "Failed", details=str(exc))


def _check_local_actions_ready() -> CheckResult:
    try:
        from grandpa.local_actions import handle_local_action

        result = handle_local_action("what time is it", execute=False)
        if result.status in {"handled", "requires_confirmation"}:
            return CheckResult("Local actions ready", "ok", "Ready")
        return CheckResult(
            "Local actions ready",
            "warn",
            "Missing/optional",
            details=result.status,
        )
    except Exception as exc:
        return CheckResult("Local actions ready", "fail", "Failed", details=str(exc))


def _check_existing_sqlite_db(name: str, path: Path) -> CheckResult:
    if not path.exists():
        return CheckResult(
            name,
            "warn",
            "Missing/optional",
            details=f"Will be created on first use: {path}",
        )
    try:
        import sqlite3

        uri = f"file:{path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=1.0) as conn:
            conn.execute("SELECT 1").fetchone()
        return CheckResult(name, "ok", "Ready", str(path))
    except Exception as exc:
        return CheckResult(name, "fail", "Failed", details=str(exc))


def _check_approval_db_ready() -> CheckResult:
    from grandpa.local_action_approvals import DEFAULT_APPROVAL_DB

    return _check_existing_sqlite_db("Approval database ready", DEFAULT_APPROVAL_DB)


def _check_memory_db_ready() -> CheckResult:
    from grandpa.memory_context import DEFAULT_MEMORY_DB

    return _check_existing_sqlite_db("Memory database ready", DEFAULT_MEMORY_DB)


def _check_file_db_ready() -> CheckResult:
    from grandpa.file_assistant import DEFAULT_FILE_DB

    return _check_existing_sqlite_db("File assistant database ready", DEFAULT_FILE_DB)


def _check_scheduler_db_ready() -> CheckResult:
    from grandpa.task_scheduler import DEFAULT_SCHEDULER_DB

    return _check_existing_sqlite_db("Scheduler database ready", DEFAULT_SCHEDULER_DB)


def _check_scheduler_daemon_ready() -> CheckResult:
    try:
        from grandpa.scheduler_daemon import BackgroundSchedulerDaemon  # noqa: F401
        from grandpa.task_scheduler import SchedulerStore  # noqa: F401

        return CheckResult("Scheduler daemon import/startup ready", "ok", "Ready")
    except Exception as exc:
        return CheckResult(
            "Scheduler daemon import/startup ready",
            "fail",
            "Failed",
            details=str(exc),
        )


def _check_screen_awareness_available() -> CheckResult:
    try:
        import grandpa.screen_awareness  # noqa: F401

        return CheckResult("Screen awareness available", "ok", "Ready")
    except Exception as exc:
        return CheckResult(
            "Screen awareness available",
            "warn",
            "Missing/optional",
            details=str(exc),
        )


def _check_screenshot_backend() -> CheckResult:
    backends = []
    try:
        from PIL import ImageGrab  # noqa: F401

        backends.append("Pillow ImageGrab")
    except Exception:
        pass
    try:
        import pyautogui  # noqa: F401

        backends.append("pyautogui")
    except Exception:
        pass
    if backends:
        return CheckResult("Screenshot backend", "ok", f"Ready ({', '.join(backends)})")
    return CheckResult(
        "Screenshot backend",
        "warn",
        "Missing/optional",
        details=f"{_windows_setup_hint('pillow')} {_windows_setup_hint('pyautogui')}",
    )


def _check_ocr_backend() -> List[CheckResult]:
    results = []
    try:
        import pytesseract  # noqa: F401

        results.append(CheckResult("OCR backend: pytesseract", "ok", "Ready"))
    except Exception:
        results.append(
            CheckResult(
                "OCR backend: pytesseract",
                "warn",
                "Missing/optional",
                details=_windows_setup_hint("pytesseract"),
            )
        )
    if shutil.which("tesseract"):
        results.append(CheckResult("OCR backend: Tesseract executable", "ok", "Ready"))
    else:
        results.append(
            CheckResult(
                "OCR backend: Tesseract executable",
                "warn",
                "Missing/optional",
                details=_windows_setup_hint("tesseract"),
            )
        )
    return results


def _check_desktop_automation_backend() -> CheckResult:
    try:
        import pyautogui  # noqa: F401

        return CheckResult("Desktop automation backend", "ok", "Ready")
    except Exception:
        return CheckResult(
            "Desktop automation backend",
            "warn",
            "Missing/optional",
            details=_windows_setup_hint("pyautogui"),
        )


def _check_voice_frontend_note() -> CheckResult:
    return CheckResult(
        "Voice frontend support",
        "warn",
        "Missing/optional",
        details="Browser-based speech requires browser support and microphone permission.",
    )


def _check_voice_runtime_ready() -> CheckResult:
    try:
        from grandpa.voice import get_voice_runtime

        status = get_voice_runtime().status()
        input_engine = status.get("speech_input", {}).get("engine", "unknown")
        output_engine = status.get("speech_output", {}).get("engine", "unknown")
        return CheckResult(
            "Voice runtime backend",
            "ok",
            "Ready",
            details=f"Input: {input_engine}; output: {output_engine}; push-to-talk transcript mode available.",
        )
    except Exception as exc:
        return CheckResult(
            "Voice runtime backend",
            "warn",
            "Missing/optional",
            details=f"Voice runtime could not initialize: {exc}",
        )


def _check_docker_readiness() -> List[CheckResult]:
    docker = shutil.which("docker")
    if not docker:
        return [
            CheckResult(
                "Docker command available",
                "warn",
                "Missing/optional",
                details=_windows_setup_hint("docker"),
            ),
            CheckResult(
                "Docker daemon reachable",
                "warn",
                "Missing/optional",
                details=_windows_setup_hint("docker"),
            ),
        ]
    results = [CheckResult("Docker command available", "ok", "Ready", docker)]
    try:
        proc = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            results.append(
                CheckResult(
                    "Docker daemon reachable",
                    "ok",
                    f"Ready ({proc.stdout.strip()})",
                )
            )
        else:
            results.append(
                CheckResult(
                    "Docker daemon reachable",
                    "warn",
                    "Missing/optional",
                    details=_windows_setup_hint("docker"),
                )
            )
    except Exception as exc:
        results.append(
            CheckResult(
                "Docker daemon reachable",
                "warn",
                "Missing/optional",
                details=f"{_windows_setup_hint('docker')} Last error: {exc}",
            )
        )
    return results


def _check_notifications_ready() -> CheckResult:
    try:
        from grandpa.task_scheduler import SchedulerStore  # noqa: F401

        return CheckResult(
            "Notifications",
            "ok",
            "Ready",
            "Routine and reminder notifications can be stored locally.",
        )
    except Exception as exc:
        return CheckResult("Notifications", "warn", "Missing/optional", details=str(exc))


def _check_background_scheduler_ready() -> CheckResult:
    try:
        from grandpa.scheduler_daemon import BackgroundSchedulerDaemon  # noqa: F401
        from grandpa.server.app import create_app  # noqa: F401

        return CheckResult(
            "Background scheduler",
            "ok",
            "Ready",
            "Backend startup can register the routine scheduler daemon.",
        )
    except Exception as exc:
        return CheckResult("Background scheduler", "fail", "Failed", details=str(exc))


def _check_frontend_readiness() -> CheckResult:
    static_index = Path(__file__).resolve().parents[1] / "server" / "static" / "index.html"
    source_index = Path.cwd() / "frontend" / "index.html"
    package_json = Path.cwd() / "frontend" / "package.json"
    if static_index.exists():
        return CheckResult("Frontend readiness", "ok", "Ready", str(static_index))
    if source_index.exists() and package_json.exists():
        return CheckResult(
            "Frontend readiness",
            "warn",
            "Missing/optional",
            details=(
                "Frontend source exists; run `cd frontend && npm run build` "
                "to refresh packaged assets."
            ),
        )
    return CheckResult(
        "Frontend readiness",
        "warn",
        "Missing/optional",
        details="Frontend assets were not detected.",
        )


def _check_release_gate_status() -> CheckResult:
    """Report the latest final release gate status without rerunning it."""
    import os

    if os.environ.get("GRANDPA_DOCTOR_SKIP_RELEASE_GATE") == "1":
        return CheckResult(
            "Final release gate",
            "ok",
            "Running now",
            "The active final release gate is executing doctor as one of its checks.",
        )
    try:
        from grandpa.release_gate import release_gate_status

        status = release_gate_status()
    except Exception as exc:
        return CheckResult(
            "Final release gate",
            "warn",
            "Missing/optional",
            f"Could not read latest gate report: {exc.__class__.__name__}",
        )
    overall = str(status.get("overall_status") or "NOT RUN")
    if status.get("status") == "not_run":
        return CheckResult(
            "Final release gate",
            "warn",
            "Not run yet",
            "Run `scripts\\release\\final-release-gate.ps1` before packaging or pushing a release.",
        )
    if status.get("pass"):
        summary = status.get("summary", {})
        detail = (
            f"Finished {status.get('finished_at')}. "
            f"{summary.get('passed', 0)} passed, {summary.get('warnings', 0)} warnings."
        )
        return CheckResult("Final release gate", "ok", overall, detail)
    return CheckResult(
        "Final release gate",
        "fail",
        overall,
        str(status.get("recommendation") or "Fix release gate blockers before packaging."),
    )


def _check_background_tasks() -> List[CheckResult]:
    from grandpa.cli._bg_state import get_status

    bg = get_status()
    results: List[CheckResult] = []
    if bg.rust_extension == "ready":
        results.append(CheckResult("Rust extension background task", "ok", "Ready"))
    elif bg.rust_extension == "failed":
        results.append(
            CheckResult(
                "Rust extension background task",
                "fail",
                "Failed",
                details=(
                    f"{bg.rust_error[:80]}\n"
                    "Retry: ~/.grandpa/.scripts/install-rust.sh && "
                    "~/.grandpa/.scripts/build-extension.sh"
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                "Rust extension background task",
                "warn",
                "Missing/optional",
                details="Rust extension is building in the background.",
            )
        )

    if not bg.models:
        results.append(
            CheckResult(
                "Background model downloads",
                "ok",
                "Ready",
                "No model downloads are currently tracked.",
            )
        )
    for model_id, state in bg.models.items():
        if state == "ready":
            results.append(CheckResult(f"Background model: {model_id}", "ok", "Ready"))
        elif state == "failed":
            results.append(
                CheckResult(
                    f"Background model: {model_id}",
                    "fail",
                    "Failed",
                    details=f"Retry: ~/.grandpa/.scripts/pull-model.sh {model_id}",
                )
            )
        else:
            results.append(
                CheckResult(
                    f"Background model: {model_id}",
                    "warn",
                    "Missing/optional",
                    details="Model download is still running.",
                )
            )
    return results


def _check_daily_use_readiness() -> List[CheckResult]:
    checks: List[CheckResult] = [
        _check_ollama_reachable(),
        _check_daily_default_model(),
        _check_rest_api_installed(),
        _check_security_profile(),
        _check_windows_app_resolver_ready(),
    ]
    for app_name in ("chrome", "edge", "vscode", "notepad", "calculator"):
        checks.append(_check_known_app(app_name))
    checks.extend(
        [
            _check_local_actions_ready(),
            _check_approval_db_ready(),
            _check_memory_db_ready(),
            _check_file_db_ready(),
            _check_scheduler_db_ready(),
            _check_scheduler_daemon_ready(),
            _check_screen_awareness_available(),
            _check_screenshot_backend(),
        ]
    )
    checks.extend(_check_ocr_backend())
    checks.extend(
        [
            _check_desktop_automation_backend(),
            _check_voice_runtime_ready(),
            _check_voice_frontend_note(),
        ]
    )
    checks.extend(_check_docker_readiness())
    return checks


# -- Main command -------------------------------------------------------------

_STATUS_ICONS = {
    "ok": "[green]\u2713[/green]",
    "warn": "[yellow]![/yellow]",
    "fail": "[red]\u2717[/red]",
}


def _run_all_checks() -> List[CheckResult]:
    """Run all diagnostic checks and return results."""
    checks: List[CheckResult] = []
    checks.append(_check_python_version())
    checks.append(_check_config_exists())
    checks.append(_check_config_parses())
    checks.extend(_check_engines())
    checks.extend(_check_models())
    checks.append(_check_default_model())
    checks.extend(_check_optional_deps())
    checks.append(_check_nodejs())
    checks.append(_check_security_profile())
    return checks


def _build_doctor_dashboard() -> List[DoctorSection]:
    """Build the grouped doctor dashboard without duplicate visible checks."""
    core_runtime = [
        _check_python_version(),
        _check_config_exists(),
        _check_config_parses(),
        _check_rest_api_installed(),
        _check_security_profile(),
        _check_nodejs(),
    ]

    ai_engines = []
    ai_engines.extend(_check_engines())
    ai_engines.append(_check_default_model())
    ai_engines.extend(_check_models())

    daily_features: List[CheckResult] = [
        _check_windows_app_resolver_ready(),
    ]
    for app_name in ("chrome", "edge", "vscode", "notepad", "calculator"):
        daily_features.append(_check_known_app(app_name))
    daily_features.extend(
        [
            _check_local_actions_ready(),
            _check_approval_db_ready(),
            _check_memory_db_ready(),
            _check_file_db_ready(),
            _check_scheduler_db_ready(),
            _check_scheduler_daemon_ready(),
            _check_screen_awareness_available(),
            _check_screenshot_backend(),
        ]
    )
    daily_features.extend(_check_ocr_backend())
    daily_features.extend(
        [
            _check_desktop_automation_backend(),
            _check_voice_runtime_ready(),
            _check_voice_frontend_note(),
        ]
    )

    system_integration: List[CheckResult] = []
    system_integration.extend(_check_docker_readiness())
    system_integration.extend(
        [
            _check_notifications_ready(),
            _check_background_scheduler_ready(),
            _check_frontend_readiness(),
            _check_release_gate_status(),
        ]
    )
    system_integration.extend(_check_background_tasks())

    return [
        DoctorSection("Core Runtime", core_runtime),
        DoctorSection("AI Engines", ai_engines),
        DoctorSection("Daily Use Features", daily_features),
        DoctorSection("System Integration", system_integration),
    ]


def _flatten_sections(sections: List[DoctorSection]) -> List[CheckResult]:
    checks: List[CheckResult] = []
    for section in sections:
        checks.extend(section.checks)
    return checks


def _readiness_label(checks: List[CheckResult]) -> str:
    failures = sum(1 for c in checks if c.status == "fail")
    warnings = sum(1 for c in checks if c.status == "warn")
    if failures:
        return "NEEDS SETUP"
    if warnings:
        return "PARTIALLY READY"
    return "DAILY USE READY"


def _readiness_style(label: str) -> str:
    if label == "DAILY USE READY":
        return "bold green"
    if label == "PARTIALLY READY":
        return "bold yellow"
    return "bold red"


def _results_to_dicts(checks: List[CheckResult]) -> List[Dict[str, Any]]:
    """Convert CheckResult list to JSON-serializable dicts."""
    return [asdict(c) for c in checks]


@click.command()
@click.option("--json", "as_json", is_flag=True, help="Output results as JSON.")
def doctor(as_json: bool) -> None:
    """Run diagnostic checks on your Grandpa installation."""
    sections = _build_doctor_dashboard()
    checks = _flatten_sections(sections)

    if as_json:
        click.echo(json.dumps(_results_to_dicts(checks), indent=2))
        return

    console = Console()
    console.print()
    console.print("[bold]Grandpa Doctor Dashboard[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("Section", style="bold", no_wrap=True)
    table.add_column("Status", width=3, justify="center")
    table.add_column("Check")
    table.add_column("Result")

    for section_index, section in enumerate(sections):
        if section_index:
            table.add_section()
        for check_index, check in enumerate(section.checks):
            icon = _STATUS_ICONS.get(check.status, "?")
            message = check.message
            if check.details:
                message += f"\n  [dim]{check.details}[/dim]"
            table.add_row(
                section.name if check_index == 0 else "",
                icon,
                check.name,
                message,
            )

    console.print(table)

    ok_count = sum(1 for c in checks if c.status == "ok")
    warn_count = sum(1 for c in checks if c.status == "warn")
    fail_count = sum(1 for c in checks if c.status == "fail")
    readiness = _readiness_label(checks)
    console.print()
    console.print("[bold]Final Summary[/bold]")
    console.print(
        f"  {ok_count} passed, {warn_count} warnings, {fail_count} failures"
    )
    console.print(f"  Overall readiness: [{_readiness_style(readiness)}]{readiness}[/]")

    failed_background = any(
        check.status == "fail"
        and (
            check.name.startswith("Rust extension background task")
            or check.name.startswith("Background model:")
        )
        for check in checks
    )
    if failed_background:
        raise click.exceptions.Exit(code=1)
