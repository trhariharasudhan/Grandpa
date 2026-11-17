"""C4: Grandpa never looks at private apps or photographs a password box.

No Windows here: windows, focus and capture are fakes. What is tested is the
one check every screen path makes, that every path makes it, and the user's
own list (add, remove, built-in entries that cannot be removed).
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from PIL import Image

from grandpa.screen import privacy
from grandpa.screen.capture import ScreenCapture
from grandpa.screen.errors import SensitiveScreenDetectedError
from grandpa.screen.models import WindowInfo
from grandpa.screen.privacy import (
    PrivateWindowError,
    add_user_entry,
    check_capture,
    load_blocklist,
    read_user_entries,
    remove_user_entry,
)
from grandpa.screen.service import ScreenVisionService
from grandpa.screen.window_click import UiControl

NOTEPAD = WindowInfo(
    title="Untitled - Notepad", process_name="Notepad.exe", bounds=(0, 0, 800, 600)
)
KEEPASS = WindowInfo(
    title="Database.kdbx - KeePass", process_name="KeePass.exe", bounds=(0, 0, 900, 700)
)
WHATSAPP = WindowInfo(
    title="WhatsApp", process_name="WhatsApp.exe", bounds=(100, 100, 500, 900)
)


@pytest.fixture
def user_list(tmp_path, monkeypatch):
    path = tmp_path / privacy.BLOCKLIST_FILENAME
    monkeypatch.setattr(privacy, "blocklist_path", lambda: path)
    return path


def _no_focus():
    return False


# --- the list -----------------------------------------------------------------


def test_password_managers_and_private_browsing_are_built_in(user_list):
    blocklist = load_blocklist()

    assert blocklist.reason(KEEPASS)
    assert blocklist.reason(
        WindowInfo(title="New tab - Work - Microsoft Edge [InPrivate]")
    )
    assert not blocklist.reason(NOTEPAD)


def test_title_words_match_whole_words_only(user_list):
    blocklist = load_blocklist()

    # "keepass" is a title word; "keepassing" is not that word.
    assert not blocklist.reason(WindowInfo(title="keepassing notes.txt - Notepad"))


def test_user_entries_add_and_remove(user_list):
    assert add_user_entry("WhatsApp.exe")
    assert add_user_entry("salary")
    assert not add_user_entry("whatsapp.exe")  # already there

    assert read_user_entries() == ["whatsapp.exe", "salary"]
    blocklist = load_blocklist()
    assert blocklist.reason(WHATSAPP)
    assert blocklist.reason(WindowInfo(title="Salary 2026.xlsx - Excel"))

    assert remove_user_entry("salary")
    assert read_user_entries() == ["whatsapp.exe"]


def test_built_in_entries_cannot_be_removed_or_duplicated(user_list):
    assert not add_user_entry("keepass.exe")
    assert not remove_user_entry("keepass.exe")
    assert load_blocklist().reason(KEEPASS)


def test_comments_and_blank_lines_in_the_file_are_ignored(user_list):
    user_list.write_text("# my private apps\n\nSignal.exe  # chats\n", "utf-8")

    assert read_user_entries() == ["signal.exe"]


# --- check_capture -------------------------------------------------------------


def test_a_private_app_anywhere_on_screen_refuses_a_full_capture(user_list):
    with pytest.raises(PrivateWindowError, match="KeePass.exe"):
        check_capture(windows=lambda: [NOTEPAD, KEEPASS], password_focus=_no_focus)


def test_a_minimised_or_off_region_private_app_does_not_block(user_list):
    hidden = WindowInfo(title="KeePass", process_name="KeePass.exe", is_minimized=True)
    elsewhere = WindowInfo(
        title="KeePass", process_name="KeePass.exe", bounds=(2000, 0, 2800, 600)
    )

    check_capture(windows=lambda: [NOTEPAD, hidden], password_focus=_no_focus)
    check_capture(
        region=(0, 0, 1920, 1080),
        windows=lambda: [NOTEPAD, elsewhere],
        password_focus=_no_focus,
    )


def test_a_window_capture_looks_only_at_that_window(user_list):
    check_capture(window=NOTEPAD, windows=lambda: [KEEPASS], password_focus=_no_focus)
    with pytest.raises(PrivateWindowError):
        check_capture(window=KEEPASS, password_focus=_no_focus)


def test_a_focused_password_box_refuses_every_capture(user_list):
    with pytest.raises(PrivateWindowError, match="password box"):
        check_capture(windows=lambda: [NOTEPAD], password_focus=lambda: True)


def test_private_window_error_is_a_sensitive_screen_error():
    # So every existing "blocked" handler (chat, voice, CLI) refuses it too.
    assert issubclass(PrivateWindowError, SensitiveScreenDetectedError)


def test_the_focus_check_is_off_under_pytest():
    assert privacy.focus_is_password() is False


# --- every path makes the check -----------------------------------------------


def test_screen_capture_checks_before_grabbing_any_pixel(monkeypatch):
    monkeypatch.setattr("grandpa.screen.capture.list_monitors", lambda: [])
    monkeypatch.setattr(
        "grandpa.screen.capture.virtual_desktop_bounds", lambda _m: (0, 0, 1920, 1080)
    )
    capture = ScreenCapture(
        privacy_check=Mock(side_effect=PrivateWindowError("private"))
    )
    grab = Mock(return_value=(Image.new("RGB", (4, 4), "white"), "fake"))
    monkeypatch.setattr(capture, "_capture_region", grab)

    with pytest.raises(PrivateWindowError):
        capture.capture()

    grab.assert_not_called()
    capture.privacy_check.assert_called_once_with(region=(0, 0, 1920, 1080))


def test_an_allowed_capture_still_works(monkeypatch):
    monkeypatch.setattr("grandpa.screen.capture.list_monitors", lambda: [])
    monkeypatch.setattr(
        "grandpa.screen.capture.virtual_desktop_bounds", lambda _m: (0, 0, 64, 64)
    )
    capture = ScreenCapture(privacy_check=Mock())
    monkeypatch.setattr(
        capture,
        "_capture_region",
        Mock(return_value=(Image.new("RGB", (64, 64), "white"), "fake")),
    )

    assert capture.capture().width == 64


def _service(window):
    return ScreenVisionService(
        capture=Mock(),
        ocr=Mock(),
        analyzer=Mock(),
        window_reader=Mock(return_value=[]),
        active_window_provider=lambda: window,
        control_reader=Mock(return_value=[UiControl("button", "OK")]),
        presser=Mock(return_value=True),
    )


def test_reading_a_private_window_is_refused_before_its_text(user_list):
    service = _service(KEEPASS)

    with pytest.raises(PrivateWindowError):
        service.read_window()
    service.window_reader.assert_not_called()


def test_pressing_in_a_private_window_is_refused(user_list):
    add_user_entry("whatsapp.exe")
    service = _service(WHATSAPP)

    with pytest.raises(PrivateWindowError):
        service.click("OK")
    service.presser.assert_not_called()


def test_an_ordinary_window_is_still_read_and_pressed(user_list):
    service = _service(NOTEPAD)

    assert service.click("OK").status == "handled"


# --- CLI -----------------------------------------------------------------------


def test_cli_lists_adds_and_removes(user_list):
    from grandpa.cli.screen_cmd import screen

    runner = CliRunner()
    shown = runner.invoke(screen, ["private"])
    assert "keepass.exe" in shown.output
    assert "(none yet)" in shown.output

    added = runner.invoke(screen, ["private", "add", "WhatsApp.exe"])
    assert "Added whatsapp.exe" in added.output
    assert "whatsapp.exe" in runner.invoke(screen, ["private"]).output

    kept = runner.invoke(screen, ["private", "remove", "keepass.exe"])
    assert "nothing changed" in kept.output
    assert load_blocklist().reason(KEEPASS)

    removed = runner.invoke(screen, ["private", "remove", "whatsapp.exe"])
    assert "Removed whatsapp.exe" in removed.output
