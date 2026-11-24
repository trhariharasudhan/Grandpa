"""The app and the orb start each other as separate, detached programs."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from grandpa.app import launch


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))


def test_only_the_app_and_the_orb_can_be_launched() -> None:
    with pytest.raises(ValueError):
        launch.launch("powershell")
    with pytest.raises(ValueError):
        launch.claim("../evil")


def test_a_launch_is_detached_and_runs_the_fixed_command() -> None:
    calls = []
    assert (
        launch.launch("avatar", popen=lambda *a, **k: calls.append((a, k))) == "started"
    )
    (args,), kwargs = calls[0]
    assert args == [sys.executable, "-m", "grandpa", "avatar"]
    assert kwargs["stdin"] is subprocess.DEVNULL and kwargs["close_fds"] is True
    if sys.platform == "win32":
        assert kwargs["creationflags"] & 0x00000008  # DETACHED_PROCESS
    else:
        assert kwargs["start_new_session"] is True


def test_one_copy_of_each(monkeypatch) -> None:
    assert launch.claim("app") is True
    assert launch.running_pid("app") == os.getpid()
    calls = []
    assert launch.launch("app", popen=lambda *a, **k: calls.append(a)) == "running"
    assert calls == []
    launch.release("app")
    assert launch.running_pid("app") is None


def test_a_stale_pid_file_does_not_block(tmp_path) -> None:
    launch.run_dir().mkdir(parents=True, exist_ok=True)
    (launch.run_dir() / "avatar.pid").write_text("999999999", encoding="ascii")
    assert launch.running_pid("avatar") is None
    assert launch.claim("avatar") is True
