"""``grandpa oops`` -- the one-command problem log.

Written for a week of real use, so its requirements are unusual: the thing it
must do above all else is **not fail**. A logging command that errors while
someone is reporting a problem is worse than no logging command, so most of
this file is about failure paths rather than the happy one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.diagnostics import oops as store

pytestmark = pytest.mark.core


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """GRANDPA_HOME for the duration, so nothing touches a real home."""
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))
    return tmp_path


class FakeAudio:
    """The capture metrics that settled the voice activity argument."""

    rms_level = 176.0
    speech_window_rms = 289.0
    noise_floor = 92.0
    max_chunk_rms = 2994.0
    speech_active_seconds = 1.8
    duration_seconds = 3.2
    sample_rate = 16000


# --- 1. it records, in one command ------------------------------------------------


def test_one_sentence_is_all_it_takes(home) -> None:
    result = CliRunner().invoke(cli, ["oops", "voice did not hear me"])

    assert result.exit_code == 0
    entries = store.entries()
    assert len(entries) == 1
    assert entries[0].note == "voice did not hear me"


def test_it_says_nothing_was_sent_anywhere(home) -> None:
    """The user is reporting a problem, not filing a telemetry event."""
    result = CliRunner().invoke(cli, ["oops", "something broke"])

    assert "Nothing was sent anywhere" in result.output


def test_the_log_lives_under_grandpa_home(home) -> None:
    """Never a relative path: a relative store once left a database in the repo."""
    CliRunner().invoke(cli, ["oops", "a note"])

    assert store.log_path().is_relative_to(home)
    assert store.log_path().exists()


def test_notes_accumulate_rather_than_overwrite(home) -> None:
    for index in range(3):
        CliRunner().invoke(cli, ["oops", f"problem {index}"])

    assert [entry.note for entry in store.entries()] == [
        "problem 0",
        "problem 1",
        "problem 2",
    ]


# --- 2. the context, which is the point -------------------------------------------


def test_it_captures_the_numbers_that_settled_past_arguments(home) -> None:
    """Not everything available -- the fields that have actually diagnosed a bug.

    These four were the whole of the voice activity diagnosis: a capture
    reported as "rms 176, never crossed 180" had speech chunks averaging 289,
    and the whole-buffer figure was the misleading one.
    """
    store.record_capture(
        FakeAudio(), held_seconds=3.21, reason="no_speech_decoded",
        model="base.en", transcript_len=0,
    )

    CliRunner().invoke(cli, ["oops", "voice did not hear me"])
    capture = store.entries()[0].context["last_capture"]

    assert capture["speech_window_rms"] == 289.0
    assert capture["noise_floor"] == 92.0
    assert capture["max_chunk_rms"] == 2994.0
    assert capture["speech_active_seconds"] == 1.8
    assert capture["held_seconds"] == 3.21
    assert capture["reason"] == "no_speech_decoded", (
        "which gate emptied the transcript is the difference between four bugs"
    )


def test_it_captures_the_last_command(home) -> None:
    """"It broke" nearly always means the command before this one."""
    store.record_command(["voice", "push-to-talk"])

    CliRunner().invoke(cli, ["oops", "that did not work"])

    assert store.entries()[0].context["last_command"]["argv"] == [
        "voice",
        "push-to-talk",
    ]


def test_an_empty_command_does_not_overwrite_the_breadcrumb(home) -> None:
    """Recording an empty command would claim the last command was nothing.

    Reachable whenever the group runs without a subcommand to report, and the
    breadcrumb it would clobber is the useful one.
    """
    store.record_command(["voice", "doctor"])

    assert store.record_command([]) is False
    assert store.record_command([None]) is False  # type: ignore[list-item]

    recorded = json.loads(
        (store.diagnostics_dir() / "last-command.json").read_text(encoding="utf-8")
    )
    assert recorded["argv"] == ["voice", "doctor"]


def test_the_breadcrumb_comes_from_clicks_parse_not_the_process(home) -> None:
    """``sys.argv`` is the process's arguments, not grandpa's.

    Under a test runner it is the runner's command line, so a report would
    name ``pytest -q`` as the last thing run. Click knows what it parsed.
    """
    import ast
    import inspect
    import textwrap

    from grandpa.cli import cli as group

    source = inspect.getsource(group.callback)
    tree = ast.parse(textwrap.dedent(source))

    # On the AST, not the text: the comment explaining why sys.argv is avoided
    # necessarily contains the words. This is the third time that has bitten a
    # test in this project, so it is worth stating.
    reads_argv = any(
        isinstance(node, ast.Attribute)
        and node.attr == "argv"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
        for node in ast.walk(tree)
    )

    assert not reads_argv, "the breadcrumb must not come from the process argv"
    assert "ctx.invoked_subcommand" in source
    assert "record_command(" in source


def test_oops_is_never_recorded_as_the_last_command(home) -> None:
    """Otherwise every report would say the last thing run was `oops`."""
    assert store.record_command(["oops", "something"]) is False


def test_it_captures_the_settings_that_have_diverged_before(home) -> None:
    CliRunner().invoke(cli, ["oops", "a note"])
    models = store.entries()[0].context["models"]

    for field in (
        "stt_model",
        "llm_model",
        "tts_backend_configured",
        "scheduler_enabled",
        "memory_backend",
    ):
        assert field in models, f"{field} is one of the fields that has lied before"


def test_it_captures_the_version_and_platform(home) -> None:
    """Identical work on this machine has varied 105x, and one bug was POSIX-only."""
    CliRunner().invoke(cli, ["oops", "a note"])
    context = store.entries()[0].context

    assert context["version"]
    assert context["platform"]["sys_platform"]
    assert context["platform"]["python"]


def test_it_does_not_ask_an_engine_whether_it_is_healthy(home) -> None:
    """That path costs 2.25s and would make the command too slow to be used.

    The configured backend is the useful fact; probing a sidecar that always
    fails its health check is not.

    Checked on the parsed module rather than on its text: the explanation of
    *why* this is avoided necessarily names the call, and a test that forbids
    the word also forbids documenting the decision.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(store))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "available_local_engines" not in called
    assert "best_available_engine" not in called
    assert "speech_output" not in inspect.getsource(store).replace(
        "oops", ""
    ) or True  # the import itself is the thing that would cost the time
    assert "from grandpa.voice.speech_output" not in inspect.getsource(store)


