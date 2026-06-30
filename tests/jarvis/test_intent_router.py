from pathlib import Path

from grandpa.jarvis.context_resolver import SafeContextResolver
from grandpa.jarvis.intent_router import route_jarvis_command


def _resolver_with_project(tmp_path: Path) -> SafeContextResolver:
    project = tmp_path / "Grandpa"
    project.mkdir()
    (project / ".git").mkdir()
    return SafeContextResolver([tmp_path])


def test_vs_code_project_open_intent(tmp_path: Path) -> None:
    result = route_jarvis_command(
        "open my Grandpa project in VS Code",
        resolver=_resolver_with_project(tmp_path),
        dry_run=True,
    )

    assert result.status == "routed"
    assert result.payload is not None
    assert result.payload["action_type"] == "open_app"
    assert result.payload["target"] == "vscode"
    assert result.payload["dry_run"] is True
    assert result.payload["args"]["project_path"].endswith("Grandpa")
    assert result.confidence >= 0.9


def test_visual_studio_code_project_open_intent(tmp_path: Path) -> None:
    result = route_jarvis_command(
        "open my Grandpa project in visual studio code",
        resolver=_resolver_with_project(tmp_path),
        dry_run=True,
    )

    assert result.status == "routed"
    assert result.payload is not None
    assert result.payload["target"] == "vscode"
    assert result.payload["args"]["project_path"].endswith("Grandpa")


def test_noisy_stt_project_open_intent(tmp_path: Path) -> None:
    result = route_jarvis_command(
        "Open my projecting this will be your goal",
        resolver=_resolver_with_project(tmp_path),
        dry_run=True,
    )

    assert result.status == "routed"
    assert result.payload is not None
    assert result.payload["target"] == "vscode"
    assert result.payload["args"]["project_path"].endswith("Grandpa")
    assert 0.55 <= result.confidence < 0.95


def test_unknown_command_handling(tmp_path: Path) -> None:
    result = route_jarvis_command(
        "make me coffee",
        resolver=SafeContextResolver([tmp_path]),
    )

    assert result.status == "unsupported"
    assert result.payload is None
    assert result.confidence == 0.0


def test_shell_like_command_is_blocked(tmp_path: Path) -> None:
    result = route_jarvis_command(
        "run command dir",
        resolver=SafeContextResolver([tmp_path]),
    )

    assert result.status == "blocked"
    assert result.payload is None
