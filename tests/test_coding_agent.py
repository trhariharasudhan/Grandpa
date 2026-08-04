from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.coding.architecture_analysis import analyze_architecture
from grandpa.coding.dependency_analysis import analyze_dependencies
from grandpa.coding.diagnostics import coding_diagnostics
from grandpa.coding.project_scanner import detect_project, scan_projects
from grandpa.coding.repository_analysis import analyze_repository
from grandpa.server.api_routes import coding_router
from grandpa.skills.registry import (
    ensure_default_skills_registered,
    execute_skill,
    get_skill,
)


def test_project_scanner_detects_common_project_types(tmp_path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    (project / ".git").mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["fastapi"]\n', encoding="utf-8"
    )
    (project / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^19.0.0"}}), encoding="utf-8"
    )
    (project / "Cargo.toml").write_text(
        "[package]\nname='demo'\nversion='0.1.0'\n[dependencies]\nserde='1'\n",
        encoding="utf-8",
    )
    detected = detect_project(project)

    assert detected["is_project"] is True
    assert {"git", "python", "node", "rust"}.issubset(set(detected["types"]))


def test_scan_projects_is_read_only(tmp_path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    result = scan_projects(tmp_path)

    assert result["count"] == 1
    assert result["read_only"] is True


def test_dependency_analysis_reads_manifests(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["fastapi", "pydantic"]\n',
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"eslint": "^9.0.0"}}), encoding="utf-8"
    )

    result = analyze_dependencies(tmp_path)

    assert result["manifest_count"] == 2
    assert result["dependency_count"] == 3
    assert {item["ecosystem"] for item in result["manifests"]} == {"python", "node"}


def test_repository_analysis_counts_modules_and_tests(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n', encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text(
        "def test_ok(): assert True\n", encoding="utf-8"
    )

    result = analyze_repository(tmp_path)

    assert result["module_count"] == 2
    assert result["test_count"] == 1
    assert result["read_only"] is True


def test_architecture_analysis_detects_layers(tmp_path) -> None:
    (tmp_path / "src" / "grandpa" / "services").mkdir(parents=True)
    (tmp_path / "src" / "grandpa" / "skills").mkdir(parents=True)

    result = analyze_architecture(tmp_path)

    assert "service_layer" in result["present_layers"]
    assert "skill_layer" in result["present_layers"]


def test_coding_diagnostics_contract() -> None:
    result = coding_diagnostics()

    assert result["status"] == "ready"
    assert result["safety"]["read_only"] is True
    assert result["capabilities"]["code_execution"] is False
    assert result["capabilities"]["code_modification"] is False


def test_coding_skills_registered() -> None:
    ensure_default_skills_registered()

    assert get_skill("coding.diagnostics").category == "coding"
    result = execute_skill("coding.dependencies")
    assert result.ok is True
    assert result.risk_level == "LOW"
    assert result.data["read_only"] is True


def test_coding_api_routes() -> None:
    app = FastAPI()
    app.include_router(coding_router)
    client = TestClient(app)

    diagnostics = client.get("/v1/coding/diagnostics")
    assert diagnostics.status_code == 200
    assert diagnostics.json()["status"] == "ready"

    summary = client.get("/v1/coding/project-summary")
    assert summary.status_code == 200
    assert summary.json()["read_only"] is True

    dependencies = client.get("/v1/coding/dependencies")
    assert dependencies.status_code == 200
    assert dependencies.json()["read_only"] is True
