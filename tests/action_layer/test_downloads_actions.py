"""Downloads through the action layer, and the confirmation shape it forced.

Notes could be asked about before the call, from its parameters alone.
Downloads cannot: "Archive 1 download (6 B)?" only exists after the scan, and
whether to ask at all depends on what the scan found. So these are
``Confirmation.DOMAIN`` -- the layer hands its callback over. The tests below
are mostly about proving that still refuses when it should.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grandpa.action_layer.catalogue import CATALOGUE, Binding, Confirmation, get
from grandpa.action_layer.executor import execute
from grandpa.action_layer.model import ActionRequest, Origin, RiskLevel
from grandpa.downloads.models import DownloadActionType

# Opted out of the default-deny actuation fixture (tests/actuation_guard.py):
pytestmark = pytest.mark.real_actions(
    reason="drives the real domain implementation against the store under the test's own GRANDPA_HOME"
)

DOWNLOADS_ACTIONS = tuple(
    spec for spec in CATALOGUE if spec.binding is Binding.DOWNLOADS_ACTION
)


@pytest.fixture(autouse=True)
def downloads_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One downloads folder per test, and an audit log that is not the real one."""
    from grandpa.downloads.scanner import DownloadsScanner

    root = tmp_path / "Downloads"
    root.mkdir()
    monkeypatch.setattr(
        "grandpa.downloads.automation.DownloadsScanner",
        lambda *a, **k: DownloadsScanner(roots=(root,)),
    )
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    return root


def act(action: str, confirm=None, **parameters):
    spec = get(action)
    return execute(
        ActionRequest(
            action,
            parameters,
            origin=Origin.USER_CHAT,
            risk=spec.risk,
            requires_confirmation=spec.requires_confirmation,
        ),
        confirm,
    )


# --- the catalogue matches what downloads can do ------------------------------


def test_every_action_the_parser_can_produce_is_catalogued() -> None:
    produced = set(DownloadActionType.__args__)
    catalogued = {spec.action_alias for spec in DOWNLOADS_ACTIONS}

    assert produced == catalogued, produced ^ catalogued


def test_they_all_point_at_the_existing_downloads_implementation() -> None:
    assert {spec.implementation for spec in DOWNLOADS_ACTIONS} == {
        "grandpa.downloads.automation.DownloadsAutomation.execute"
    }


# --- reading ------------------------------------------------------------------


def test_recent_lists_what_is_in_the_folder(downloads_home: Path) -> None:
    (downloads_home / "report.pdf").write_bytes(b"%PDF")

    result = act("downloads_recent")

    assert result.success is True, result
    assert "report.pdf" in result.message


def test_search_finds_by_name(downloads_home: Path) -> None:
    (downloads_home / "quarterly-report.pdf").write_bytes(b"%PDF")
    (downloads_home / "cat.png").write_bytes(b"\x89PNG")

    result = act("downloads_search", query="quarterly")

    assert result.success is True, result
    assert "quarterly-report.pdf" in result.message
    assert "cat.png" not in result.message


def test_latest_is_catalogued_but_still_unsupported(downloads_home: Path) -> None:
    """The parser produces it and _execute has no branch. Catalogued so the
    honest refusal survives the migration rather than becoming an LLM guess."""
    (downloads_home / "report.pdf").write_bytes(b"%PDF")

    result = act("downloads_latest")

    assert result.success is False
    assert "not supported yet" in result.message


# --- the domain does the asking ----------------------------------------------


@pytest.mark.parametrize(
    "action", ["downloads_delete", "downloads_archive", "downloads_organize"]
)
def test_the_changing_actions_are_confirmed_by_the_domain(action: str) -> None:
    assert get(action).confirmation is Confirmation.DOMAIN
    assert get(action).requires_confirmation is True


def test_with_no_callback_nothing_is_deleted(downloads_home: Path) -> None:
    """No one to ask means no, even though the domain would have done the asking."""
    target = downloads_home / "old.pdf"
    target.write_bytes(b"%PDF")

    result = act("downloads_delete", which="old.pdf")

    assert result.error == "confirmation_required", result
    assert target.exists(), "deleted with nobody asked"


def test_a_declined_delete_keeps_the_file(downloads_home: Path) -> None:
    target = downloads_home / "old.pdf"
    target.write_bytes(b"%PDF")

    result = act("downloads_delete", which="old.pdf", confirm=lambda *_: False)

    assert result.success is False, result
    assert target.exists(), "deleted after answering no"


def test_an_approved_delete_removes_the_file(downloads_home: Path) -> None:
    target = downloads_home / "old.pdf"
    target.write_bytes(b"%PDF")
    asked = MagicMock(return_value=True)

    result = act("downloads_delete", which="old.pdf", confirm=asked)

    assert result.success is True, result
    assert not target.exists()
    assert "Deleted 1 download" in result.message


def test_the_prompt_quotes_what_the_scan_found(downloads_home: Path) -> None:
    """The whole reason downloads asks for itself rather than the layer."""
    (downloads_home / "old.pdf").write_bytes(b"%PDF12")
    asked = MagicMock(return_value=True)

    act("downloads_archive", which="old.pdf", confirm=asked)

    _action, parameters, risk = asked.call_args.args
    assert parameters["_plan"] == "Archive 1 download (6 B)?", parameters
    assert risk is RiskLevel.MEDIUM


def test_moving_one_file_does_not_ask(downloads_home: Path) -> None:
    """A single-file move has always been silent; the migration kept that."""
    target = downloads_home / "one.pdf"
    target.write_bytes(b"%PDF")
    destination = downloads_home / "Sorted"
    asked = MagicMock(return_value=True)

    result = act(
        "downloads_move", which="one.pdf", destination=str(destination), confirm=asked
    )

    assert result.success is True, result
    asked.assert_not_called()


# --- validation and audit -----------------------------------------------------


def test_a_move_with_no_destination_is_refused_before_the_scan() -> None:
    result = act("downloads_move", which="anything")

    assert result.error == "invalid_parameters"
    assert "destination" in result.message


def test_the_action_is_audited_with_chat_as_the_origin(
    downloads_home: Path, tmp_path: Path
) -> None:
    import json

    (downloads_home / "report.pdf").write_bytes(b"%PDF")
    act("downloads_recent")

    records = [
        json.loads(line)
        for line in (tmp_path / "actions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert records[-1]["action_type"] == "downloads_recent"
    assert records[-1]["origin"] == "user_chat"
    assert records[-1]["ok"] is True
