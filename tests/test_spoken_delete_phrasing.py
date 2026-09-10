"""A spoken file deletion has to survive the words people actually use.

"delete the file report.pdf" reached the file layer and then failed, because
``FileParser._parse_delete`` matched ``(?:delete|remove) (.+)`` and kept the
noun phrase in the filename -- it looked for a file literally called "the file
report.pdf". Every other verb in that parser already strips it:
``_parse_move`` matches ``move(?: folder| file)? (.+?) to (.+)``. Delete was
the one that did not.

So the routing was never the problem for these phrasings.
``_looks_like_file_operator_command`` already admits "delete file ", "delete
the file ", "delete folder " and "delete the folder "; they arrived and were
then mis-parsed.

**Bare ``delete <name>`` is now routed too**, which it was not when this file
was written. Admitting "delete " to the gate does let phrases meant for another
domain reach the file layer -- "delete that email", "delete this reminder",
"delete my downloads" -- and two things already in the chain contain that: the
notes, calendar and downloads parsers are matched earlier and keep their own
phrases, and no delete acts without a confirmation naming the resolved path, so
a wrong match ends as a question rather than as a deletion. Both are held by
tests below. A filename discriminator was never an option: the voice normaliser
strips punctuation, so ``report.pdf`` is already ``report pdf`` by the time
routing sees it.

Nothing here deletes anything: the mutation runner is injected and the real
actuator is made to raise.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from grandpa import pc_control
from grandpa.files.parser import FileParser
from grandpa.pc_control import _coerce_request
from grandpa.voice.operator import (
    _looks_like_file_operator_command,
    parse_voice_operator_command,
)

#: Phrasings the routing gate already admits, which must now parse correctly.
DELETE_PHRASINGS = (
    ("delete report.pdf", "report.pdf"),
    ("delete file report.pdf", "report.pdf"),
    ("delete the file report.pdf", "report.pdf"),
    ("delete folder archive", "archive"),
    ("delete the folder archive", "archive"),
    ("remove report.pdf", "report.pdf"),
    ("remove file report.pdf", "report.pdf"),
    ("remove the file report.pdf", "report.pdf"),
    ("remove folder archive", "archive"),
    ("remove the folder archive", "archive"),
)

#: Phrasings that must keep meaning exactly what they meant before.
UNCHANGED = (
    ("delete the report", "the report"),
    ("delete file", "file"),
    ("delete folder", "folder"),
    ("delete my notes", "my notes"),
    ("remove the backup", "the backup"),
)


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


class TestDeletePhrasingIsUnderstood:
    @pytest.mark.parametrize(("phrase", "expected"), DELETE_PHRASINGS)
    def test_the_filename_is_extracted_without_the_noun_phrase(self, phrase, expected):
        action = FileParser().parse(phrase)

        assert action is not None, f"{phrase!r} did not parse as a file command"
        assert action.action == "delete"
        assert action.source == expected

    @pytest.mark.parametrize(("phrase", "expected"), UNCHANGED)
    def test_ordinary_targets_are_left_exactly_as_spoken(self, phrase, expected):
        """The noun is stripped only when it is actually the noun.

        "delete the report" means a file called "the report" as far as this
        parser is concerned, and must keep meaning that -- only "the file" and
        "the folder" are treated as words about the target rather than part of
        it.
        """
        action = FileParser().parse(phrase)

        assert action is not None
        assert action.source == expected

    def test_it_matches_the_idiom_move_already_uses(self):
        """``_parse_move`` has stripped this noun phrase all along."""
        move = FileParser().parse("move file report.pdf to archive")

        assert move is not None
        assert move.source == "report.pdf"

    def test_a_file_named_like_the_noun_still_works(self):
        """A file genuinely called "file" is not swallowed by the pattern."""
        action = FileParser().parse("delete file file")

        assert action is not None
        assert action.source == "file"


class RecordingRunner:
    def __init__(self, *, status: str = "completed") -> None:
        self.payloads: list[dict[str, Any]] = []
        self.status = status

    def __call__(self, payload: dict[str, Any]):
        self.payloads.append(dict(payload))
        return pc_control.LocalActionResponse(
            ok=self.status == "completed",
            action_id=None,
            status=self.status,
            message="Done.",
            approval_required=self.status == "approval_required",
            risk_level="HIGH",
            evidence={"path": payload.get("target", "")},
        )

    @property
    def action_types(self) -> list[str]:
        return [p.get("action_type") for p in self.payloads]

    @property
    def origins(self) -> list[str]:
        return [_coerce_request(p).origin for p in self.payloads]


@pytest.fixture
def no_real_actuator(monkeypatch):
    def explode(payload):
        raise AssertionError(f"the real actuator was reached with {payload!r}")

    monkeypatch.setattr(pc_control, "run_local_action", explode)


@pytest.fixture
def no_direct_mutation(monkeypatch):
    def refuse(name):
        def _refuse(*args, **kwargs):
            raise AssertionError(f"{name} ran instead of the actuator")

        return _refuse

    monkeypatch.setattr(shutil, "rmtree", refuse("shutil.rmtree"))
    monkeypatch.setattr(Path, "unlink", refuse("Path.unlink"))


@pytest.fixture
def confined_roots(tmp_path, monkeypatch):
    import grandpa.files.executor as file_executor

    monkeypatch.setattr(file_executor, "safe_roots", lambda: (tmp_path,))
    return tmp_path


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class TestRouting:
    """Routing, including the fixtures the wrong-target cases need."""

    @pytest.mark.parametrize(("phrase", "_expected"), DELETE_PHRASINGS)
    def test_every_supported_phrasing_reaches_the_file_layer(self, phrase, _expected):
        intent = parse_voice_operator_command(phrase)

        assert intent.kind == "file_automation"
        assert intent.action == "delete"

    @pytest.mark.parametrize(("phrase", "expected"), DELETE_PHRASINGS)
    def test_the_intent_carries_the_target_without_the_noun_phrase(
        self, phrase, expected
    ):
        """What this slice fixes: "the file" is gone from the target.

        The target is compared after the voice normaliser has run, which drops
        punctuation -- see ``test_the_voice_layer_drops_punctuation`` below.
        The defect being fixed is the noun phrase, not the dot.
        """
        intent = parse_voice_operator_command(phrase)

        assert intent.target == expected.replace(".", " ")
        assert "the file" not in intent.target
        assert not intent.target.startswith("file ")

    def test_the_voice_layer_drops_punctuation(self):
        """Pre-existing and pinned, because it shapes every assertion here.

        ``normalize_voice_operator_transcript`` strips punctuation, so this
        layer addresses files by fuzzy name against its roots rather than by
        literal filename. It is why "move report.pdf to archive" has always
        worked, and it is not something this slice changes.
        """
        from grandpa.voice.operator import normalize_voice_operator_transcript

        assert normalize_voice_operator_transcript("delete report.pdf") == (
            "delete report pdf"
        )

    def test_the_file_parser_itself_keeps_the_extension(self):
        """Below the voice layer the filename is intact."""
        action = FileParser().parse("delete the file report.pdf")

        assert action.source == "report.pdf"

    @pytest.mark.parametrize(("phrase", "_expected"), DELETE_PHRASINGS)
    def test_a_spoken_delete_asks_before_it_acts(self, phrase, _expected):
        """Deleting is the one file verb the operator flags for confirmation."""
        intent = parse_voice_operator_command(phrase)

        assert intent.requires_confirmation is True

    @pytest.mark.parametrize(
        "phrase",
        ["delete note groceries", "delete the meeting tomorrow"],
    )
    def test_other_domains_still_claim_their_own_deletes(self, phrase):
        """Notes and calendar are matched before the file gate and stay theirs."""
        intent = parse_voice_operator_command(phrase)

        assert intent.kind in {"notes", "calendar"}

    @pytest.mark.parametrize(
        "phrase",
        ["delete that email", "delete this reminder"],
    )
    def test_a_delete_the_file_layer_cannot_place_is_still_confirmation_gated(
        self, phrase
    ):
        """Bare "delete X" now reaches the file layer, which widens what it
        claims -- so the thing that protects the user is that no delete acts
        without confirmation naming the resolved path first.

        A phrase meant for another domain therefore ends as a question about a
        file, not as a deletion.

        Asserted unconditionally. This was written as ``if intent.kind ==
        "file_automation"``, which meant it stopped checking anything the
        moment routing changed -- the one circumstance in which it most needed
        to speak up. There is no email or reminder parser earlier in the chain,
        so these really do land on the file layer today; if that ever stops
        being true, this should fail and be re-read rather than pass in
        silence.
        """
        intent = parse_voice_operator_command(phrase)

        assert intent.kind == "file_automation"
        assert intent.requires_confirmation is True

    def test_a_bare_delete_of_something_absent_never_reaches_the_actuator(
        self, confined_roots, no_real_actuator, no_direct_mutation
    ):
        """The wrong-target case: nothing is offered, nothing is run."""
        from grandpa.files.executor import FileExecutor

        runner = RecordingRunner()

        result = FileExecutor(mutation_runner=runner, origin="voice").execute(
            FileParser().parse("delete that email"),
            confirm=lambda *args: True,
        )

        assert runner.payloads == []
        assert result.status != "handled"

    def test_downloads_still_claims_its_own_delete(self):
        """A domain parser earlier in the chain keeps its phrase."""
        intent = parse_voice_operator_command("delete downloads older than 30 days")

        assert intent.kind == "downloads"


class TestTheOpenDiscriminator:
    """ "open X" is the one place the routing gate's *refusal* decides anything.

    Everywhere else the gate can over-claim harmlessly: it is a pre-filter, not
    a boundary. A hit is followed by ``FileParser().parse``, and a phrase the
    parser declines falls through to the rest of the chain -- while the notes,
    calendar and downloads parsers run earlier still and keep their phrases
    regardless. Making the gate answer True for everything changes almost
    nothing.

    "open X" is the exception. Nothing else separates "open report.pdf" from
    "open chrome", so if this refusal goes, launching an application becomes an
    attempt to open a file by that name.

    One wrinkle worth stating: the voice normaliser strips punctuation, so by
    the time a spoken "open report.pdf" reaches the gate it is already "open
    report pdf" and the dot is gone. Through that path it is the separators
    that carry a filename. The dot still matters for a typed command, which is
    why both are pinned here.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "open report.pdf",
            "open notes.txt",
            "open c:/users/me/report.pdf",
            "open c:\\users\\me\\notes.txt",
            "open /home/me/a.txt",
            "open downloads/report pdf",
        ],
    )
    def test_a_path_or_filename_is_a_file_command(self, command):
        assert _looks_like_file_operator_command(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "open chrome",
            "open notepad",
            "open task manager",
            "open youtube",
            "open calculator",
        ],
    )
    def test_an_application_name_is_not(self, command):
        """The refusal that keeps an app launch out of the file layer."""
        assert _looks_like_file_operator_command(command) is False

    def test_the_gate_does_not_simply_claim_everything(self):
        """The narrowest statement of the above, and the one that fails first
        if the discriminator is ever dropped."""
        assert _looks_like_file_operator_command("open chrome") is False
        assert _looks_like_file_operator_command("open c:/tmp/a.txt") is True

    def test_a_spoken_app_launch_still_reaches_the_launcher(self):
        """The consequence, end to end: routing, not just the predicate."""
        assert parse_voice_operator_command("open chrome").kind == "local_action"


