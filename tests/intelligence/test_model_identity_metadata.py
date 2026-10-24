"""Every tag that resolves to a role must describe the model it really loads.

``base_family`` is not decoration. ``prompt.identity.identity_prompt`` states it
to the model as fact ("Underlying foundation family: ..."), and
``intelligence.model_catalog`` publishes it as the catalogue ``family``. So a tag
aliased onto the wrong role turns GRANDPA_IDENTITY_PROMPT's promise to "answer
truthfully" into the thing that produces the falsehood: with
``grandpa-light:latest`` (gemma3, 4.3B) aliased to the Qwen3 ``fast`` role, the
real voice path answered "I'm running on Qwen3, specifically the 'fast' role"
-- faithfully, from a prompt that was wrong.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from grandpa.intelligence.grandpa_models import (
    GRANDPA_MODEL_ROLES,
    get_model_role,
)

_OLLAMA_HOST = "http://localhost:11434"
_TIMEOUT_S = 5.0

# What has to show up in Ollama's own metadata for a declared base_family to be
# believable. Markers rather than an equality check against ``details.family``,
# because that field is the *architecture*: grandpa-coder and grandpa-eyes both
# report "llama" while their parent models are deepseek-coder:6.7b and
# llava:latest. The lineage appears in general.basename or parent_model instead,
# so the check searches all of them.
_FAMILY_MARKERS: dict[str, tuple[str, ...]] = {
    "Qwen2.5": ("qwen2.5",),
    "Qwen3": ("qwen3",),
    "DeepSeek Coder": ("deepseek",),
    "LLaVA": ("llava",),
    "Nomic BERT": ("nomic",),
}

# A tag that names its own family must not resolve to a role of another one.
# This is the half of the check that needs no running Ollama, so it is what
# holds in CI.
_NAME_HINTS: tuple[tuple[str, str], ...] = (
    ("qwen2.5", "Qwen2.5"),
    ("qwen3", "Qwen3"),
    ("gemma", "Gemma"),
    ("llama", "Llama"),
    ("deepseek", "DeepSeek"),
    ("llava", "LLaVA"),
    ("nomic", "Nomic"),
    ("mistral", "Mistral"),
)


def _resolvable_tags() -> list[str]:
    """Every Ollama-queryable string that ``get_model_role`` resolves."""

    tags: list[str] = []
    for entry in GRANDPA_MODEL_ROLES:
        tags.append(entry.ollama_tag)
        tags.extend(entry.legacy_aliases)
    return tags


def _ollama_get(path: str, payload: dict[str, str] | None = None) -> dict | None:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{_OLLAMA_HOST}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None


@pytest.fixture(scope="module")
def installed_models() -> dict[str, dict]:
    """Tag -> /api/show payload, or skip the module when Ollama is not up."""

    listing = _ollama_get("/api/tags")
    if listing is None:
        pytest.skip(f"Ollama not reachable at {_OLLAMA_HOST}")
    present = {str(item.get("name", "")) for item in listing.get("models", [])}
    shown: dict[str, dict] = {}
    for tag in _resolvable_tags():
        if tag not in present and f"{tag}:latest" not in present:
            continue
        payload = _ollama_get("/api/show", {"model": tag})
        if payload is not None:
            shown[tag] = payload
    return shown


def _lineage_haystack(tag: str, payload: dict) -> str:
    details = payload.get("details") or {}
    info = payload.get("model_info") or {}
    parts = (
        tag,
        str(details.get("family", "")),
        str(details.get("parent_model", "")),
        str(info.get("general.architecture", "")),
        str(info.get("general.basename", "")),
        str(info.get("general.finetune", "")),
        str(info.get("general.name", "")),
    )
    return " ".join(parts).casefold()


def _reported_parameters_b(payload: dict) -> float | None:
    raw = str((payload.get("details") or {}).get("parameter_size", "")).strip()
    if not raw:
        return None
    scale = {"B": 1.0, "M": 1e-3, "K": 1e-6}.get(raw[-1].upper())
    if scale is None:
        return None
    try:
        return float(raw[:-1]) * scale
    except ValueError:
        return None


def test_every_declared_family_has_markers() -> None:
    """A new base_family must be taught to this module, so that the live check
    below cannot quietly start passing by knowing nothing about it."""

    undeclared = sorted(
        {
            entry.base_family
            for entry in GRANDPA_MODEL_ROLES
            if entry.base_family not in _FAMILY_MARKERS
        }
    )
    assert not undeclared, (
        f"base_family values with no markers in _FAMILY_MARKERS: {undeclared}. "
        "Add the strings that identify this lineage in Ollama's metadata."
    )


def test_a_tag_that_names_its_family_resolves_to_that_family() -> None:
    """Offline guard: gemma3:4b must not resolve to a Qwen3 role."""

    wrong: list[str] = []
    for tag in _resolvable_tags():
        entry = get_model_role(tag)
        assert entry is not None, f"{tag} is in the registry but does not resolve"
        lowered = tag.casefold()
        for hint, family in _NAME_HINTS:
            if hint not in lowered:
                continue
            if family.casefold() not in entry.base_family.casefold():
                wrong.append(
                    f"{tag} names {family} but resolves to role {entry.role!r} "
                    f"declaring base_family {entry.base_family!r}"
                )
    assert not wrong, "Tags aliased onto the wrong family:" + "".join(
        f"\n  {item}" for item in wrong
    )


def test_a_gemma_tag_never_resolves_to_a_qwen_role() -> None:
    """The measured regression. grandpa-light's name gives nothing away, so the
    offline guard above cannot see it; pin the two tags by hand as well."""

    for tag in ("grandpa-light:latest", "gemma3:4b"):
        entry = get_model_role(tag)
        assert entry is None or "gemma" in entry.base_family.casefold(), (
            f"{tag} is a gemma3 model but resolves to role {entry.role!r} "
            f"declaring base_family {entry.base_family!r}; identity_prompt "
            "would state that family to the model as fact"
        )


def test_resolvable_tags_report_their_declared_family(
    installed_models: dict[str, dict],
) -> None:
    """The live check: ask Ollama what each tag actually is."""

    if not installed_models:
        pytest.skip("none of the registry's tags are installed")

    mismatches: list[str] = []
    for tag, payload in sorted(installed_models.items()):
        entry = get_model_role(tag)
        assert entry is not None
        markers = _FAMILY_MARKERS.get(entry.base_family)
        if not markers:
            continue  # reported by test_every_declared_family_has_markers
        haystack = _lineage_haystack(tag, payload)
        if not any(marker in haystack for marker in markers):
            details = payload.get("details") or {}
            mismatches.append(
                f"{tag} resolves to role {entry.role!r} declaring base_family "
                f"{entry.base_family!r}, but Ollama reports family "
                f"{details.get('family')!r} / parent {details.get('parent_model')!r}"
            )
    assert not mismatches, (
        "Tags whose declared base_family contradicts the loaded model:"
        + "".join(f"\n  {item}" for item in mismatches)
    )


def test_resolvable_tags_report_their_declared_parameter_count(
    installed_models: dict[str, dict],
) -> None:
    """Secondary signal. Weaker than family -- grandpa-light's 4.3B is within
    tolerance of fast's declared 4.0 -- but it catches a role pointed at a
    different size of the same family."""

    if not installed_models:
        pytest.skip("none of the registry's tags are installed")

    mismatches: list[str] = []
    for tag, payload in sorted(installed_models.items()):
        entry = get_model_role(tag)
        assert entry is not None
        reported = _reported_parameters_b(payload)
        if reported is None:
            continue
        if abs(reported - entry.parameter_count_b) > 0.10 * entry.parameter_count_b:
            mismatches.append(
                f"{tag} resolves to role {entry.role!r} declaring "
                f"{entry.parameter_count_b}B, but Ollama reports {reported:.3f}B"
            )
    assert not mismatches, (
        "Tags whose declared parameter_count_b contradicts the loaded model:"
        + "".join(f"\n  {item}" for item in mismatches)
    )