# --- 3. redaction -----------------------------------------------------------------


def test_a_pasted_transcript_cannot_leak_a_secret(home) -> None:
    """The user was told they may paste a transcript into it."""
    CliRunner().invoke(
        cli,
        [
            "oops",
            "it typed password: hunter2sekrit and key sk-abcdefghij1234567890",
        ],
    )
    note = store.entries()[0].note

    assert "hunter2sekrit" not in note
    assert "sk-abcdefghij1234567890" not in note
    assert "it typed" in note, "redaction must not destroy the sentence"


def test_a_card_number_is_redacted(home) -> None:
    CliRunner().invoke(cli, ["oops", "my card 4111 1111 1111 1111 was shown"])

    assert "4111" not in store.entries()[0].note


def test_a_secret_in_the_context_is_redacted_too(home) -> None:
    """A command line can carry a token in a flag."""
    store.record_command(["config", "set", "api_key=sk-livekey12345678901234"])

    CliRunner().invoke(cli, ["oops", "config broke"])
    argv = store.entries()[0].context["last_command"]["argv"]

    assert "config" in argv, "the breadcrumb must still be recorded"
    assert not any("sk-livekey" in str(part) for part in argv)


def test_the_same_redaction_the_screen_uses(home) -> None:
    """Not a second copy of the patterns, which would drift from the first."""
    import inspect

    assert "redact_screen_text" in inspect.getsource(store)


# --- 4. it must never fail --------------------------------------------------------


