"""Regression tests for the Voice Operator *production entry point*.

``process_voice_operator_turn`` (voice/operator.py:952) is what the shipped CLI
actually runs: ``grandpa voice-operator`` -> ``run_voice_operator_loop``
(:1164) -> ``VoiceOperatorResponder.handle_user_input`` (:941) -> here.

Every other voice test in this repository targets
``parse_voice_operator_command`` instead -- 92 references across the suite
against **zero** for the turn function. The parser is therefore exhaustively
covered while the function the product runs is not covered at all, which is why
the routing defects below survive a green suite: they live in the turn
function's pre-routing, above the parser, and the parser tests can never see
them.

These tests are hermetic by construction. Both side-effecting collaborators are
injected -- ``action_runner`` replaces ``run_local_action`` and
``automation_service`` replaces ``ScreenAutomationService`` -- so nothing here
launches an app, presses a key, or touches a window. They need no microphone,
no Ollama, no network, and no ambient application state.

The greeting branch they exercise (agent/runtime.py:175-185) returns a
hardcoded string and never reaches an engine, so no LLM is required either.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from grandpa.voice.operator import process_voice_operator_turn


class RecordingRunner:
    """Stands in for ``run_local_action`` and records what it was asked to do.

    Returning a ``LocalActionResponse``-shaped object (pc_control.py:226) keeps
    the turn function on its normal success path, so the assertions are about
    routing rather than about error handling.
    """

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]) -> SimpleNamespace:
        self.payloads.append(dict(payload))
        return SimpleNamespace(
            ok=True,
            action_id=None,
            status="completed",
            message="recorded",
            approval_required=False,
            risk_level="LOW",
            evidence={},
            error=None,
            data={},
            to_dict=lambda: {"status": "completed"},
        )

    @property
    def action_types(self) -> list[str]:
        return [p.get("action_type", "") for p in self.payloads]


class RecordingAutomation:
    """Stands in for ``ScreenAutomationService``; records the command string.

    The turn function re-serialises its structured intent back into text via
    ``_automation_command_from_intent`` (:1389) before handing it here, so the
    recorded string is what the screen-automation layer would have parsed.
    """

    def __init__(self) -> None:
        self.commands: list[str] = []

    def has_pending_confirmation(self) -> bool:
        return False

    def has_pending_window_choice(self) -> bool:
        return False

    def has_pending_dialog(self) -> bool:
        return False

    def handle(self, command: str, dry_run: bool = False) -> SimpleNamespace:
        self.commands.append(command)
        return SimpleNamespace(
            status="handled",
            message=f"recorded: {command}",
            data={},
            confirmation_token=None,
        )


def _turn(text: str):
    """Run one real turn with both side-effecting collaborators recorded."""
    runner = RecordingRunner()
    automation = RecordingAutomation()
    response = process_voice_operator_turn(
        text,
        dry_run=True,
        action_runner=runner,
        automation_service=automation,
    )
    return response, runner, automation


# ---------------------------------------------------------------------------
# Control cases -- these already pass and must keep passing.
# ---------------------------------------------------------------------------


class TestDeviceCommandsReachTheActuator:
    def test_open_app_reaches_the_action_runner(self):
        _response, runner, _automation = _turn("open notepad")

        assert "open_app" in runner.action_types
        assert runner.payloads[0]["target"] == "notepad"

    def test_hotkey_reaches_the_automation_service(self):
        _response, _runner, automation = _turn("press enter")

        assert automation.commands == ["press enter"]

    def test_window_command_reaches_the_action_runner(self):
        _response, runner, _automation = _turn("maximize this window")

        assert "maximize_window" in runner.action_types


# ---------------------------------------------------------------------------
# P0-1: conversational classification hijacks device commands
# ---------------------------------------------------------------------------


class TestGreetingClassificationDoesNotHijackDeviceCommands:
    """``classify_intent`` runs before the device parser and wins.

    voice/operator.py:1041 calls ``classify_intent`` on the raw transcript and
    :1043-1051 diverts seven conversational intents into ``AgentRuntime``,
    returning at :1061. The device parser at :1082 is reached only if that
    branch declines.

    ``classify_intent`` matches greeting words anywhere in the utterance, so a
    literal device command that happens to contain one is answered with a
    chat greeting and **no actuator is invoked at all**. The user hears a
    friendly reply and nothing happens.
    """

    def test_type_hello_world_types_instead_of_greeting(self):
        response, runner, automation = _turn("type hello world")

        assert automation.commands or runner.payloads, (
            "no actuator was invoked; the command was answered conversationally: "
            f"{response.text!r}"
        )
        assert "type hello world" in automation.commands

    def test_type_hello_world_does_not_return_a_greeting(self):
        response, _runner, _automation = _turn("type hello world")

        assert "I am Grandpa" not in response.text

    @pytest.mark.parametrize(
        "command",
        [
            "type hello world",
            "type hi there",
            "type good morning team",
            "type hey can we meet",
        ],
    )
    def test_type_commands_containing_greeting_words_still_type(self, command):
        _response, runner, automation = _turn(command)

        assert automation.commands or runner.payloads, (
            f"{command!r} invoked no actuator"
        )

    @pytest.mark.parametrize(
        "command",
        ["open hello.txt", "search for hello.txt"],
    )
    def test_file_commands_containing_greeting_words_are_not_hijacked(self, command):
        """These route into the file layer, which resolves paths internally.

        Unlike app and hotkey commands they do not necessarily pass through the
        injected runner or automation service, so the property asserted here is
        the routing outcome itself: a file command must not be answered with a
        chat greeting. "No matching files found." is a correct file-layer reply;
        "Hello! I am Grandpa" is the hijack this guards against.
        """
        response, _runner, _automation = _turn(command)

        assert "I am Grandpa" not in response.text, (
            f"{command!r} was answered conversationally: {response.text!r}"
        )

    def test_greeting_alone_is_still_conversational(self):
        """The fix must not break real greetings -- this is the guard rail."""
        _response, runner, automation = _turn("hello")

        assert not runner.payloads
        assert not automation.commands


# ---------------------------------------------------------------------------
# P0-2: filesystem traversal must be bounded
# ---------------------------------------------------------------------------


def _build_tree(root, *, depth: int, files_per_dir: int) -> None:
    """Create a deterministic nested tree for traversal-bound assertions."""
    current = root
    for level in range(depth):
        current.mkdir(parents=True, exist_ok=True)
        for index in range(files_per_dir):
            (current / f"f{level}_{index}.txt").write_text("x", encoding="utf-8")
        current = current / f"level{level}"


class TestFilesystemTraversalIsBounded:
    """``_walk`` must not walk a whole safe root when nothing matches.

    ``MAX_SEARCH_RESULTS`` caps how many *matches* are kept, but nothing capped
    how many entries were *examined*, so a filename that does not exist walked
    every root in ``safe_roots()`` -- the whole user profile -- to completion.
    Measured at over 20s before being killed, stack pinned in ``_walk``. It is
    reached from file-argument validation (kernel/files.py:1442 ->
    :300 ``validate_arguments``), so dry runs hung too.

    These assert the ceilings directly, on a synthetic tree under ``tmp_path``,
    so they do not depend on how much is stored on the machine running them.

    Note on scope: an earlier draft of this file asserted that a dry run
    performs *no* traversal. Reading kernel/files.py:1436-1455 shows that is the
    wrong property -- resolution decides whether the source exists, which a dry
    run must still report, and ``validate_arguments`` takes no ``dry_run``
    argument to thread one through. Bounding the traversal fixes the hang for
    dry and real runs alike without restructuring the kernel.
    """

    def test_walk_stops_at_the_entry_ceiling(self, tmp_path):
        from grandpa.files.paths import _walk

        _build_tree(tmp_path / "tree", depth=3, files_per_dir=40)

        entries = list(_walk(tmp_path / "tree", max_entries=25, max_depth=10))

        assert len(entries) == 25

    def test_walk_stops_at_the_depth_ceiling(self, tmp_path):
        from grandpa.files.paths import _walk

        root = tmp_path / "tree"
        _build_tree(root, depth=8, files_per_dir=1)

        entries = list(_walk(root, max_entries=10_000, max_depth=2))

        deepest = max(len(entry.relative_to(root).parts) for entry in entries)
        assert deepest <= 3, f"descended past the depth ceiling: {deepest}"

    def test_walk_is_bounded_by_default(self, tmp_path):
        """The defaults, not just explicit arguments, must bound traversal."""
        from grandpa.files.paths import MAX_SEARCH_DEPTH, MAX_SEARCH_ENTRIES, _walk

        assert MAX_SEARCH_ENTRIES > 0
        assert MAX_SEARCH_DEPTH > 0

        root = tmp_path / "tree"
        _build_tree(root, depth=MAX_SEARCH_DEPTH + 4, files_per_dir=2)

        entries = list(_walk(root))
        deepest = max(len(entry.relative_to(root).parts) for entry in entries)

        assert len(entries) <= MAX_SEARCH_ENTRIES
        assert deepest <= MAX_SEARCH_DEPTH + 1

    def test_missing_file_search_terminates_over_a_controlled_root(
        self, tmp_path, monkeypatch
    ):
        """A query that matches nothing must still finish promptly."""
        import grandpa.files.paths as paths

        root = tmp_path / "tree"
        _build_tree(root, depth=5, files_per_dir=30)
        monkeypatch.setattr(paths, "safe_roots", lambda: (root,))

        examined = {"n": 0}
        real_walk = paths._walk

        def counting_walk(target, **kwargs):
            for entry in real_walk(target, **kwargs):
                examined["n"] += 1
                yield entry

        monkeypatch.setattr(paths, "_walk", counting_walk)

        matches = paths.find_matches("definitely_missing_file_xyz.pdf")

        assert matches == []
        assert examined["n"] <= paths.MAX_SEARCH_ENTRIES

    def test_search_still_finds_a_real_file(self, tmp_path, monkeypatch):
        """The ceilings must not break ordinary search."""
        import grandpa.files.paths as paths

        root = tmp_path / "tree"
        root.mkdir(parents=True)
        (root / "budget.xlsx").write_text("x", encoding="utf-8")
        monkeypatch.setattr(paths, "safe_roots", lambda: (root,))

        matches = paths.find_matches("budget.xlsx")

        assert [match.name for match in matches] == ["budget.xlsx"]
