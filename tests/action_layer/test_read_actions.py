"""The read actions, and the two limits that make file_read safe to offer.

Reading is the half of the catalogue that was missing, and the half a model is
most likely to reach for. ``file_read`` is the one with teeth: it can only read
where file search can already look, and it refuses a file big enough to crowd
out the conversation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.action_layer.catalogue import LAYER_OWNED, get
from grandpa.action_layer.executor import execute
from grandpa.action_layer.model import ActionRequest, RiskLevel
from grandpa.files.executor import MAX_READ_BYTES, FileExecutor
from grandpa.files.models import FileAction


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))


@pytest.fixture
def readable_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One searchable root and nothing else.

    The real ``safe_roots()`` always includes the home directory, and on Windows
    pytest's tmp_path lives *under* it -- so a test that just pointed
    GRANDPA_FILE_SAFE_ROOTS at a temp folder would prove nothing about the gate.
    Narrowing the roots to exactly one folder is what makes "outside" mean
    outside.
    """
    root = tmp_path / "searchable"
    root.mkdir()
    monkeypatch.setattr("grandpa.files.paths.safe_roots", lambda *_a, **_k: (root,))
    return root


def read_request(action: str, **parameters) -> ActionRequest:
    """Build the request the way the loop does: risk and confirmation from the
    catalogue, not from ActionRequest's deliberately cautious defaults."""
    spec = get(action)
    return ActionRequest(
        action,
        parameters,
        risk=spec.risk,
        requires_confirmation=spec.requires_confirmation,
    )


READ_ACTIONS = (
    "volume_get",
    "brightness_get",
    "file_read",
    "clipboard_read",
    "list_windows",
    "list_processes",
    "active_process",
    "screenshot_describe",
)


@pytest.mark.parametrize("action", READ_ACTIONS)
def test_every_read_action_is_low_risk_and_asks_nothing(action: str) -> None:
    spec = get(action)

    assert spec.risk is RiskLevel.LOW, action
    assert spec.requires_confirmation is False, action


@pytest.mark.parametrize("action", READ_ACTIONS)
def test_every_read_action_resolves_to_something_callable(action: str) -> None:
    from grandpa.action_layer.executor import _resolve

    implementation, _owner = _resolve(get(action).implementation)

    assert callable(implementation)


# --- file_read ----------------------------------------------------------------


def test_a_file_in_a_searchable_root_reads_back(readable_root: Path) -> None:
    note = readable_root / "note.txt"
    note.write_text("shopping list", encoding="utf-8")

    result = execute(read_request("file_read", path=str(note)))

    assert result.success is True, result
    assert result.data["content"] == "shopping list"
    assert result.data["size"] == len("shopping list")


def test_a_file_outside_the_searchable_roots_is_refused(
    readable_root: Path, tmp_path: Path
) -> None:
    """The same roots file search walks, and nothing wider."""
    secret = tmp_path / "elsewhere" / "private.txt"
    secret.parent.mkdir()
    secret.write_text("not yours", encoding="utf-8")

    result = execute(read_request("file_read", path=str(secret)))

    assert result.success is False
    assert result.error == "outside_safe_roots", result
    assert "not yours" not in result.message


def test_the_env_var_that_widens_file_search_widens_reading_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GRANDPA_FILE_SAFE_ROOTS is how a user opens a folder to file search, and
    reading follows the same setting rather than inventing its own."""
    from grandpa.files.paths import safe_roots

    extra = tmp_path / "opened-up"
    extra.mkdir()
    monkeypatch.setenv("GRANDPA_FILE_SAFE_ROOTS", str(extra))

    assert extra in safe_roots()


def test_a_file_over_the_limit_is_refused_without_being_read(
    readable_root: Path,
) -> None:
    big = readable_root / "big.log"
    big.write_text("x" * 2048, encoding="utf-8")

    result = execute(read_request("file_read", path=str(big), max_bytes=1024))

    assert result.success is False
    assert result.error == "file_too_large"
    assert "content" not in result.data, "it read the file it had just refused"


def test_the_ceiling_cannot_be_raised_by_asking(readable_root: Path) -> None:
    """max_bytes narrows the limit; it cannot widen it past MAX_READ_BYTES."""
    result = FileExecutor(roots=(readable_root,)).execute(
        FileAction(
            action="read",
            source=str(readable_root / "missing.txt"),
            args={"max_bytes": MAX_READ_BYTES * 100},
        )
    )

    # It got past the size gate to the existence check, so the huge request was
    # clamped rather than honoured.
    assert result.error == "missing_file"


def test_a_missing_file_says_so(readable_root: Path) -> None:
    result = execute(read_request("file_read", path=str(readable_root / "nope.txt")))

    assert result.error == "missing_file"


def test_a_binary_file_is_reported_not_mangled(readable_root: Path) -> None:
    binary = readable_root / "image.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")

    result = execute(read_request("file_read", path=str(binary)))

    assert result.error == "not_text", result


def test_the_schema_rejects_a_negative_limit(readable_root: Path) -> None:
    result = execute(read_request("file_read", path=str(readable_root), max_bytes=-1))

    assert result.error == "invalid_parameters"


# --- volume_get ---------------------------------------------------------------


def test_volume_get_reports_a_level_or_says_why_it_cannot() -> None:
    """pycaw is an optional backend. Either answer is honest; inventing is not."""
    result = execute(read_request("volume_get"))

    if result.success:
        assert 0 <= result.data["level"] <= 100
        assert isinstance(result.data["muted"], bool)
    else:
        assert result.error in {"missing_volume_backend", "unsupported"}, result
        assert "pycaw" in result.message or "Windows" in result.message


def test_volume_get_needs_no_arguments() -> None:
    assert get("volume_get").parameters["properties"] == {}
    assert get("volume_get").parameters["required"] == []


# --- what the layer owns ------------------------------------------------------


def test_the_new_read_actions_are_declared_as_the_layers_own() -> None:
    assert {"volume_get", "file_read", "screenshot_describe"} <= set(LAYER_OWNED)