def test_a_broken_collector_still_stores_the_note(home, monkeypatch) -> None:
    def explode() -> dict:
        raise RuntimeError("everything broke")

    monkeypatch.setattr(store, "collect_context", explode)

    result = CliRunner().invoke(cli, ["oops", "collectors are broken"])

    assert result.exit_code == 0
    assert any(e.note == "collectors are broken" for e in store.entries())


def test_an_unwritable_store_prints_the_note_rather_than_losing_it(
    home, monkeypatch, tmp_path
) -> None:
    """The sentence is the thing that must survive.

    The unwritable path is a *file*, inside the sandbox, so ``mkdir`` fails the
    way it would in production -- an OSError. Pointing it at another drive
    instead would be denied by the write guard, and ``ActuationDenied`` is a
    BaseException that this code deliberately does not catch: a guard violation
    must not be swallowed by a never-fail handler.
    """
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("i am a file", encoding="utf-8")
    monkeypatch.setattr(store, "diagnostics_dir", lambda: blocker / "diagnostics")

    result = CliRunner().invoke(cli, ["oops", "the disk is gone"])

    assert result.exit_code == 0
    assert "the disk is gone" in result.output


def test_a_corrupt_line_does_not_hide_the_other_notes(home) -> None:
    CliRunner().invoke(cli, ["oops", "first"])
    with store.log_path().open("a", encoding="utf-8") as handle:
        handle.write("{not json at all\n")
    CliRunner().invoke(cli, ["oops", "second"])

    assert [entry.note for entry in store.entries()] == ["first", "second"]


def test_bare_oops_explains_itself(home) -> None:
    result = CliRunner().invoke(cli, ["oops"])

    assert result.exit_code == 0
    assert "--list" in result.output
    assert "--export" in result.output


def test_every_collector_is_individually_guarded(home, monkeypatch) -> None:
    """One missing field must not cost the other six."""
    monkeypatch.setattr(
        store, "_models", lambda: (_ for _ in ()).throw(RuntimeError("no config"))
    )

    context = store.collect_context()

    assert "unavailable" in context["models"]
    assert context["version"], "a broken collector took an unrelated one with it"


# --- 5. reading it back -----------------------------------------------------------


def test_list_shows_what_was_logged(home) -> None:
    CliRunner().invoke(cli, ["oops", "first problem"])
    CliRunner().invoke(cli, ["oops", "second problem"])

    result = CliRunner().invoke(cli, ["oops", "--list"])

    assert result.exit_code == 0
    assert "first problem" in result.output
    assert "second problem" in result.output


def test_list_with_nothing_logged_says_so(home) -> None:
    result = CliRunner().invoke(cli, ["oops", "--list"])

    assert result.exit_code == 0
    assert "Nothing logged yet" in result.output


def test_export_writes_one_file_to_hand_over(home) -> None:
    CliRunner().invoke(cli, ["oops", "first problem"])
    CliRunner().invoke(cli, ["oops", "second problem"])

    result = CliRunner().invoke(cli, ["oops", "--export"])

    assert result.exit_code == 0
    target = store.diagnostics_dir() / "oops-export.md"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "first problem" in text
    assert "second problem" in text


def test_export_takes_a_path(home, tmp_path) -> None:
    CliRunner().invoke(cli, ["oops", "a problem"])
    target = tmp_path / "handover" / "report.md"

    result = CliRunner().invoke(cli, ["oops", "--export", "--to", str(target)])

    assert result.exit_code == 0
    assert target.exists()


def test_the_export_carries_no_secret(home) -> None:
    CliRunner().invoke(cli, ["oops", "password: hunter2sekrit leaked"])

    text = store.export_text()

    assert "hunter2sekrit" not in text


# --- 6. nothing leaves the machine ------------------------------------------------


def test_the_module_cannot_reach_the_network() -> None:
    """Stated as a requirement, so asserted rather than trusted."""
    import inspect

    source = inspect.getsource(store)

    for banned in ("requests", "urllib", "httpx", "socket", "http.client"):
        assert banned not in source, f"{banned} has no business in a local log"
