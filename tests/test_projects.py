"""Project Launcher and Developer Workflow Manager tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from grandpa.projects.commands import handle_project_command
from grandpa.projects.discovery import discover_projects
from grandpa.projects.errors import (
    AmbiguousProjectError,
    InvalidProjectPathError,
    ProjectAlreadyRegisteredError,
    ProjectCommandTimeoutError,
    ProjectNotFoundError,
    UnsafeProjectCommandError,
)
from grandpa.projects.models import Project, ProjectCommand
from grandpa.projects.process_manager import ProjectProcess, ProjectProcessStore
from grandpa.projects.registry import ProjectRegistry
from grandpa.projects.resolver import resolve_project
from grandpa.projects.runner import ProjectRunner, redact_secrets
from grandpa.projects.service import ProjectService
from grandpa.voice.assistant import VoiceCommandProcessor


def _project(
    root: Path, *, project_id: str = "sample", name: str = "Sample"
) -> Project:
    return Project(
        id=project_id,
        name=name,
        root_path=str(root),
        aliases=(name.casefold(),),
        project_type="python",
        commands={
            "test": ProjectCommand(("python", "-m", "pytest", "-q"), timeout_seconds=10)
        },
        test_profiles={
            "voice": ProjectCommand(("python", "-m", "pytest", "tests/voice", "-q"))
        },
    )


def test_register_python_project_and_versioned_schema(tmp_path: Path) -> None:
    root = tmp_path / "Example"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='example'\n")
    store = tmp_path / "projects.json"

    project = ProjectRegistry(store).register(root, name="Example")

    assert project.project_type == "python"
    payload = json.loads(store.read_text())
    assert payload["schema_version"] == 1
    assert payload["projects"][0]["root_path"] == str(root.resolve())


def test_registration_suggests_only_detected_python_workflows(tmp_path: Path) -> None:
    root = tmp_path / "Example"
    (root / "tests").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[tool.ruff]\n")
    project = ProjectRegistry(tmp_path / "projects.json").register(root)
    assert sorted(project.commands) == ["lint", "test"]


def test_registry_never_persists_environment_values(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = Project(
        "sample",
        "Sample",
        str(root),
        environment={"API_TOKEN": "do-not-write-this"},
    )
    store = tmp_path / "projects.json"
    ProjectRegistry(store).save([project])
    content = store.read_text()
    assert "do-not-write-this" not in content
    assert "API_TOKEN" in content


def test_register_rejects_missing_and_duplicate_paths(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "projects.json")
    with pytest.raises(InvalidProjectPathError):
        registry.register(tmp_path / "missing")
    root = tmp_path / "project"
    root.mkdir()
    registry.register(root)
    with pytest.raises(ProjectAlreadyRegisteredError):
        registry.register(root)


def test_discovery_is_bounded_and_ignores_dependencies(tmp_path: Path) -> None:
    valid = tmp_path / "work" / "app"
    ignored = tmp_path / "node_modules" / "dependency"
    too_deep = tmp_path / "one" / "two" / "three"
    for path in (valid, ignored, too_deep):
        path.mkdir(parents=True)
        (path / "pyproject.toml").write_text("")

    found = discover_projects(tmp_path, max_depth=2)

    assert [Path(item.path) for item in found] == [valid]


def test_resolver_exact_alias_and_ambiguous(tmp_path: Path) -> None:
    alpha = _project(tmp_path / "alpha", project_id="alpha", name="MotoCompass")
    beta = _project(tmp_path / "beta", project_id="beta", name="MotoMate")
    grandpa = Project(
        **{
            **_project(tmp_path / "grandpa").__dict__,
            "id": "grandpa",
            "name": "Grandpa",
            "aliases": ("local assistant",),
        }
    )
    assert resolve_project("grandpa", [grandpa]).id == "grandpa"
    assert resolve_project("local assistant", [grandpa]).id == "grandpa"
    with pytest.raises(AmbiguousProjectError):
        resolve_project("moto", [alpha, beta])


def test_runner_uses_project_cwd_shell_false_and_logs_output(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = _project(root)
    completed = subprocess.CompletedProcess([], 0, "12 passed in 1.2s\n", "")
    with patch("grandpa.projects.runner.subprocess.run", return_value=completed) as run:
        result = ProjectRunner(log_dir=tmp_path / "logs").run(
            project, "test", project.commands["test"]
        )

    assert result.status == "completed"
    assert "12 passed" in result.message
    assert Path(result.log_path).read_text() == "12 passed in 1.2s\n"
    assert run.call_args.kwargs["cwd"] == str(root.resolve())
    assert run.call_args.kwargs["shell"] is False


def test_runner_rejects_shell_and_reports_timeout(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runner = ProjectRunner(log_dir=tmp_path / "logs")
    with pytest.raises(UnsafeProjectCommandError):
        runner.run(
            _project(root),
            "bad",
            ProjectCommand(("powershell", "-Command", "echo bad")),
        )
    with (
        patch(
            "grandpa.projects.runner.subprocess.run",
            side_effect=subprocess.TimeoutExpired("pytest", 1),
        ),
        pytest.raises(ProjectCommandTimeoutError),
    ):
        runner.run(
            _project(root),
            "test",
            ProjectCommand(("python", "-m", "pytest"), timeout_seconds=1),
        )


def test_runner_tracks_long_running_process_and_handles_cancellation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    process_store = Mock(spec=ProjectProcessStore)
    runner = ProjectRunner(log_dir=tmp_path / "logs", process_store=process_store)
    process = SimpleNamespace(pid=321)
    with patch(
        "grandpa.projects.runner.subprocess.Popen", return_value=process
    ) as popen:
        result = runner.run(
            _project(root),
            "start",
            ProjectCommand(("python", "server.py"), long_running=True),
        )
    assert result.pid == 321
    assert popen.call_args.kwargs["shell"] is False
    process_store.put.assert_called_once()

    with patch("grandpa.projects.runner.subprocess.run", side_effect=KeyboardInterrupt):
        cancelled = runner.run(_project(root), "test", _project(root).commands["test"])
    assert cancelled.status == "cancelled"


def test_general_status_and_stop_use_registered_workflows(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    project = Project(
        **{
            **_project(root).__dict__,
            "commands": {
                "status": ProjectCommand(("python", "status.py")),
                "stop": ProjectCommand(
                    ("python", "stop.py"), requires_confirmation=True
                ),
            },
        }
    )
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.save([project])
    runner = SimpleNamespace(
        process_store=Mock(spec=ProjectProcessStore),
        run=Mock(return_value=SimpleNamespace(status="completed", message="Done.")),
    )
    runner.process_store.get_owned.return_value = None
    service = ProjectService(registry=registry, runner=runner)
    assert service.status("sample").message == "Done."
    assert service.lifecycle("sample", "stop").message == "Done."
    assert [call.args[1] for call in runner.run.call_args_list] == ["status", "stop"]


def test_process_store_removes_stale_or_wrong_owner(tmp_path: Path) -> None:
    store = ProjectProcessStore(tmp_path / "processes.json")
    state = ProjectProcess(
        "sample",
        123,
        ("python", "server.py"),
        str(tmp_path),
        "now",
        "log",
        "python.exe",
    )
    store.put(state)
    with patch("grandpa.projects.process_manager.process_matches", return_value=False):
        assert store.get_owned("sample") is None
    assert "sample" not in store.load()


def test_open_project_routes_through_pc_control(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.save([_project(root)])
    service = ProjectService(registry=registry)
    response = SimpleNamespace(ok=True, message="Opening VS Code.")
    with patch("grandpa.pc_control.run_local_action", return_value=response) as run:
        message = service.open("sample")
    request = run.call_args.args[0]
    assert request.action_type == "open_app"
    assert request.args["project_path"] == str(root)
    assert "Visual Studio Code" in message


def test_logs_are_limited_and_secrets_redacted(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    log = root / "server.log"
    log.write_text("first\nAuthorization: secret-token\nlast\n")
    project = Project(**{**_project(root).__dict__, "log_paths": (str(log),)})
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.save([project])
    content, path = ProjectService(registry=registry).logs("sample", tail=2)
    assert "first" not in content
    assert "secret-token" not in content
    assert "[REDACTED]" in content
    assert path == str(log)
    assert "secret" not in redact_secrets("api_key=secret")
    assert "123456" not in redact_secrets("OTP: 123456")
    assert "4111111111111111" not in redact_secrets("4111111111111111")


def test_project_intents_and_app_command_non_collision(tmp_path: Path) -> None:
    service = Mock(spec=ProjectService)
    service.projects.return_value = [_project(tmp_path)]
    service.resolve.side_effect = lambda query: (
        _project(tmp_path)
        if query.casefold() == "sample"
        else (_ for _ in ()).throw(ProjectNotFoundError(query))
    )
    service.open.return_value = "Opening Sample in Visual Studio Code."
    service.status.return_value = SimpleNamespace(
        message="Sample is running.", status="running"
    )
    service.run_workflow.return_value = SimpleNamespace(
        message="Sample test passed.", status="completed"
    )
    service.current_project.return_value = _project(tmp_path)

    assert (
        handle_project_command("List my projects", service=service).status == "handled"
    )
    assert (
        handle_project_command("Open Sample project", service=service).action == "open"
    )
    assert (
        handle_project_command("Check Sample server status", service=service).action
        == "status"
    )
    assert (
        handle_project_command("Run Sample voice tests", service=service).action
        == "test"
    )
    assert (
        handle_project_command(
            "Run only voice tests for Sample", service=service
        ).action
        == "test"
    )
    assert (
        handle_project_command("Run only the app manager tests", service=service).action
        == "test"
    )
    assert handle_project_command("Open Chrome", service=service).should_fallback
    assert (
        handle_project_command("Stop Sample server", service=service).status
        == "needs_confirmation"
    )


def test_chat_and_voice_share_project_intent_handler() -> None:
    local_result = SimpleNamespace(
        should_fallback=False,
        message="Registered projects:\n- Grandpa",
        status="handled",
    )
    with patch(
        "grandpa.projects.handle_project_command", return_value=local_result
    ) as handler:
        from grandpa.cli.chat_cmd import _handle_natural_assistant_intent

        assert "Grandpa" in (_handle_natural_assistant_intent("List my projects") or "")
        response = VoiceCommandProcessor()._handle_local_pipeline("List my projects")
    assert response is not None
    assert response.text == "Registered projects:\n- Grandpa"
    assert handler.call_count == 2
