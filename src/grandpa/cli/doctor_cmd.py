"""``Grandpa doctor`` — run diagnostic checks on the Grandpa installation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
    status: str  # "ok", "info", "warn", "fail"
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


def _project_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists() and (
            parent / "src" / "grandpa"
        ).exists():
            return parent
    return None


def _path_text(path: str | Path | None) -> str:
    return str(path) if path else "Not detected"


def _grandpa_executable_candidates() -> list[str]:
    try:
        if sys.platform == "win32":
            proc = subprocess.run(
                ["where", "grandpa"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0:
                candidates = [line.strip() for line in proc.stdout.splitlines()]
            else:
                candidates = []
        else:
            found = shutil.which("grandpa")
            candidates = [found] if found else []
    except Exception:
        candidates = []

    seen = set()
    unique = []
    for item in candidates:
        if not item:
            continue
        key = item.casefold() if sys.platform == "win32" else item
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    if not unique:
        found = shutil.which("grandpa")
        if found:
            unique.append(found)
    return unique


def _active_grandpa_executable(candidates: list[str]) -> str:
    """Return the current launcher path when it can be identified safely."""

    invoked = Path(sys.argv[0]).expanduser()
    if invoked.name.casefold() in {"grandpa", "grandpa.exe"}:
        try:
            if invoked.exists():
                return str(invoked.resolve())
        except OSError:
            pass
    executable_dir = Path(sys.executable).resolve().parent
    for candidate in candidates:
        try:
            if Path(candidate).resolve().parent == executable_dir:
                return candidate
        except OSError:
            continue
    return candidates[0] if candidates else "Not found on PATH"


def _duplicate_launcher_guidance(candidates: list[str], preferred: str) -> str:
    lines = [
        *candidates,
        f"Prefer: {preferred}",
        "Use `uv run grandpa ...` to force the project environment.",
    ]
    for candidate in candidates:
        candidate_path = Path(candidate)
        if candidate.casefold() == preferred.casefold():
            continue
        scripts_dir = candidate_path.parent
        python = scripts_dir.parent / "python.exe"
        if python.exists():
            lines.append(
                f'Review the other install with: "{python}" -m pip show grandpa'
            )
            lines.append(
                f'If confirmed stale, remove it with: "{python}" -m pip uninstall grandpa'
            )
    return "\n".join(lines)


def _check_runtime_environment() -> list[CheckResult]:
    project_root = _project_root()
    package_root = Path(__file__).resolve().parents[1]
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if not virtual_env and sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        virtual_env = sys.prefix

    checks = [
        CheckResult("Python executable", "ok", sys.executable),
        CheckResult("Grandpa package path", "ok", str(package_root)),
        CheckResult("Active virtual environment", "ok", _path_text(virtual_env)),
        CheckResult("Project root", "ok", _path_text(project_root)),
    ]

    candidates = _grandpa_executable_candidates()
    active = _active_grandpa_executable(candidates)
    checks.append(CheckResult("Grandpa executable", "ok", active))
    checks.append(
        CheckResult(
            "Grandpa executables on PATH",
            "info",
            f"{len(candidates)} found",
            details="\n".join(candidates) if candidates else "None found",
        )
    )

    if len(candidates) > 1:
        preferred = None
        if project_root:
            expected = project_root / ".venv" / "Scripts" / "grandpa.exe"
            for candidate in candidates:
                if Path(candidate).resolve() == expected.resolve():
                    preferred = str(expected)
                    break
        preferred = preferred or active
        checks.append(
            CheckResult(
                "Grandpa executable duplicates",
                "warn",
                f"{len(candidates)} executables found on PATH",
                details=_duplicate_launcher_guidance(candidates, preferred),
            )
        )
    else:
        checks.append(
            CheckResult(
                "Grandpa executable duplicates",
                "ok",
                "No duplicate Grandpa executables detected",
            )
        )

    return checks


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


def _active_engine_keys(config: Any | None = None) -> set[str]:
    config = config or _get_config()
    active = {
        str(getattr(getattr(config, "engine", None), "default", "") or "").strip(),
        str(
            getattr(getattr(config, "intelligence", None), "preferred_engine", "") or ""
        ).strip(),
    }
    return {key for key in active if key}


def _engine_is_configured(key: str, config: Any | None = None) -> bool:
    return key in _active_engine_keys(config)


def _check_engines() -> List[CheckResult]:
    """Probe active engines and list inactive integrations as informational."""
    results: List[CheckResult] = []

    _ensure_engines_imported()

    from grandpa.core.registry import EngineRegistry
    from grandpa.engine import _discovery

    config = _get_config()
    active_engines = _active_engine_keys(config)

    for key in sorted(EngineRegistry.keys()):
        if key not in active_engines:
            results.append(
                CheckResult(
                    f"Engine: {key}",
                    "info",
                    "Not configured",
                    details="Optional engine skipped. Set it as engine.default or intelligence.preferred_engine to check readiness.",
                )
            )
            continue
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
    """List models from healthy active engines."""
    results: List[CheckResult] = []

    _ensure_engines_imported()

    from grandpa.core.registry import EngineRegistry
    from grandpa.engine import _discovery

    config = _get_config()
    active_engines = _active_engine_keys(config)

    for key in sorted(EngineRegistry.keys()):
        if key not in active_engines:
            continue
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
        ("colbert", "Grandpa[memory-colbert]", "ColBERT memory backend"),
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


def _ollama_host(config: Any | None = None) -> str:
    from grandpa.engine.ollama import normalize_ollama_host

    config = config or _get_config()
    host = getattr(getattr(getattr(config, "engine", None), "ollama", None), "host", "")
    return normalize_ollama_host(host)


def _fetch_ollama_models(
    host: str, timeout: float = 1.5
) -> tuple[bool, list[str], str]:
    from grandpa.engine.ollama import OllamaEngine, normalize_ollama_host

    normalized_host = normalize_ollama_host(host)
    engine = OllamaEngine(host=normalized_host, timeout=timeout)
    try:
        models = engine.list_models()
        if engine.health():
            return True, models, "Reachable"
        return False, [], f"Unreachable at {normalized_host}"
    except Exception as exc:
        return False, [], str(exc)
    finally:
        engine.close()


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
        return CheckResult(
            "Windows app resolver ready", "ok", f"Ready ({count} allowlisted apps)"
        )
    except Exception as exc:
        return CheckResult(
            "Windows app resolver ready", "fail", "Failed", details=str(exc)
        )


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


def _check_gmail_readiness() -> CheckResult:
    try:
        from grandpa.gmail import GmailAuthManager
        from grandpa.gmail.auth import GmailDependencyError

        status = GmailAuthManager().status()
        if not status.configured:
            return CheckResult(
                "Gmail integration",
                "info",
                "Optional / not configured",
                details=f"OAuth client secret not found. Setup expects: {status.client_secret_path}",
            )
        try:
            GmailAuthManager._ensure_dependencies()  # noqa: SLF001 - doctor validates optional runtime dependencies.
        except GmailDependencyError as exc:
            return CheckResult(
                "Gmail integration", "warn", "Dependencies missing", details=str(exc)
            )
        if status.ready:
            account = f" ({status.account})" if status.account else ""
            return CheckResult(
                "Gmail integration",
                "ok",
                f"Connected{account}",
                details=f"Token: {status.token_path}",
            )
        return CheckResult(
            "Gmail integration",
            "warn",
            "OAuth setup incomplete",
            details=status.message,
        )
    except Exception as exc:
        return CheckResult(
            "Gmail integration", "warn", "Could not check Gmail", details=str(exc)
        )


def _check_calendar_readiness() -> CheckResult:
    try:
        from grandpa.calendar import CalendarAuthManager
        from grandpa.calendar.auth import CalendarDependencyError

        status = CalendarAuthManager().status()
        if not status.configured:
            return CheckResult(
                "Google Calendar integration",
                "info",
                "Optional / not configured",
                details=f"OAuth client secret not found. Setup expects: {status.client_secret_path}",
            )
        try:
            CalendarAuthManager._ensure_dependencies()  # noqa: SLF001 - doctor validates optional runtime dependencies.
        except CalendarDependencyError as exc:
            return CheckResult(
                "Google Calendar integration",
                "warn",
                "Dependencies missing",
                details=str(exc),
            )
        if status.ready:
            account = f" ({status.account})" if status.account else ""
            return CheckResult(
                "Google Calendar integration",
                "ok",
                f"Connected{account}",
                details=f"Token: {status.token_path}",
            )
        return CheckResult(
            "Google Calendar integration",
            "warn",
            "OAuth setup incomplete",
            details=status.message,
        )
    except Exception as exc:
        return CheckResult(
            "Google Calendar integration",
            "warn",
            "Could not check Calendar",
            details=str(exc),
        )


def _check_notes_readiness() -> CheckResult:
    try:
        from grandpa.notes import NotesStore

        status, message = NotesStore().status()
        if status == "ready":
            return CheckResult("Notes storage", "ok", "Ready", details=message)
        if status == "permission_denied":
            return CheckResult(
                "Notes storage", "warn", "Permission denied", details=message
            )
        return CheckResult(
            "Notes storage", "warn", "Storage unavailable", details=message
        )
    except Exception as exc:
        return CheckResult(
            "Notes storage", "warn", "Could not check notes storage", details=str(exc)
        )


def _check_downloads_readiness() -> CheckResult:
    try:
        from grandpa.downloads import DownloadsScanner

        status, message = DownloadsScanner().status()
        if status == "ready":
            return CheckResult("Downloads directory", "ok", "Ready", details=message)
        if status == "permission_denied":
            return CheckResult(
                "Downloads directory", "warn", "Permission denied", details=message
            )
        if status == "missing":
            return CheckResult(
                "Downloads directory",
                "warn",
                "Configured folder missing",
                details=message,
            )
        return CheckResult(
            "Downloads directory", "warn", "Unavailable", details=message
        )
    except Exception as exc:
        return CheckResult(
            "Downloads directory", "warn", "Could not check Downloads", details=str(exc)
        )


def _check_web_search_readiness() -> CheckResult:
    try:
        from grandpa.web_search import WebSearchClient

        status, message = WebSearchClient().status()
        if status == "ready":
            return CheckResult("Web search", "ok", "Ready", details=message)
        return CheckResult(
            "Web search", "info", "Optional / not configured", details=message
        )
    except Exception as exc:
        return CheckResult(
            "Web search", "warn", "Could not check web search", details=str(exc)
        )


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
        return CheckResult(
            "Notifications", "warn", "Missing/optional", details=str(exc)
        )


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
    except ModuleNotFoundError as exc:
        if exc.name == "fastapi":
            return CheckResult(
                "Background scheduler",
                "warn",
                "Missing/optional",
                details=(
                    "Server startup requires the optional server extra. "
                    "Run `uv sync --extra server --link-mode=copy` to enable "
                    "backend scheduler startup checks."
                ),
            )
        return CheckResult("Background scheduler", "fail", "Failed", details=str(exc))
    except Exception as exc:
        return CheckResult("Background scheduler", "fail", "Failed", details=str(exc))


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
        str(
            status.get("recommendation")
            or "Fix release gate blockers before packaging."
        ),
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
                "info",
                "Optional / not configured",
                details="Rust extension is not required by the active runtime.",
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
            _check_notes_readiness(),
            _check_downloads_readiness(),
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
        ]
    )
    return checks


# -- Main command -------------------------------------------------------------

_STATUS_ICONS = {
    "ok": "[green]\u2713[/green]",
    "info": "[dim]i[/dim]",
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
    checks.append(_check_security_profile())
    return checks


def _build_doctor_dashboard() -> List[DoctorSection]:
    """Build the grouped doctor dashboard without duplicate visible checks."""
    optional_integrations: List[CheckResult] = []

    core_runtime = [
        _check_python_version(),
        *_check_runtime_environment(),
        _check_config_exists(),
        _check_config_parses(),
        _check_rest_api_installed(),
        _check_security_profile(),
    ]

    ai_engines = []
    for check in _check_engines():
        if check.status == "info":
            optional_integrations.append(check)
        else:
            ai_engines.append(check)
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
        ]
    )
    gmail_readiness = _check_gmail_readiness()
    if gmail_readiness.status == "info":
        optional_integrations.append(gmail_readiness)
    else:
        daily_features.append(gmail_readiness)
    calendar_readiness = _check_calendar_readiness()
    if calendar_readiness.status == "info":
        optional_integrations.append(calendar_readiness)
    else:
        daily_features.append(calendar_readiness)
    web_search_readiness = _check_web_search_readiness()
    if web_search_readiness.status == "info":
        optional_integrations.append(web_search_readiness)
    else:
        daily_features.append(web_search_readiness)

    system_integration: List[CheckResult] = []
    system_integration.extend(
        [
            _check_notifications_ready(),
            _check_background_scheduler_ready(),
            _check_release_gate_status(),
        ]
    )
    for check in _check_background_tasks():
        if check.status == "info":
            optional_integrations.append(check)
        else:
            system_integration.append(check)

    sections = [
        DoctorSection("Core Runtime", core_runtime),
        DoctorSection("AI Engines", ai_engines),
        DoctorSection("Daily Use Features", daily_features),
        DoctorSection("System Integration", system_integration),
    ]
    if optional_integrations:
        sections.append(DoctorSection("Optional Integrations", optional_integrations))
    return sections


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
    return "READY"


def _readiness_style(label: str) -> str:
    if label == "READY":
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
    info_count = sum(1 for c in checks if c.status == "info")
    warn_count = sum(1 for c in checks if c.status == "warn")
    fail_count = sum(1 for c in checks if c.status == "fail")
    readiness = _readiness_label(checks)
    console.print()
    console.print("[bold]Final Summary[/bold]")
    console.print(
        f"  {ok_count} passed, {info_count} optional/skipped, {warn_count} warnings, {fail_count} failures"
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
