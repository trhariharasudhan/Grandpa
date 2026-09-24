"""A process that stops making progress says what it was doing.

``tests/e2e/test_reminders_fire.py::test_at_five_pm_is_one_shot`` has timed out
twice, in two sessions, each time with the command's full and correct output
already printed. Every investigation after the fact could only rule things out --
there was no lingering non-daemon thread, the command takes under a second, it
would not reproduce in seven attempts -- because by the time anyone looked the
process had been killed and had left nothing behind.

So the process leaves something behind. ``faulthandler.dump_traceback_later``
arms a watchdog in C: after N seconds nobody has cancelled, it writes every
thread's stack and ends the process. The CLI arms it when
``GRANDPA_STALL_TIMEOUT`` is set, and the e2e harness sets it for every child.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from grandpa.diagnostics import stall

pytestmark = pytest.mark.core


def test_it_is_off_unless_asked_for(monkeypatch) -> None:
    """A library does not install watchdogs in somebody else's process."""
    monkeypatch.delenv(stall.ENV_VAR, raising=False)

    assert stall.configured_timeout() == 0.0
    assert stall.arm() is False


@pytest.mark.parametrize("raw", ["", "0", "-5", "not a number"])
def test_nonsense_settings_leave_it_off(monkeypatch, raw: str) -> None:
    monkeypatch.setenv(stall.ENV_VAR, raw)

    assert stall.configured_timeout() == 0.0


def test_a_timeout_is_read_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv(stall.ENV_VAR, "12.5")

    assert stall.configured_timeout() == 12.5


def test_the_log_lives_under_grandpa_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "home"))

    assert stall.stall_log_path() == tmp_path / "home" / "stalled-stacks.log"


@pytest.mark.real_actions(
    reason="runs a python subprocess that deliberately hangs, to prove the "
    "watchdog dumps its stack and ends it; everything is under tmp_path"
)
def test_a_hung_process_dumps_its_stack_and_ends(tmp_path: Path) -> None:
    """The whole point: a stall leaves evidence instead of a silent kill.

    The child sleeps far longer than the watchdog allows. If the watchdog works,
    the child dies on its own with the stacks written; if it does not, this test
    is the thing that hangs, and ``timeout`` below fails it.
    """
    home = tmp_path / "home"
    script = textwrap.dedent(
        """
        import sys, time
        sys.path.insert(0, SRC)
        from grandpa.diagnostics import stall
        stall.arm()
        def the_function_that_hangs():
            time.sleep(120)
        the_function_that_hangs()
        """
    ).replace("SRC", repr(str(Path(__file__).resolve().parents[1] / "src")))

    env = {
        **os.environ,
        "GRANDPA_HOME": str(home),
        stall.ENV_VAR: "3",
        "PYTHONIOENCODING": "utf-8",
    }

    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )

    assert proc.returncode != 0, "the watchdog should have ended the process"
    log = home / "stalled-stacks.log"
    assert log.exists(), "no stacks were written"
    written = log.read_text(encoding="utf-8", errors="replace")
    assert "Timeout (0:00:03)" in written or "Timeout" in written, written[:400]
    # It names the function that was stuck, which is the entire value of this.
    assert "the_function_that_hangs" in written, written[:800]


@pytest.mark.real_actions(
    reason="runs a python subprocess that finishes normally, to prove a disarmed "
    "watchdog does not fire; everything is under tmp_path"
)
def test_a_command_that_finishes_is_not_killed(tmp_path: Path) -> None:
    """The watchdog must not end a process that is simply doing its job."""
    home = tmp_path / "home"
    script = textwrap.dedent(
        """
        import sys, time
        sys.path.insert(0, SRC)
        from grandpa.diagnostics import stall
        stall.arm()
        time.sleep(0.2)
        stall.disarm()
        time.sleep(1.0)
        print("finished")
        """
    ).replace("SRC", repr(str(Path(__file__).resolve().parents[1] / "src")))

    env = {
        **os.environ,
        "GRANDPA_HOME": str(home),
        stall.ENV_VAR: "0.5",
        "PYTHONIOENCODING": "utf-8",
    }

    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr
    assert "finished" in proc.stdout


def test_the_e2e_harness_arms_it_for_every_child() -> None:
    """A stall in the suite is the case this exists for, so the suite sets it."""
    from tests.e2e.harness import CLI_TIMEOUT, STALL_TIMEOUT, Sandbox

    assert 0 < STALL_TIMEOUT < CLI_TIMEOUT, (STALL_TIMEOUT, CLI_TIMEOUT)
    box = Sandbox()
    try:
        assert box.env().get(stall.ENV_VAR) == str(STALL_TIMEOUT)
    finally:
        box.cleanup()