# ---------------------------------------------------------------------------
# The safety chain is unchanged
# ---------------------------------------------------------------------------


class TestSafetyChainPreserved:
    def test_a_parsed_delete_still_routes_through_the_boundary(
        self, confined_roots, no_real_actuator, no_direct_mutation
    ):
        """The A1-safe mutation boundary, reached by the fixed phrasing."""
        from grandpa.files.executor import FileExecutor

        victim = confined_roots / "report.pdf"
        victim.write_text("x", encoding="utf-8")
        runner = RecordingRunner()

        result = FileExecutor(mutation_runner=runner, origin="voice").execute(
            FileParser().parse("delete the file report.pdf"),
            confirm=lambda *args: True,
        )

        assert runner.action_types == ["file_delete"]
        assert runner.origins == ["voice"]
        assert result.status == "handled"
        assert victim.exists(), "the legacy path deleted the file itself"

    def test_confirmation_is_still_required_first(
        self, confined_roots, no_real_actuator, no_direct_mutation
    ):
        from grandpa.files.executor import FileExecutor

        (confined_roots / "report.pdf").write_text("x", encoding="utf-8")
        runner = RecordingRunner()

        result = FileExecutor(mutation_runner=runner, origin="voice").execute(
            FileParser().parse("delete the file report.pdf")
        )

        assert runner.payloads == []
        assert result.requires_confirmation is True

    def test_the_recursive_delete_guard_still_refuses_first(
        self, confined_roots, monkeypatch, no_real_actuator, no_direct_mutation
    ):
        from grandpa.files.executor import FileExecutor
        from grandpa.files.safety import FileSafetyPolicy

        monkeypatch.setattr(
            FileSafetyPolicy, "blocks_recursive_delete", lambda self, path: True
        )
        folder = confined_roots / "archive"
        folder.mkdir()
        runner = RecordingRunner()

        result = FileExecutor(mutation_runner=runner, origin="voice").execute(
            FileParser().parse("delete the folder archive"),
            confirm=lambda *args: True,
        )

        assert runner.payloads == [], "a blocked delete reached the actuator"
        assert result.status == "blocked"
        assert folder.exists()

    def test_a_protected_path_is_still_blocked_at_the_boundary(
        self, monkeypatch, tmp_path
    ):
        """The pc_control preflight is unchanged by any of this."""
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
        )
        monkeypatch.setattr(pc_control, "_is_protected_path", lambda path: True)

        response = pc_control.run_local_action(
            {"action_type": "file_delete", "target": str(tmp_path / "report.pdf")}
        )

        assert response.status == "blocked"
        assert response.error == "protected_path"

    def test_the_delete_action_is_still_high_risk(self):
        assert "file_delete" in pc_control.HIGH_RISK_ACTIONS
        assert "file_permanent_delete" in pc_control.BLOCKED_ACTIONS

    def test_a_dangerous_phrase_is_still_blocked_before_any_parsing(self):
        """The safety check runs ahead of the file gate and still wins."""
        assert parse_voice_operator_command("delete all my files").kind == "blocked"

    def test_dry_run_reaches_the_runner_without_touching_the_disk(
        self, confined_roots, no_real_actuator, no_direct_mutation
    ):
        from grandpa.files.executor import FileExecutor

        victim = confined_roots / "report.pdf"
        victim.write_text("x", encoding="utf-8")
        runner = RecordingRunner()

        FileExecutor(mutation_runner=runner, origin="voice", dry_run=True).execute(
            FileParser().parse("delete the file report.pdf"),
            confirm=lambda *args: True,
        )

        assert runner.payloads and runner.payloads[0]["dry_run"] is True
        assert victim.exists()


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_no_other_verb_changed(self):
        parser = FileParser()

        assert parser.parse("move report.pdf to archive").action == "move"
        assert parser.parse("copy report.pdf to archive").action == "copy"
        assert parser.parse("create folder reports").action == "create_folder"
        assert parser.parse("find report.pdf").action == "search"

    def test_the_read_only_actions_are_untouched(self):
        """This slice changed nothing about which actions route.

        It once read "search, properties, create_folder and copy stay with the
        kernel". Two of those since moved: ``create_folder`` and ``copy``
        mutate the filesystem and now route through the boundary when a runner
        is supplied. ``search`` and ``properties`` mutate nothing, so they have
        no mutation to route and remain outside it -- which is the part this
        test was really guarding, and the part that still holds.
        """
        from grandpa.files.executor import BOUNDARY_ROUTED_ACTIONS

        assert "delete" in BOUNDARY_ROUTED_ACTIONS
        assert not BOUNDARY_ROUTED_ACTIONS & {"search", "properties"}

    def test_no_new_action_type(self):
        action = FileParser().parse("delete the file report.pdf")

        assert action.action == "delete"
