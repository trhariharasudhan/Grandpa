from __future__ import annotations

from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from grandpa.server.api_routes import vision_router
from grandpa.vision.analyzer import PLACEHOLDER_ANALYSIS
from grandpa.vision.screenshot import ScreenshotSession
from grandpa.vision.session import VisionSession

pytestmark = pytest.mark.core


def _mock_local_model_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import grandpa.vision.screenshot as screenshot_session
    import grandpa.vision.session as vision_session

    unavailable_result = {
        "available": False,
        "model": None,
        "analysis": "",
        "error": "Ollama is not available. Start it with: ollama serve",
    }
    unavailable_status = {
        "available": False,
        "configured_model": None,
        "fallback_models": ["grandpa-eyes", "llava:latest"],
        "engine": "ollama",
    }

    monkeypatch.setattr(vision_session, "analyze_image_with_local_model", lambda *_args, **_kwargs: unavailable_result)
    monkeypatch.setattr(vision_session, "local_model_status", lambda: unavailable_status)
    monkeypatch.setattr(
        screenshot_session,
        "analyze_image_with_local_model",
        lambda *_args, **_kwargs: {
            "available": False,
            "model": None,
            "analysis": "",
            "error": "Ollama is not available. Start it with: ollama serve",
        },
    )
    monkeypatch.setattr(screenshot_session, "local_model_status", lambda: unavailable_status)


@pytest.fixture
def vision_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _mock_local_model_unavailable(monkeypatch)
    app = FastAPI()
    app.include_router(vision_router)
    return TestClient(app)


def _image_bytes(image_format: str = "PNG") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 3), color=(10, 20, 30)).save(buffer, format=image_format)
    return buffer.getvalue()


def test_vision_session_default_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_local_model_unavailable(monkeypatch)
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
        "model_analysis": {
            "available": False,
            "model": None,
            "analysis": "",
            "error": "Ollama is not available. Start it with: ollama serve",
        },
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
    assert status["local_model"] == {
        "available": False,
        "configured_model": None,
        "fallback_models": ["grandpa-eyes", "llava:latest"],
        "engine": "ollama",
    }
    assert status["live_capture"] is False
    assert status["screen_capture_enabled"] is False
    assert status["webcam_enabled"] is False


def test_no_real_vision_model_or_live_capture_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_local_model_unavailable(monkeypatch)
    session = VisionSession()

    result = session.analyze_image_bytes(_image_bytes("WEBP"), "sample.webp", "image/webp")
    status = session.status()

    assert result["analysis"] == PLACEHOLDER_ANALYSIS
    assert result["success"] is True
    assert result["format"] == "webp"
    assert "model_analysis" in result
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


