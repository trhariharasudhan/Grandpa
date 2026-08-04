from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from grandpa.apps.automation import ApplicationManager
from grandpa.apps.inventory import (
    AppInventoryRecord,
    find_app,
    launch_inventory_app,
    list_apps,
    normalize_app_name,
    save_inventory,
    scan_app_inventory,
)
from grandpa.apps.models import ApplicationInfo, AppProcessInfo
from grandpa.apps.process_manager import find_running_app, list_running_apps
from grandpa.apps.registry import APP_REGISTRY_SCHEMA_VERSION, load_app_registry
from grandpa.cli.apps_cmd import apps


def test_app_name_normalization() -> None:
    assert normalize_app_name("Visual-Studio_Code.lnk") == "visual studio code"


def test_app_inventory_scan_from_fake_start_menu(tmp_path: Path) -> None:
    start_menu = tmp_path / "Start Menu" / "Programs"
    start_menu.mkdir(parents=True)
    (start_menu / "Spotify.lnk").write_text("fake", encoding="utf-8")
    store = tmp_path / "apps.json"

    records = scan_app_inventory(
        start_menu_roots=[start_menu],
        install_roots=[],
        store_path=store,
        registry_rows=[],
        resolver_rows=[],
        app_path_rows=[],
    )

    assert any(record.display_name == "Spotify" for record in records)
    assert any(
        record.normalized_name == "spotify" for record in list_apps(store_path=store)
    )


def test_app_find_exact_match(tmp_path: Path) -> None:
    store = tmp_path / "apps.json"
    save_inventory(
        [
            AppInventoryRecord(
                "Spotify",
                "spotify",
                str(tmp_path / "Spotify.lnk"),
                "test",
                ("spotify",),
                1.0,
            ),
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
            AppInventoryRecord(
                "Visual Studio Code",
                "visual studio code",
                str(tmp_path / "Code.exe"),
                "test",
                ("vscode", "vs code"),
                1.0,
            ),
        ],
        store_path=store,
    )

    result = find_app("vscode", store_path=store)

    assert result.status == "found"
    assert result.matches[0].display_name == "Visual Studio Code"


def test_app_fuzzy_match_uses_safe_threshold(tmp_path: Path) -> None:
    store = tmp_path / "apps.json"
    save_inventory(
        [
            AppInventoryRecord(
                "Blender",
                "blender",
                str(tmp_path / "blender.exe"),
                "test",
                ("blender",),
                1.0,
            ),
        ],
        store_path=store,
    )

    assert find_app("blendr", store_path=store).status == "found"
    assert find_app("studio", store_path=store).status == "missing"


def test_app_ambiguous_match_asks_user(tmp_path: Path) -> None:
    store = tmp_path / "apps.json"
    save_inventory(
        [
            AppInventoryRecord(
                "Visual Studio",
                "visual studio",
                str(tmp_path / "vs.exe"),
                "test",
                ("visual studio",),
                1.0,
            ),
            AppInventoryRecord(
                "Android Studio",
                "android studio",
                str(tmp_path / "studio.exe"),
                "test",
                ("android studio",),
                1.0,
            ),
        ],
        store_path=store,
    )

    result = find_app("studio", store_path=store)

    assert result.status == "ambiguous"
    assert "Which one should I open" in result.message


def test_cache_uses_applications_payload(tmp_path: Path) -> None:
    store = tmp_path / "apps.json"
    save_inventory(
        [
            AppInventoryRecord(
                "Spotify",
                "spotify",
                str(tmp_path / "Spotify.lnk"),
                "test",
                ("spotify",),
                1.0,
            )
        ],
        store_path=store,
    )

    assert '"last_scan"' in store.read_text(encoding="utf-8")
    assert '"applications"' in store.read_text(encoding="utf-8")
    assert f'"schema_version": {APP_REGISTRY_SCHEMA_VERSION}' in store.read_text(
        encoding="utf-8"
    )


def test_old_cache_schema_is_not_trusted(tmp_path: Path) -> None:
    store = tmp_path / "apps.json"
    store.write_text(
        '{"applications": [{"name": "noisy", "path": "tool.exe"}]}', encoding="utf-8"
    )

    assert load_app_registry(store_path=store) == []


def test_start_menu_entry_outranks_program_files_and_deduplicates(
    tmp_path: Path,
) -> None:
    start_menu = tmp_path / "Start Menu"
    start_menu.mkdir()
    shortcut = start_menu / "Visual Studio Code.lnk"
    shortcut.write_text("shortcut", encoding="utf-8")
    install_root = tmp_path / "Program Files"
    product = install_root / "Visual Studio Code"
    product.mkdir(parents=True)
    (product / "Code.exe").write_text("binary", encoding="utf-8")
    store = tmp_path / "apps.json"

    records = scan_app_inventory(
        start_menu_roots=[start_menu],
        install_roots=[install_root],
        store_path=store,
        registry_rows=[
            {
                "display_name": "Microsoft Visual Studio Code (User)",
                "path": str(product / "Code.exe"),
                "source": "registry_uninstall",
            }
        ],
        resolver_rows=[
            {
                "display_name": "VS Code",
                "path": str(product / "Code.exe"),
                "source": "resolver:common_path",
            }
        ],
        app_path_rows=[],
    )

    vscode = [app for app in records if app.canonical_key == "visual studio code"]
    assert len(vscode) == 1
    assert vscode[0].source == "start_menu"
    assert {"visual studio code", "vs code", "vscode", "code"} <= set(vscode[0].aliases)


