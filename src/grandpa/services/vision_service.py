"""Service facade for screen and visual diagnostics."""

from __future__ import annotations

from typing import Any

from grandpa.services.base import safe_call


def diagnostics() -> dict[str, Any]:
    from grandpa.screen_awareness import screen_diagnostics

    screen = screen_diagnostics()
    visual: dict[str, Any]
    try:
        from grandpa.visual_targeting import visual_diagnostics

        visual = visual_diagnostics()
    except Exception as exc:
        visual = {
            "status": "unsupported",
            "ready": False,
            "opencv_available": False,
            "error": exc.__class__.__name__,
            "message": "Visual targeting diagnostics are unavailable.",
        }
    return {"status": "ready", "screen": screen, "visual": visual, "local_only": True}


def health() -> dict[str, Any]:
    payload = safe_call("vision", diagnostics)
    screen = (
        payload.get("screen", {}) if isinstance(payload.get("screen"), dict) else {}
    )
    visual = (
        payload.get("visual", {}) if isinstance(payload.get("visual"), dict) else {}
    )
    return {
        "name": "vision",
        "ready": bool(screen) or bool(visual.get("opencv_available")),
        "status": payload.get("status", "partial"),
        "dependencies": {
            "screen_awareness": bool(screen),
            "opencv": bool(visual.get("opencv_available")),
            "ocr": screen.get("ocr", {}).get("available")
            if isinstance(screen.get("ocr"), dict)
            else None,
        },
    }


def readiness() -> dict[str, Any]:
    payload = safe_call("vision", diagnostics)
    return {"ready": health()["ready"], "diagnostics": payload}
