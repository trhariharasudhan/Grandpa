"""Single point of contact between Python and the Rust ``grandpa_rust`` module.

Every Python module that wants to delegate to Rust should import helpers from
here rather than importing ``grandpa_rust`` directly.

The Rust backend is **optional**.  ``grandpa_rust`` is a compiled PyO3
extension that is not built by the default install and is not shipped in the
wheel (the build backend is hatchling, which produces a pure-Python
distribution).  Python is the authoritative implementation for everything;
callers that consult Rust must degrade to their Python path when it is absent,
and must not change observable behaviour depending on which one ran.

This module previously documented the opposite — that Rust was mandatory with
no Python fallback — while every one of its callers wrapped the call in
``try/except`` and fell back.  ``RUST_AVAILABLE`` was likewise hardcoded to
``True``.  Both statements were false on every machine the project has run on.
"""

from __future__ import annotations

import functools
import importlib.util
import json
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    import types as _types

# ---------------------------------------------------------------------------
# Optional import — the Rust backend may legitimately be absent
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def get_rust_module() -> _types.ModuleType:
    """Return the ``grandpa_rust`` module.

    Raises ``ImportError`` if the compiled extension is not available, which is
    the normal case for a default install.  Callers must handle that and use
    their Python implementation.
    """
    import grandpa_rust  # type: ignore[import-untyped]

    return grandpa_rust


def rust_available() -> bool:
    """Return whether the compiled ``grandpa_rust`` extension can be imported.

    Uses ``find_spec`` so the extension is not actually loaded as a side effect
    of asking.
    """
    return importlib.util.find_spec("grandpa_rust") is not None


#: Whether the compiled extension is present.  Resolved at import time from the
#: real interpreter state rather than asserted.
RUST_AVAILABLE: bool = rust_available()


# ---------------------------------------------------------------------------
# JSON -> Python dataclass converters
# ---------------------------------------------------------------------------


def scan_result_from_json(json_str: str) -> object:
    """Convert a Rust scanner JSON string to a Python ``ScanResult``."""
    from grandpa.security.types import (
        ScanFinding,
        ScanResult,
        ThreatLevel,
    )

    data = json.loads(json_str)
    findings: List[ScanFinding] = []
    for f in data.get("findings", []):
        findings.append(
            ScanFinding(
                pattern_name=f.get("pattern_name", ""),
                matched_text=f.get("matched_text", ""),
                threat_level=ThreatLevel(
                    f.get("threat_level", "low").lower(),
                ),
                start=f.get("start", 0),
                end=f.get("end", 0),
                description=f.get("description", ""),
            )
        )
    return ScanResult(findings=findings)


def injection_result_from_json(json_str: str) -> object:
    """Convert Rust ``InjectionScanner.scan()`` JSON to dataclass."""
    from grandpa.security.injection_scanner import (
        InjectionScanResult,
    )
    from grandpa.security.types import ScanFinding, ThreatLevel

    data = json.loads(json_str)
    findings: List[ScanFinding] = []
    for f in data.get("findings", []):
        findings.append(
            ScanFinding(
                pattern_name=f.get("pattern_name", ""),
                matched_text=f.get("matched_text", ""),
                threat_level=ThreatLevel(
                    f.get("threat_level", "low").lower(),
                ),
                start=f.get("start", 0),
                end=f.get("end", 0),
                description=f.get("description", ""),
            )
        )

    threat_raw = data.get("threat_level", "low").lower()
    try:
        threat = ThreatLevel(threat_raw)
    except ValueError:
        threat = ThreatLevel.LOW

    return InjectionScanResult(
        is_clean=data.get("is_clean", True),
        findings=findings,
        threat_level=threat,
    )


def retrieval_results_from_json(json_str: str) -> list:
    """Convert Rust memory ``retrieve()`` JSON to a list of results."""
    from grandpa.tools.storage._stubs import RetrievalResult

    items = json.loads(json_str)
    results: List[RetrievalResult] = []
    for item in items:
        meta = item.get("metadata", {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        results.append(
            RetrievalResult(
                content=item.get("content", ""),
                score=float(item.get("score", 0.0)),
                source=item.get("source", ""),
                metadata=meta,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Phase 2 converters — optimization & engine types
# ---------------------------------------------------------------------------


def optimization_store_from_rust(path: str = ":memory:") -> object | None:
    """Get a Rust-backed OptimizationStore, or None if Rust unavailable."""
    mod = get_rust_module()
    if mod is None:
        return None
    try:
        return mod.OptimizationStore(path)
    except Exception:
        return None


def trial_result_from_json(json_str: str) -> dict:
    """Convert Rust TrialResult JSON to a Python dict."""
    return json.loads(json_str)


def optimization_run_from_json(json_str: str) -> dict:
    """Convert Rust OptimizationRun JSON to a Python dict."""
    return json.loads(json_str)


def generate_result_from_json(json_str: str) -> dict:
    """Convert Rust GenerateResult JSON to a Python dict."""
    data = json.loads(json_str)
    return {
        "content": data.get("content", ""),
        "model": data.get("model", ""),
        "finish_reason": data.get("finish_reason", "stop"),
        "usage": data.get("usage", {}),
        "tool_calls": data.get("tool_calls"),
        "ttft": data.get("ttft", 0.0),
        "cost_usd": data.get("cost_usd", 0.0),
        "metadata": data.get("metadata", {}),
    }


__all__ = [
    "RUST_AVAILABLE",
    "generate_result_from_json",
    "get_rust_module",
    "injection_result_from_json",
    "optimization_run_from_json",
    "optimization_store_from_rust",
    "retrieval_results_from_json",
    "rust_available",
    "scan_result_from_json",
    "trial_result_from_json",
]
