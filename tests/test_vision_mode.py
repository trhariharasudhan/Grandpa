from __future__ import annotations

from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from grandpa.server.api_routes import vision_router
from grandpa.vision.analyzer import PLACEHOLDER_ANALYSIS
from grandpa.vision.session import VisionSession

pytestmark = pytest.mark.core


@pytest.fixture
def vision_client() -> TestClient:
    app = FastAPI()
    app.include_router(vision_router)
    return TestClient(app)


def _image_bytes(image_format: str = "PNG") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 3), color=(10, 20, 30)).save(buffer, format=image_format)
    return buffer.getvalue()


def test_vision_session_default_disabled() -> None:
    session = VisionSession()

    status = session.status()

    assert status["enabled"] is False
    assert status["last_image_name"] is None
    assert status["live_capture"] is False
    assert status["screen_capture_enabled"] is False
    assert status["webcam_enabled"] is False


def test_vision_enable_disable(vision_client: TestClient) -> None:
    enabled = vision_client.post("/v1/vision/enable")
    disabled = vision_client.post("/v1/vision/disable")

    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False


def test_analyze_png_reads_dimensions(vision_client: TestClient) -> None:
    response = vision_client.post(
        "/v1/vision/analyze",
        files={"image": ("sample.png", _image_bytes(), "image/png")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload == {
        "success": True,
        "filename": "sample.png",
        "width": 2,
        "height": 3,
        "format": "png",
        "analysis": PLACEHOLDER_ANALYSIS,
        "error": None,
    }


def test_rejects_unsupported_image_type(vision_client: TestClient) -> None:
    response = vision_client.post(
        "/v1/vision/analyze",
        files={"image": ("note.txt", b"hello", "text/plain")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["error"] == "Unsupported image type. Upload a PNG, JPG, JPEG, or WEBP image."


def test_rejects_empty_image(vision_client: TestClient) -> None:
    response = vision_client.post(
        "/v1/vision/analyze",
        files={"image": ("empty.png", b"", "image/png")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["error"] == "Empty image file."


def test_rejects_invalid_image(vision_client: TestClient) -> None:
    response = vision_client.post(
        "/v1/vision/analyze",
        files={"image": ("broken.png", b"not an image", "image/png")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["error"] == "Invalid image file."


def test_status_shows_last_image_metadata(vision_client: TestClient) -> None:
    vision_client.post(
        "/v1/vision/analyze",
        files={"image": ("sample.png", _image_bytes(), "image/png")},
    )

    status = vision_client.get("/v1/vision/status").json()

    assert status["last_image_name"] == "sample.png"
    assert status["last_image_size"] == {"bytes": len(_image_bytes()), "width": 2, "height": 3}
    assert status["last_format"] == "png"
    assert status["last_analysis"] == PLACEHOLDER_ANALYSIS
    assert status["last_error"] is None
    assert "ocr" in status
    assert isinstance(status["ocr"]["available"], bool)
    assert status["live_capture"] is False
    assert status["screen_capture_enabled"] is False
    assert status["webcam_enabled"] is False


def test_no_real_vision_model_or_live_capture_is_used() -> None:
    session = VisionSession()

    result = session.analyze_image_bytes(_image_bytes("WEBP"), "sample.webp", "image/webp")
    status = session.status()

    assert result["analysis"] == PLACEHOLDER_ANALYSIS
    assert result["success"] is True
    assert result["format"] == "webp"
    assert status["live_capture"] is False
    assert status["screen_capture_enabled"] is False
    assert status["webcam_enabled"] is False


def test_ocr_endpoint_with_valid_image_and_mocked_ocr(vision_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import grandpa.vision.ocr as ocr

    monkeypatch.setattr(ocr.util, "find_spec", lambda name: object() if name == "pytesseract" else None)

    class FakeTesseract:
        @staticmethod
        def image_to_string(_image: object) -> str:
            return "Hello from image"

    monkeypatch.setattr(ocr, "_load_pytesseract", lambda: FakeTesseract)

    response = vision_client.post(
        "/v1/vision/ocr",
        files={"image": ("text.png", _image_bytes(), "image/png")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["filename"] == "text.png"
    assert payload["mime_type"] == "image/png"
    assert payload["width"] == 2
    assert payload["height"] == 3
    assert payload["ocr"] == {
        "available": True,
        "text": "Hello from image",
        "engine": "pytesseract",
        "error": None,
    }


def test_ocr_unavailable_path(vision_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import grandpa.vision.ocr as ocr

    monkeypatch.setattr(ocr.util, "find_spec", lambda _name: None)

    response = vision_client.post(
        "/v1/vision/ocr",
        files={"image": ("text.png", _image_bytes(), "image/png")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["ocr"]["available"] is False
    assert payload["ocr"]["engine"] == "none"
    assert payload["ocr"]["text"] == "OCR is not available. Install OCR dependencies to extract text."


def test_ocr_rejects_invalid_image(vision_client: TestClient) -> None:
    response = vision_client.post(
        "/v1/vision/ocr",
        files={"image": ("broken.png", b"not an image", "image/png")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["ocr"]["available"] is False
    assert payload["ocr"]["error"] == "Invalid image file."


def test_ocr_rejects_empty_upload(vision_client: TestClient) -> None:
    response = vision_client.post(
        "/v1/vision/ocr",
        files={"image": ("empty.png", b"", "image/png")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["ocr"]["available"] is False
    assert payload["ocr"]["error"] == "Empty image file."