def test_program_files_scan_is_shallow_and_filters_helpers(tmp_path: Path) -> None:
    install_root = tmp_path / "Program Files"
    product = install_root / "Blender"
    deep = product / "sdk" / "bin"
    deep.mkdir(parents=True)
    (product / "Blender.exe").write_text("binary", encoding="utf-8")
    (product / "BlenderUpdater.exe").write_text("binary", encoding="utf-8")
    (deep / "testhost.exe").write_text("binary", encoding="utf-8")

    records = scan_app_inventory(
        start_menu_roots=[],
        install_roots=[install_root],
        store_path=tmp_path / "apps.json",
        registry_rows=[],
        resolver_rows=[],
        app_path_rows=[],
    )

    assert [app.display_name for app in records] == ["Blender"]


def test_program_files_scan_respects_candidate_bound(
    monkeypatch, tmp_path: Path
) -> None:
    install_root = tmp_path / "Program Files"
    for index in range(4):
        product = install_root / f"Product{index}"
        product.mkdir(parents=True)
        (product / f"Product{index}.exe").write_text("binary", encoding="utf-8")
    monkeypatch.setattr("grandpa.apps.scanner.MAX_PROGRAM_FILES_CANDIDATES", 2)

    records = scan_app_inventory(
        start_menu_roots=[],
        install_roots=[install_root],
        store_path=tmp_path / "apps.json",
        registry_rows=[],
        resolver_rows=[],
        app_path_rows=[],
    )

    assert len(records) == 2


def test_same_canonical_app_is_not_ambiguous() -> None:
    apps = [
        ApplicationInfo(
            "visual studio code",
            ("vs code", "vscode"),
            "Visual Studio Code",
            r"C:\Apps\Code.exe",
            canonical_key="visual studio code",
        ),
        ApplicationInfo(
            "microsoft visual studio code user",
            ("vs code", "code"),
            "Microsoft Visual Studio Code (User)",
            r"C:\Apps\Code.exe",
            canonical_key="visual studio code",
        ),
    ]

    from grandpa.apps.resolver import resolve_app

    assert resolve_app("visual studio code", apps).status == "found"


def test_running_apps_group_browser_children_and_filter_system(monkeypatch) -> None:
    processes = [
        AppProcessInfo(1, "chrome.exe", "Google Chrome"),
        AppProcessInfo(2, "chrome.exe", "Google Chrome"),
        AppProcessInfo(3, "RuntimeBroker.exe", ""),
        AppProcessInfo(4, "System Idle Process", ""),
    ]
    monkeypatch.setattr(
        "grandpa.apps.process_manager._psutil_processes", lambda **_kwargs: processes
    )
    monkeypatch.setattr(
        "grandpa.apps.process_manager._visible_window_pids", lambda: {1, 2, 3, 4}
    )

    apps = list_running_apps()

    assert len(apps) == 1
    assert apps[0].display_name == "Google Chrome"
    assert apps[0].process_count == 2


def test_all_processes_keeps_raw_diagnostic_rows(monkeypatch) -> None:
    processes = [AppProcessInfo(4, "System Idle Process", "System Idle Process")]
    monkeypatch.setattr(
        "grandpa.apps.process_manager._psutil_processes", lambda **_kwargs: processes
    )

    assert list_running_apps(include_all_processes=True) == processes


def test_running_app_exact_match() -> None:
    from grandpa.apps.models import AppProcessInfo

    proc = find_running_app(
        "chrome",
        processes=[
            AppProcessInfo(
                123, "chrome.exe", "Chrome", r"C:\Program Files\Chrome\chrome.exe"
            )
        ],
    )

    assert proc is not None
    assert proc.pid == 123


def test_running_apps_fallback_uses_tasklist(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(
        "grandpa.apps.process_manager.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout='"chrome.exe","123","Console","1","100 K"\n'
        ),
    )

    apps = list_running_apps()

    assert apps[0].name == "chrome.exe"
    assert apps[0].pid == 123


def test_dangerous_launch_target_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "bad.bat"
    target.write_text("echo nope", encoding="utf-8")
    record = AppInventoryRecord("Bad", "bad", str(target), "test", ("bad",), 1.0)

    with pytest.raises(ValueError):
        launch_inventory_app(record)


def test_apps_cli_list_and_find(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / "apps.json"
    save_inventory(
        [
            AppInventoryRecord(
                "Spotify",
                "spotify",
                str(tmp_path / "Spotify.lnk"),
                "test",
                ("spotify",),
                1.0,
            )
        ],
        store_path=store,
    )
    monkeypatch.setattr(
        ApplicationManager,
        "__init__",
        lambda self, store_path=store: setattr(self, "store_path", store),
    )

    runner = CliRunner()
    list_result = runner.invoke(apps, ["list"])
    find_result = runner.invoke(apps, ["find", "spotify"])

    assert list_result.exit_code == 0
    assert "Spotify" in list_result.output
    assert find_result.exit_code == 0
    assert "Found Spotify" in find_result.output


def test_apps_cli_list_is_limited_and_all_includes_technical(
    monkeypatch, tmp_path: Path
) -> None:
    from grandpa.apps.registry import save_app_registry

    store = tmp_path / "apps.json"
    save_app_registry(
        [
            ApplicationInfo(
                "chrome", ("chrome",), "Chrome", "chrome.exe", canonical_key="chrome"
            ),
            ApplicationInfo(
                "testhost",
                ("testhost",),
                "testhost",
                "testhost.exe",
                confidence=0.2,
                is_user_facing=False,
                canonical_key="testhost",
            ),
        ],
        store_path=store,
    )
    monkeypatch.setattr(
        ApplicationManager,
        "__init__",
        lambda self, store_path=store: setattr(self, "store_path", store),
    )
    runner = CliRunner()

    default = runner.invoke(apps, ["list", "--limit", "1"])
    raw = runner.invoke(apps, ["list", "--all"])

    assert "Chrome" in default.output
    assert "testhost" not in default.output
    assert "testhost" in raw.output
