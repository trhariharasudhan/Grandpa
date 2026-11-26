"""/model: every installed Grandpa model, forgiving names, and the memory fallback."""

from __future__ import annotations

from types import SimpleNamespace

from grandpa.cli.chat_cmd import _smaller_model_that_fits
from grandpa.cli.interactive_tui import model_menu, resolve_model_tag

INSTALLED = [
    "grandpa-brain:latest",
    "grandpa-fast:latest",
    "grandpa-mini:latest",
    "grandpa-coder:latest",
    "grandpa-general:latest",
    "grandpa-light:latest",
    "qwen:latest",
    "qwen2.5:0.5b-instruct-q4_K_M",
    "nomic-embed-text:latest",
]


def test_names_are_forgiving() -> None:
    assert resolve_model_tag("brain", INSTALLED) == "grandpa-brain:latest"
    assert resolve_model_tag("grandpa-fast", INSTALLED) == "grandpa-fast:latest"
    assert resolve_model_tag("GRANDPA-FAST:LATEST", INSTALLED) == "grandpa-fast:latest"
    assert resolve_model_tag("general", INSTALLED) == "grandpa-general:latest"
    assert resolve_model_tag("qwen", INSTALLED) == "qwen:latest"
    assert resolve_model_tag("nonsense", INSTALLED) is None


def test_the_menu_lists_every_grandpa_model() -> None:
    rows = model_menu(INSTALLED, "grandpa-brain:latest")
    tags = [tag for tag, _label, _ok in rows]
    for wanted in (
        "grandpa-mini:latest",
        "grandpa-fast:latest",
        "grandpa-brain:latest",
        "grandpa-coder:latest",
        "grandpa-general:latest",
        "grandpa-light:latest",
        "qwen:latest",
    ):
        assert wanted in tags
    assert "nomic-embed-text:latest" not in tags  # embeddings are not for chat
    assert "qwen2.5:0.5b-instruct-q4_K_M" not in tags  # old name of Mini
    current = next(label for tag, label, _ in rows if tag == "grandpa-brain:latest")
    assert current.startswith("*") and "needs ~8 GB" in current
    eyes = next(row for row in rows if row[0] == "grandpa-eyes:latest")
    assert eyes[2] is False and "not installed" in eyes[1]
    assert tags.index("grandpa-general:latest") < tags.index("qwen:latest")


def _engine(installed):
    return SimpleNamespace(list_models=lambda: list(installed))


def test_out_of_memory_falls_back_to_the_next_smaller_model() -> None:
    oom = RuntimeError("Ollama could not load x because available memory is too low.")
    assert (
        _smaller_model_that_fits(_engine(INSTALLED), "grandpa-brain:latest", oom)
        == "grandpa-fast:latest"
    )
    assert (
        _smaller_model_that_fits(_engine(INSTALLED), "grandpa-fast:latest", oom)
        == "grandpa-mini:latest"
    )
    # Fast missing: brain goes straight to mini.
    no_fast = [m for m in INSTALLED if "fast" not in m]
    assert (
        _smaller_model_that_fits(_engine(no_fast), "grandpa-brain:latest", oom)
        == "grandpa-mini:latest"
    )
    assert (
        _smaller_model_that_fits(_engine(INSTALLED), "grandpa-mini:latest", oom) is None
    )


def test_other_load_errors_are_not_retried() -> None:
    broken = RuntimeError("Ollama could not load x: unknown model architecture")
    assert (
        _smaller_model_that_fits(_engine(INSTALLED), "grandpa-brain:latest", broken)
        is None
    )
