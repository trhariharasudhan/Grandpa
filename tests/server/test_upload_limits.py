"""Resource-limit tests for document upload routes."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.server.upload_router import (
    _MAX_PASTE_CHARS,
    _MAX_UPLOAD_BYTES,
    _MAX_UPLOAD_FILES,
    router,
)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rejects_oversized_paste_before_ingestion() -> None:
    response = _client().post(
        "/v1/connectors/upload/ingest",
        json={"content": "x" * (_MAX_PASTE_CHARS + 1)},
    )
    assert response.status_code == 422


def test_rejects_oversized_file_before_parsing() -> None:
    response = _client().post(
        "/v1/connectors/upload/ingest/files",
        files={"files": ("large.txt", b"x" * (_MAX_UPLOAD_BYTES + 1), "text/plain")},
    )
    assert response.status_code == 413


def test_rejects_too_many_files() -> None:
    files = [
        ("files", (f"{index}.txt", b"x", "text/plain"))
        for index in range(_MAX_UPLOAD_FILES + 1)
    ]
    response = _client().post("/v1/connectors/upload/ingest/files", files=files)
    assert response.status_code == 413