def test_model_analysis_success_with_mocked_ollama(vision_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import grandpa.vision.session as vision_session

    captured = {}

    def fake_model(data: bytes, filename: str, mime_type: str, prompt: str):
        captured["prompt"] = prompt
        captured["filename"] = filename
        captured["mime_type"] = mime_type
        assert data
        return {
            "available": True,
            "model": "grandpa-eyes",
            "analysis": "A small test image.",
            "error": None,
        }

    monkeypatch.setattr(vision_session, "analyze_image_with_local_model", fake_model)

    response = vision_client.post(
        "/v1/vision/analyze",
        data={"prompt": "What is visible?"},
        files={"image": ("sample.png", _image_bytes(), "image/png")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["model_analysis"] == {
        "available": True,
        "model": "grandpa-eyes",
        "analysis": "A small test image.",
        "error": None,
    }
    assert captured == {
        "prompt": "What is visible?",
        "filename": "sample.png",
        "mime_type": "image/png",
    }


def test_model_analysis_uses_default_prompt(vision_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import grandpa.vision.session as vision_session
    from grandpa.vision.local_model import DEFAULT_VISION_PROMPT

    captured = {}

    def fake_model(_data: bytes, _filename: str, _mime_type: str, prompt: str | None):
        captured["prompt"] = prompt
        return {"available": False, "model": None, "analysis": "", "error": None}

    monkeypatch.setattr(vision_session, "analyze_image_with_local_model", fake_model)

    response = vision_client.post(
        "/v1/vision/analyze",
        files={"image": ("sample.png", _image_bytes(), "image/png")},
    )

    assert response.status_code == 200
    assert captured["prompt"] == DEFAULT_VISION_PROMPT
    assert response.json()["model_analysis"]["error"] is None
    assert DEFAULT_VISION_PROMPT == "Describe this image clearly and mention any visible text."


def test_local_model_ollama_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    import grandpa.vision.local_model as local_model

    class UnavailableClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(local_model.httpx, "Client", UnavailableClient)

    result = local_model.analyze_image_with_local_model(_image_bytes(), "sample.png", "image/png", None)

    assert result == {
        "available": False,
        "model": None,
        "analysis": "",
        "error": "Ollama is not available. Start it with: ollama serve",
    }


def test_local_model_missing_model_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    import grandpa.vision.local_model as local_model

    class FakeResponse:
        status_code = 200
        text = ""

        def __init__(self, payload: dict):
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class MissingModelClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            return FakeResponse({"models": [{"name": "qwen3:8b"}]})

    monkeypatch.setattr(local_model.httpx, "Client", MissingModelClient)
    monkeypatch.delenv("GRANDPA_VISION_MODEL", raising=False)
    monkeypatch.delenv("GRANDPA_EYES_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_VISION_MODEL", raising=False)

    result = local_model.analyze_image_with_local_model(_image_bytes(), "sample.png", "image/png", None)

    assert result == {
        "available": False,
        "model": "grandpa-eyes",
        "analysis": "",
        "error": "Vision model is not installed. Run: ollama pull grandpa-eyes",
    }


def test_screenshot_status_default(vision_client: TestClient) -> None:
    response = vision_client.get("/v1/vision/screenshot/status")

    payload = response.json()
    assert response.status_code == 200
    assert payload["enabled"] is False
    assert payload["last_capture_name"] is None
    assert payload["desktop_capture"] is False
    assert payload["live_capture"] is False
    assert payload["local_model"] == {
        "available": False,
        "configured_model": None,
        "fallback_models": ["grandpa-eyes", "llava:latest"],
        "engine": "ollama",
    }


def test_screenshot_enable_disable(vision_client: TestClient) -> None:
    enabled = vision_client.post("/v1/vision/screenshot/enable")
    disabled = vision_client.post("/v1/vision/screenshot/disable")

    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False


def test_screenshot_ingest_valid_image_reuses_ocr_and_model(
    vision_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import grandpa.vision.screenshot as screenshot

    captured = {}

    def fake_ocr(data: bytes, mime_type: str):
        captured["ocr_mime"] = mime_type
        assert data
        return {
            "available": True,
            "text": "Screenshot text",
            "engine": "mock-ocr",
            "error": None,
        }

    def fake_model(data: bytes, filename: str, mime_type: str, prompt: str):
        captured["model"] = {
            "filename": filename,
            "mime_type": mime_type,
            "prompt": prompt,
        }
        assert data
        return {
            "available": True,
            "model": "grandpa-eyes",
            "analysis": "A screenshot with text.",
            "error": None,
        }

    monkeypatch.setattr(screenshot, "extract_text_from_image_bytes", fake_ocr)
    monkeypatch.setattr(screenshot, "analyze_image_with_local_model", fake_model)

    response = vision_client.post(
        "/v1/vision/screenshot/ingest",
        data={"prompt": "Read the screen."},
        files={"image": ("screen.png", _image_bytes(), "image/png")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload == {
        "ok": True,
        "filename": "screen.png",
        "mime_type": "image/png",
        "width": 2,
        "height": 3,
        "analysis": PLACEHOLDER_ANALYSIS,
        "error": None,
        "ocr": {
            "available": True,
            "text": "Screenshot text",
            "engine": "mock-ocr",
            "error": None,
        },
        "model_analysis": {
            "available": True,
            "model": "grandpa-eyes",
            "analysis": "A screenshot with text.",
            "error": None,
        },
    }
    assert captured == {
        "ocr_mime": "image/png",
        "model": {
            "filename": "screen.png",
            "mime_type": "image/png",
            "prompt": "Read the screen.",
        },
    }
    status = vision_client.get("/v1/vision/screenshot/status").json()
    assert status["last_capture_name"] == "screen.png"
    assert status["last_capture_size"] == {"bytes": len(_image_bytes()), "width": 2, "height": 3}
    assert status["last_capture_at"]


def test_screenshot_ingest_invalid_file(vision_client: TestClient) -> None:
    response = vision_client.post(
        "/v1/vision/screenshot/ingest",
        files={"image": ("broken.png", b"not an image", "image/png")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error"] == "Invalid image file."
    assert payload["ocr"]["error"] == "Invalid image file."
    assert payload["model_analysis"]["error"] == "Invalid image file."


def test_screenshot_ingest_empty_file(vision_client: TestClient) -> None:
    response = vision_client.post(
        "/v1/vision/screenshot/ingest",
        files={"image": ("empty.png", b"", "image/png")},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error"] == "Empty image file."


def test_screenshot_session_has_no_desktop_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_local_model_unavailable(monkeypatch)
    session = ScreenshotSession()

    result = session.ingest_screenshot_bytes(_image_bytes("WEBP"), "screen.webp", "image/webp")
    status = session.status()

    assert result["ok"] is True
    assert result["analysis"] == PLACEHOLDER_ANALYSIS
    assert status["desktop_capture"] is False
    assert status["live_capture"] is False
