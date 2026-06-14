from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _engine() -> MagicMock:
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    return engine


def test_server_imports_without_optional_research_dependencies() -> None:
    from grandpa.server.app import create_app

    app = create_app(_engine(), "test-model")
    assert app.title == "Grandpa API"


def test_research_route_reports_missing_optional_dependency_cleanly() -> None:
    from grandpa.server.app import create_app

    client = TestClient(create_app(_engine(), "test-model"))
    response = client.post("/api/research", json={"query": "test"})

    if response.status_code != 503:
        pytest.skip("Research dependencies are installed in this environment.")
    payload = response.json()
    assert payload["error"] == "research_unavailable"
    assert "optional dependency" in payload["message"]
    assert "Traceback" not in response.text
    assert payload["install"] == "uv sync --extra memory-faiss"
