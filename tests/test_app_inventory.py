from pathlib import Path

import pytest

from grandpa.apps.inventory import (
    AppInventoryRecord,
    find_app,
    launch_inventory_app,
    list_apps,
    normalize_app_name,
    save_inventory,
    scan_app_inventory,
)


def test_app_name_normalization() -> None:
    assert normalize_app_name("Visual-Studio_Code.lnk") == "visual studio code"


def test_app_inventory_scan_from_fake_start_menu(tmp_path: Path) -> None:
    start_menu = tmp_path / "Start Menu" / "Programs"
    start_menu.mkdir(parents=True)
    (start_menu / "Spotify.lnk").write_text("fake", encoding="utf-8")
    store = tmp_path / "apps.json"

    records = scan_app_inventory(start_menu_roots=[start_menu], install_roots=[], store_path=store)

    assert any(record.display_name == "Spotify" for record in records)
    assert any(record.normalized_name == "spotify" for record in list_apps(store_path=store))


def test_app_find_exact_match(tmp_path: Path) -> None:
    store = tmp_path / "apps.json"
    save_inventory(
        [
            AppInventoryRecord("Spotify", "spotify", str(tmp_path / "Spotify.lnk"), "test", ("spotify",), 1.0),
        ],
        store_path=store,
    )

    result = find_app("spotify", store_path=store)

    assert result.status == "found"
    assert result.matches[0].display_name == "Spotify"


def test_app_find_alias_match(tmp_path: Path) -> None:
    store = tmp_path / "apps.json"
    save_inventory(
        [
            AppInventoryRecord("Visual Studio Code", "visual studio code", str(tmp_path / "Code.exe"), "test", ("vscode", "vs code"), 1.0),
        ],
        store_path=store,
    )

    result = find_app("vscode", store_path=store)

    assert result.status == "found"
    assert result.matches[0].display_name == "Visual Studio Code"


def test_dangerous_launch_target_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "bad.bat"
    target.write_text("echo nope", encoding="utf-8")
    record = AppInventoryRecord("Bad", "bad", str(target), "test", ("bad",), 1.0)

    with pytest.raises(ValueError):
        launch_inventory_app(record)
