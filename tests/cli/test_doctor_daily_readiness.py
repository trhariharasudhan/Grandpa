from pathlib import Path
from unittest.mock import MagicMock

from grandpa.cli.doctor_cmd import (
    CheckResult,
    _build_doctor_dashboard,
    _check_daily_use_readiness,
    _check_docker_readiness,
    _check_existing_sqlite_db,
    _check_known_app,
    _fetch_ollama_models,
    _readiness_label,
)
from grandpa.windows_app_resolver import AppResolution


def test_fetch_ollama_models_parses_tags(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"models":[{"name":"qwen2.5:3b"}]}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: FakeResponse())

    ok, models, message = _fetch_ollama_models("http://localhost:11434")

    assert ok is True
    assert models == ["qwen2.5:3b"]
    assert message == "Reachable"


def test_existing_sqlite_db_missing_is_optional(tmp_path: Path) -> None:
    result = _check_existing_sqlite_db("Memory database ready", tmp_path / "missing.db")

    assert result.status == "warn"
    assert result.message == "Missing/optional"


def test_known_app_found(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app",
        lambda name: AppResolution(
            "chrome",
            "Chrome",
            "found",
            "path",
            "C:/Chrome/chrome.exe",
            "test",
            "ready",
        ),
    )

    result = _check_known_app("chrome")

    assert result.status == "ok"
    assert result.message == "Ready"


def test_docker_missing_is_optional(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)

    results = _check_docker_readiness()

    assert all(result.status == "warn" for result in results)
    assert all(result.message == "Missing/optional" for result in results)


def test_daily_readiness_contains_expected_checks(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.cli.doctor_cmd._fetch_ollama_models",
        lambda host: (True, ["qwen2.5:3b"], "Reachable"),
    )
    cfg = MagicMock()
    cfg.intelligence.default_model = "qwen2.5:3b"
    cfg.engine.ollama.host = "http://localhost:11434"
    cfg.security.profile = "personal"
    monkeypatch.setattr("grandpa.cli.doctor_cmd._get_config", lambda: cfg)
    monkeypatch.setattr("grandpa.cli.doctor_cmd.load_config", lambda: cfg)
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app",
        lambda name: AppResolution(
            name,
            name.title(),
            "found",
            "path",
            f"C:/{name}.exe",
            "test",
            "ready",
        ),
    )
    monkeypatch.setattr("grandpa.cli.doctor_cmd._check_docker_readiness", lambda: [])

    results = _check_daily_use_readiness()
    names = {result.name for result in results}

    assert "Ollama reachable" in names
    assert "Default model available" in names
    assert "Scheduler daemon import/startup ready" in names
    assert "Voice frontend support" in names


def test_dashboard_uses_expected_grouped_sections(monkeypatch) -> None:
    def patch_check(function_name: str, result: CheckResult) -> None:
        monkeypatch.setattr(f"grandpa.cli.doctor_cmd.{function_name}", lambda: result)

    patch_check("_check_python_version", CheckResult("Python version", "ok", "3.12"))
    patch_check("_check_config_exists", CheckResult("Config file", "ok", "Ready"))
    patch_check("_check_config_parses", CheckResult("Config parsing", "ok", "Ready"))
    patch_check(
        "_check_rest_api_installed",
        CheckResult("REST API server installed", "ok", "Ready"),
    )
    patch_check(
        "_check_security_profile",
        CheckResult("Security profile", "ok", "Ready"),
    )
    patch_check("_check_nodejs", CheckResult("Node.js", "ok", "v24"))
    monkeypatch.setattr(
        "grandpa.cli.doctor_cmd._check_engines",
        lambda: [CheckResult("Engine: ollama", "ok", "Reachable")],
    )
    patch_check("_check_default_model", CheckResult("Default model", "ok", "qwen"))
    monkeypatch.setattr("grandpa.cli.doctor_cmd._check_models", lambda: [])
    patch_check(
        "_check_windows_app_resolver_ready",
        CheckResult("Windows app resolver ready", "ok", "Ready"),
    )
    monkeypatch.setattr(
        "grandpa.cli.doctor_cmd._check_known_app",
        lambda name: CheckResult(f"Known app: {name}", "ok", "Ready"),
    )
    patch_check(
        "_check_local_actions_ready",
        CheckResult("Local actions ready", "ok", "Ready"),
    )
    patch_check(
        "_check_approval_db_ready",
        CheckResult("Approval database ready", "ok", "Ready"),
    )
    patch_check(
        "_check_memory_db_ready",
        CheckResult("Memory database ready", "ok", "Ready"),
    )
    patch_check(
        "_check_file_db_ready",
        CheckResult("File assistant database ready", "ok", "Ready"),
    )
    patch_check(
        "_check_scheduler_db_ready",
        CheckResult("Scheduler database ready", "ok", "Ready"),
    )
    patch_check(
        "_check_scheduler_daemon_ready",
        CheckResult("Scheduler daemon import/startup ready", "ok", "Ready"),
    )
    patch_check(
        "_check_screen_awareness_available",
        CheckResult("Screen awareness available", "ok", "Ready"),
    )
    patch_check(
        "_check_screenshot_backend",
        CheckResult("Screenshot backend", "ok", "Ready"),
    )
    monkeypatch.setattr(
        "grandpa.cli.doctor_cmd._check_ocr_backend",
        lambda: [CheckResult("OCR backend", "ok", "Ready")],
    )
    patch_check(
        "_check_desktop_automation_backend",
        CheckResult("Desktop automation backend", "ok", "Ready"),
    )
    patch_check(
        "_check_voice_frontend_note",
        CheckResult("Voice frontend support", "warn", "Missing/optional"),
    )
    monkeypatch.setattr(
        "grandpa.cli.doctor_cmd._check_docker_readiness",
        lambda: [CheckResult("Docker command available", "ok", "Ready")],
    )
    patch_check("_check_notifications_ready", CheckResult("Notifications", "ok", "Ready"))
    patch_check(
        "_check_background_scheduler_ready",
        CheckResult("Background scheduler", "ok", "Ready"),
    )
    patch_check(
        "_check_frontend_readiness",
        CheckResult("Frontend readiness", "ok", "Ready"),
    )
    monkeypatch.setattr("grandpa.cli.doctor_cmd._check_background_tasks", lambda: [])

    sections = _build_doctor_dashboard()

    assert [section.name for section in sections] == [
        "Core Runtime",
        "AI Engines",
        "Daily Use Features",
        "System Integration",
    ]
    all_names = {check.name for section in sections for check in section.checks}
    assert "REST API server installed" in all_names
    assert "Windows app resolver ready" in all_names
    assert "Docker command available" in all_names


def test_readiness_label() -> None:
    assert _readiness_label([CheckResult("a", "ok", "Ready")]) == "DAILY USE READY"
    assert _readiness_label([CheckResult("a", "warn", "Missing/optional")]) == "PARTIALLY READY"
    assert _readiness_label([CheckResult("a", "fail", "Failed")]) == "NEEDS SETUP"
