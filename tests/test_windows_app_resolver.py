import sys
from pathlib import Path
from types import SimpleNamespace

from grandpa import local_actions, windows_app_resolver
from grandpa.windows_app_resolver import AppResolution, AppResolverCache, resolve_app


def test_resolve_app_from_common_path(tmp_path: Path, monkeypatch) -> None:
    program_files = tmp_path / "ProgramFiles"
    chrome = program_files / "Google" / "Chrome" / "Application" / "chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.write_text("fake", encoding="utf-8")
    monkeypatch.setattr(windows_app_resolver.sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "ProgramFilesX86"))
    monkeypatch.setenv("LocalAppData", str(tmp_path / "LocalAppData"))

    result = resolve_app("chrome", refresh=True, cache=AppResolverCache(tmp_path / "apps.db"))

    assert result.status == "found"
    assert result.launch_kind == "path"
    assert result.launch_target == str(chrome)


def test_resolve_app_uses_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(windows_app_resolver.sys, "platform", "win32")
    cache = AppResolverCache(tmp_path / "apps.db")
    cache.set(
        AppResolution(
            "chrome",
            "Chrome",
            "found",
            "path",
            "C:/Cached/chrome.exe",
            "test",
            "cached",
        )
    )

    result = resolve_app("chrome", cache=cache)

    assert result.launch_target == "C:/Cached/chrome.exe"
    assert result.source == "test"


def test_resolve_app_from_registry_app_paths(tmp_path: Path, monkeypatch) -> None:
    chrome = tmp_path / "Chrome" / "chrome.exe"
    chrome.parent.mkdir()
    chrome.write_text("fake", encoding="utf-8")

    class FakeKey:
        def __init__(self, path: str) -> None:
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def open_key(root, path):
        if path.endswith(r"App Paths\chrome.exe"):
            return FakeKey(path)
        raise OSError

    def query_value_ex(key, name):
        if name == "":
            return str(chrome), 1
        raise OSError

    fake_winreg = SimpleNamespace(
        HKEY_CURRENT_USER=1,
        HKEY_LOCAL_MACHINE=2,
        OpenKey=open_key,
        QueryValueEx=query_value_ex,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr(windows_app_resolver.sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "missing"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "missing86"))
    monkeypatch.setenv("LocalAppData", str(tmp_path / "missing_local"))

    result = resolve_app("chrome", refresh=True, cache=AppResolverCache(tmp_path / "apps.db"))

    assert result.status == "found"
    assert result.source == "registry_app_paths"
    assert result.launch_target == str(chrome)


def test_launch_missing_app_returns_clear_error(monkeypatch) -> None:
    monkeypatch.setattr(windows_app_resolver.sys, "platform", "win32")
    monkeypatch.setattr(
        windows_app_resolver,
        "resolve_app",
        lambda name: AppResolution("chrome", "Chrome", "missing", "missing", "", "not_found", "I could not find Chrome."),
    )

    result = windows_app_resolver.launch_app("chrome")

    assert result.status == "missing"
    assert "could not find Chrome" in result.message


def test_local_action_open_app_uses_resolver(monkeypatch) -> None:
    monkeypatch.setattr(local_actions.sys, "platform", "win32")
    monkeypatch.setattr(
        windows_app_resolver,
        "launch_app",
        lambda name: AppResolution(name, "Chrome", "found", "path", "C:/Chrome/chrome.exe", "test", "found"),
    )

    result = local_actions.handle_local_action("open chrome")

    assert result.status == "handled"
    assert result.target == "C:/Chrome/chrome.exe"
