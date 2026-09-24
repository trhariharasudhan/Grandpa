"""The generation log goes where GRANDPA_HOME says, not where Path.home() says.

``log_generation_exception`` writes a traceback when generation fails. Its path
was built as ``Path.home() / ".grandpa" / "server.log"``, which ignores
GRANDPA_HOME -- so a test with a mocked engine appended its fake traceback to
the developer's own ~/.grandpa/server.log, which is where this was found. The
write guard did not stop it: the real home is a legitimate place for Grandpa to
write, and nothing said this was a test.

Fixing the one unpatched test would have fixed today's symptom. This is the
cause, so the next test cannot reintroduce it by forgetting to patch.
"""

from __future__ import annotations

from pathlib import Path

from grandpa.engine.messages import _generation_log_path, log_generation_exception


def test_the_log_path_follows_grandpa_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "home"))

    assert _generation_log_path() == tmp_path / "home" / "server.log"


def test_nothing_is_written_outside_grandpa_home(monkeypatch, tmp_path: Path) -> None:
    """The effect, not the path: a real failure lands inside the sandbox."""
    home = tmp_path / "home"
    monkeypatch.setenv("GRANDPA_HOME", str(home))

    try:
        raise RuntimeError("pretend generation failure")
    except RuntimeError as exc:
        log_generation_exception(exc)

    written = home / "server.log"
    assert written.exists(), "the failure was not recorded at all"
    text = written.read_text(encoding="utf-8")
    assert "pretend generation failure" in text
    assert "Chat generation failed" in text


def test_it_does_not_fall_back_to_the_users_home(monkeypatch, tmp_path: Path) -> None:
    """A moved HOME must not drag the log back to ``~/.grandpa``.

    This is the assertion that fails if the path goes back to being built from
    ``Path.home()``: with GRANDPA_HOME set, the user's home is not involved.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "home"))

    resolved = _generation_log_path()

    assert resolved == tmp_path / "home" / "server.log"
    assert (tmp_path / "elsewhere") not in resolved.parents
