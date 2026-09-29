"""A plain script can arm the write guard, and then cannot write outside it.

The guard lived only inside pytest, so every ad-hoc probe ran unguarded -- and
every machine change in recent turns came from exactly that: a script importing
grandpa before setting GRANDPA_HOME, writing into a real ``~/.grandpa``. Five
files one turn, a ``server.log`` another.

These run the arming in a subprocess, because it patches ``builtins.open`` for
the whole process and a test that did it in-process would be confining pytest
itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

REPO = Path(__file__).resolve().parents[1]


def _run(body: str, *, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    script = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, REPO)
        sys.path.insert(0, SRC)
        """
    ).replace("REPO", repr(str(REPO))).replace(
        "SRC", repr(str(REPO / "src"))
    ) + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


@pytest.mark.real_actions(
    reason="runs a subprocess that arms the guard and tries to write outside its "
    "sandbox; the write is refused, and the sandbox is a temp directory"
)
def test_a_write_outside_the_sandbox_is_refused() -> None:
    proc = _run(
        """
        from pathlib import Path

        from tests.sandbox import arm

        arm()
        target = Path("D:/Grandpa/should-never-exist.txt")
        try:
            target.write_text("x", encoding="utf-8")
        except BaseException as exc:
            print("REFUSED:" + type(exc).__name__)
        else:
            print("WROTE IT")
        """
    )

    assert "REFUSED:ActuationDenied" in proc.stdout, proc.stdout + proc.stderr
    assert not Path("D:/Grandpa/should-never-exist.txt").exists()


@pytest.mark.real_actions(
    reason="runs a subprocess that arms the guard and writes inside its own "
    "sandbox, which must be allowed; everything is under a temp directory"
)
def test_a_write_inside_the_sandbox_is_allowed() -> None:
    proc = _run(
        """
        from pathlib import Path

        from tests.sandbox import arm

        root = arm()
        (root / "note.txt").write_text("fine", encoding="utf-8")
        print("SANDBOX:" + str(root))
        print("WROTE:" + (root / "note.txt").read_text(encoding="utf-8"))
        """
    )

    assert "WROTE:fine" in proc.stdout, proc.stdout + proc.stderr


@pytest.mark.real_actions(
    reason="runs a subprocess that arms the guard and then imports grandpa, to "
    "check GRANDPA_HOME points into the sandbox; writes only under a temp dir"
)
def test_arming_points_grandpa_home_into_the_sandbox() -> None:
    """The reason arming comes first: paths must land inside, not be refused."""
    proc = _run(
        """
        from tests.sandbox import arm

        root = arm()
        from grandpa.runtime_paths import grandpa_home, runtime_path

        home = grandpa_home()
        knowledge = runtime_path("knowledge")
        print("HOME_INSIDE:" + str(home.is_relative_to(root)))
        print("KNOWLEDGE_INSIDE:" + str(knowledge.is_relative_to(root)))
        """
    )

    assert "HOME_INSIDE:True" in proc.stdout, proc.stdout + proc.stderr
    assert "KNOWLEDGE_INSIDE:True" in proc.stdout, proc.stdout + proc.stderr


@pytest.mark.real_actions(
    reason="runs a subprocess that arms twice to check the second is a no-op; "
    "writes only under a temp directory"
)
def test_arming_twice_is_harmless() -> None:
    """A probe that arms, then imports something that also arms, must not break."""
    proc = _run(
        """
        from tests.sandbox import arm, armed

        first = arm()
        second = arm()
        print("SAME:" + str(first == second))
        print("ARMED:" + str(armed()))
        """
    )

    assert "SAME:True" in proc.stdout, proc.stdout + proc.stderr
    assert "ARMED:True" in proc.stdout
