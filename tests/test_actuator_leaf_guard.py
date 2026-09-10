"""No test may open a real browser or launch a real application.

Three times in recent work a test patched the wrong namespace, so its fake was
never used and the real actuator ran -- once opening Chrome on a developer's
machine. Each was caught by a hand-written fixture in the file that happened to
have one; six files out of roughly two hundred did.

A census of the full suite (recording every call rather than blocking it) found
``webbrowser.open``, ``webbrowser.open_new_tab`` and ``os.startfile`` are
called **zero** times. Nothing legitimately needs them, so refusing them
suite-wide costs nothing and closes the whole class of mistake.

Deliberately not guarded, because the same census found them heavily and
legitimately used -- guarding them would break pytest itself:

``Path.unlink`` (1554 calls)
    pytest's own ``tmp_path`` teardown.
``shutil.rmtree`` (145)
    the same, plus test cleanup.
``subprocess.Popen`` (354)
    git-tool tests, agent CLI execution, ``compileall``.

Also unguarded: ``pyautogui``, because tests substitute
``sys.modules["pyautogui"]`` and a real-module guard would not fire reliably;
and ``pc_control.run_local_action``, which twenty test files exercise as the
system under test.

The opt-out is the ``browser`` marker -- registered in ``pyproject.toml`` and
unused until now -- following the ``microphone`` precedent already in
``conftest.py``.
"""

from __future__ import annotations

import os
import webbrowser

import pytest


def _is_guard(func: object) -> bool:
    """Whether *func* is this file's guard rather than the real actuator."""
    return getattr(func, "_grandpa_actuator_guard", False) is True


# ---------------------------------------------------------------------------
# The guard refuses
# ---------------------------------------------------------------------------


class TestTheGuardRefuses:
    def test_opening_a_browser_raises(self):
        with pytest.raises(AssertionError) as excinfo:
            webbrowser.open("https://example.test")

        assert "webbrowser.open" in str(excinfo.value)

    def test_opening_a_new_tab_raises(self):
        with pytest.raises(AssertionError) as excinfo:
            webbrowser.open_new_tab("https://example.test")

        assert "webbrowser.open_new_tab" in str(excinfo.value)

    @pytest.mark.skipif(
        not hasattr(os, "startfile"), reason="os.startfile is Windows-only"
    )
    def test_launching_a_file_raises(self):
        with pytest.raises(AssertionError) as excinfo:
            os.startfile("C:/Windows/notepad.exe")

        assert "os.startfile" in str(excinfo.value)

    def test_the_message_names_the_target(self):
        with pytest.raises(AssertionError) as excinfo:
            webbrowser.open("https://example.test/page")

        assert "https://example.test/page" in str(excinfo.value)

    def test_the_message_names_the_test(self):
        """So a failure in a large run says which test to look at."""
        with pytest.raises(AssertionError) as excinfo:
            webbrowser.open("https://example.test")

        assert "test_the_message_names_the_test" in str(excinfo.value)

    def test_the_message_says_how_to_opt_out(self):
        """Naming the marker, not merely the word "browser".

        The message already says "open a real browser", so a looser assertion
        passes even when the actionable half is gone.
        """
        with pytest.raises(AssertionError) as excinfo:
            webbrowser.open("https://example.test")

        assert "pytest.mark.browser" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The guard is installed everywhere
# ---------------------------------------------------------------------------


class TestTheGuardIsInstalled:
    def test_it_applies_without_being_requested(self):
        """Autouse: a test that asks for nothing is still protected."""
        assert _is_guard(webbrowser.open)
        assert _is_guard(webbrowser.open_new_tab)

    @pytest.mark.skipif(
        not hasattr(os, "startfile"), reason="os.startfile is Windows-only"
    )
    def test_startfile_is_guarded_too(self):
        assert _is_guard(os.startfile)

    def test_a_test_can_still_substitute_its_own_fake(self, monkeypatch):
        """The guard must not fight a test that patches deliberately."""
        seen: list[str] = []
        monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: seen.append(url))

        webbrowser.open("https://example.test")

        assert seen == ["https://example.test"]


# ---------------------------------------------------------------------------
# The opt-out
# ---------------------------------------------------------------------------


@pytest.mark.browser
class TestTheBrowserMarkerOptsOut:
    """A test that genuinely needs a browser declares it, as ``microphone`` does.

    These assert the guard is *absent* rather than calling through, so the
    suite still never opens anything.
    """

    def test_the_guard_is_not_installed(self):
        assert not _is_guard(webbrowser.open)
        assert not _is_guard(webbrowser.open_new_tab)

    @pytest.mark.skipif(
        not hasattr(os, "startfile"), reason="os.startfile is Windows-only"
    )
    def test_startfile_is_not_guarded_either(self):
        assert not _is_guard(os.startfile)


@pytest.mark.browser
def test_the_marker_works_on_a_plain_function_too():
    assert not _is_guard(webbrowser.open)


# ---------------------------------------------------------------------------
# Nothing else changed
# ---------------------------------------------------------------------------


class TestScope:
    @pytest.mark.parametrize(
        "leaf",
        [
            "Path.unlink",
            "shutil.rmtree",
            "subprocess.Popen",
        ],
    )
    def test_the_heavily_used_leaves_are_left_alone(self, leaf):
        """Guarding these would break pytest's own temp-directory teardown."""
        import shutil
        import subprocess
        from pathlib import Path

        actual = {
            "Path.unlink": Path.unlink,
            "shutil.rmtree": shutil.rmtree,
            "subprocess.Popen": subprocess.Popen,
        }[leaf]

        assert not _is_guard(actual)

    def test_the_actuator_boundary_is_not_guarded(self):
        """Twenty test files exercise ``run_local_action`` as the SUT."""
        from grandpa import pc_control

        assert not _is_guard(pc_control.run_local_action)

    def test_pyautogui_is_not_guarded(self):
        """Tests substitute ``sys.modules``; a real-module guard would not fire."""
        import sys

        module = sys.modules.get("pyautogui")
        if module is not None:
            assert not _is_guard(getattr(module, "click", None))

    def test_a_temp_file_can_still_be_removed(self, tmp_path):
        """The practical consequence of leaving the filesystem leaves alone."""
        victim = tmp_path / "scratch.txt"
        victim.write_text("x", encoding="utf-8")

        victim.unlink()

        assert not victim.exists()

    def test_the_browser_marker_is_registered(self):
        """The opt-out uses a marker the project already declares."""
        import pathlib

        import tomllib

        config = tomllib.loads(
            pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
        )
        markers = config["tool"]["pytest"]["ini_options"]["markers"]

        assert any(marker.startswith("browser:") for marker in markers)


# ---------------------------------------------------------------------------
# The microphone precedent is untouched
# ---------------------------------------------------------------------------


class TestMicrophoneBehaviourPreserved:
    def test_the_microphone_marker_is_still_registered(self):
        import pathlib

        import tomllib

        config = tomllib.loads(
            pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
        )
        markers = config["tool"]["pytest"]["ini_options"]["markers"]

        assert any(marker.startswith("microphone:") for marker in markers)

    def test_microphone_tests_are_still_opt_in(self):
        """``conftest`` skips them unless GRANDPA_RUN_MICROPHONE_TESTS=1."""
        import pathlib

        conftest = pathlib.Path("tests/conftest.py").read_text(encoding="utf-8")

        assert "GRANDPA_RUN_MICROPHONE_TESTS" in conftest
        assert 'if "microphone" in marker_names' in conftest
