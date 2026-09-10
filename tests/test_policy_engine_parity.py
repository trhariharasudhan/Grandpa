"""The extracted classifier must decide exactly what the original decides.

Parity is checked by running both over the same generated matrix rather than by
asserting a handful of cases: every action type in the four tier tables, every
key in ``SENSITIVE_APP_RISK``, the alias and raw-name lookups, the
normalisation forms, and the ordinary targets that must stay LOW. If the two
disagree anywhere in that space, the extraction changed behaviour.

The models differ -- the original returns a ``RiskLevel`` string, the extracted
one a ``PolicyDecision`` -- so the mapping is stated explicitly and tested:
``old(request) == new(request).risk_level``. Nothing else about the decision is
claimed to be equivalent, because nothing else existed before.
"""

from __future__ import annotations

import pytest

from grandpa import pc_control
from grandpa.pc_control import LocalActionRequest
from grandpa.policy.engine import RiskTables
from grandpa.policy.engine import classify_risk as policy_classify
from grandpa.policy.models import PolicyRequest


def _tables() -> RiskTables:
    """Exactly the constants ``pc_control`` holds today, passed rather than
    imported by the engine.

    This mirrors ``pc_control._risk_tables()`` and has to be kept in step with
    it: a field missing here does not fail, it silently stops being covered.
    ``TestTheTablesAreMirrored`` guards that.
    """
    from grandpa.desktop.control.applications import SAFE_APP_ALIASES

    return RiskTables(
        blocked=frozenset(pc_control.BLOCKED_ACTIONS),
        high=frozenset(pc_control.HIGH_RISK_ACTIONS),
        medium=frozenset(pc_control.MEDIUM_RISK_ACTIONS),
        low=frozenset(pc_control.LOW_RISK_ACTIONS),
        sensitive_apps=dict(pc_control.SENSITIVE_APP_RISK),
        sensitive_executables=dict(pc_control.SENSITIVE_EXECUTABLE_RISK),
        aliases=dict(SAFE_APP_ALIASES),
        approval_required=frozenset(pc_control.APPROVAL_REQUIRED_ACTIONS),
    )


ALL_ACTIONS = sorted(
    set(pc_control.LOW_RISK_ACTIONS)
    | set(pc_control.MEDIUM_RISK_ACTIONS)
    | set(pc_control.HIGH_RISK_ACTIONS)
    | set(pc_control.BLOCKED_ACTIONS)
)

SENSITIVE_KEYS = sorted(pc_control.SENSITIVE_APP_RISK)


def _matrix() -> list[tuple[str, str]]:
    """(action_type, target) pairs covering every branch of the classifier."""
    cases: list[tuple[str, str]] = []
    cases += [(action, "") for action in ALL_ACTIONS]
    cases += [(action, "chrome") for action in ALL_ACTIONS]
    cases += [("open_app", key) for key in SENSITIVE_KEYS]
    cases += [("open_app", f"  {key.upper()}  ") for key in SENSITIVE_KEYS]
    cases += [("detect_app", key) for key in SENSITIVE_KEYS]
    cases += [
        ("open_app", target)
        for target in (
            "chrome",
            "notepad",
            "calculator",
            "vscode",
            "paint",
            "settings",
            "windows terminal",
            "some-random-app",
            "",
            "cmdr",
            "wtf",
            "regedit viewer",
            "diskpartition",
            "cmd.com",
            "cmd.bat",
            "wsl",
            "git bash",
            "bash",
            "ise",
            "vs",
            "x64",
            "console",
        )
    ]
    cases += [
        (raw, "")
        for raw in (
            "OPEN_APP",
            "  open_app  ",
            "open-app",
            "open app",
            "Open-App",
            "open__app",
            "openapp",
            "no_such_action",
            "",
            "   ",
            "FILE_DELETE",
            "shell-run",
            "Script Run",
        )
    ]
    cases += [
        (action, "regedit") for action in ("focus_window", "close_window", "volume_up")
    ]
    return cases


MATRIX = _matrix()


def _old(action_type: str, target: str) -> str:
    return pc_control.classify_risk(
        LocalActionRequest(action_type=action_type, target=target)
    )


def _new(action_type: str, target: str) -> str:
    return policy_classify(
        PolicyRequest(action_type=action_type, target=target), _tables()
    ).risk_level


class TestDifferentialParity:
    def test_the_matrix_is_large_enough_to_mean_something(self):
        assert len(MATRIX) == 241
        assert len({case[0] for case in MATRIX}) > len(ALL_ACTIONS)
        assert {action for action, _ in MATRIX} >= set(ALL_ACTIONS)

    @pytest.mark.parametrize(("action_type", "target"), MATRIX)
    def test_both_classifiers_agree(self, action_type, target):
        assert _old(action_type, target) == _new(action_type, target)

    def test_every_tier_is_actually_exercised(self):
        """A parity suite that only ever saw LOW would prove very little."""
        seen = {_old(action, target) for action, target in MATRIX}

        assert seen == {"LOW", "MEDIUM", "HIGH", "BLOCKED"}

    def test_the_field_mapping_is_the_only_claim_made(self):
        """The models differ; the equivalence asserted is on risk_level alone."""
        decision = policy_classify(
            PolicyRequest(action_type="open_app", target="terminal"), _tables()
        )

        assert decision.risk_level == _old("open_app", "terminal")
        assert decision.approval_required is False
        assert decision.blocked_reason is None
        assert decision.canonical_target is None


class TestTheTablesAreMirrored:
    """The helper above must carry every field production injects.

    Discovered the hard way: when the executable table was added, this helper
    still built ``RiskTables`` without it, so the parity matrix compared two
    identical tables and reported agreement it had not tested.
    """

    def test_every_injected_field_is_reproduced(self):
        from dataclasses import fields

        live = pc_control._risk_tables()
        mirrored = _tables()

        for f in fields(RiskTables):
            assert getattr(mirrored, f.name) == getattr(live, f.name), f.name


class TestTheTwoTablesAreDisjoint:
    """Nothing is listed as both a name and an executable.

    While that holds, the order of the two lookups cannot change an answer --
    which is why a mutant that swaps them is equivalent rather than uncaught.
    If an entry ever appears in both, the order becomes load-bearing and this
    fails first.
    """

    def test_no_key_appears_in_both_tables(self):
        overlap = set(pc_control.SENSITIVE_APP_RISK) & set(
            pc_control.SENSITIVE_EXECUTABLE_RISK
        )

        assert overlap == set()


class TestExceptionParity:
    def test_both_raise_for_a_request_without_an_action_type(self):
        class Bare:
            target = "x"

        with pytest.raises(AttributeError):
            pc_control.classify_risk(Bare())
        with pytest.raises(AttributeError):
            policy_classify(Bare(), _tables())  # type: ignore[arg-type]

    def test_both_tolerate_a_missing_target(self):
        class NoTarget:
            action_type = "open_app"

        assert pc_control.classify_risk(NoTarget()) == "LOW"
        assert policy_classify(NoTarget(), _tables()).risk_level == "LOW"  # type: ignore[arg-type]


class TestTheEngineStaysPure:
    def test_an_absent_alias_mapping_behaves_like_the_old_import_failure(self):
        """The original wrapped its alias import in ``except Exception`` and
        fell back to the raw name. An empty mapping reproduces *that* path --
        not full behaviour.

        So a name that is itself a table key still resolves, and a name that
        only reached the table through an alias does not. "windows terminal" is
        not a key; it is an alias for "terminal". Under the old import failure
        it would have classified LOW too, which is what makes these equivalent
        rather than merely similar.
        """
        bare = RiskTables(
            low=frozenset({"open_app"}),
            sensitive_apps=dict(pc_control.SENSITIVE_APP_RISK),
        )

        def tier(target: str) -> str:
            return policy_classify(
                PolicyRequest(action_type="open_app", target=target), bare
            ).risk_level

        assert tier("terminal") == "MEDIUM"
        assert tier("wt") == "MEDIUM"
        assert tier("regedit") == "HIGH"
        assert tier("windows terminal") == "LOW"
        assert "windows terminal" not in pc_control.SENSITIVE_APP_RISK

    def test_empty_tables_deny_by_default(self):
        decision = policy_classify(PolicyRequest(action_type="open_app"), RiskTables())

        assert decision.risk_level == "BLOCKED"

    def test_the_engine_imports_nothing_it_should_not(self):
        import ast
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "grandpa"
            / "policy"
            / "engine.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)

        assert modules == {
            "__future__",
            "collections.abc",
            "dataclasses",
            "grandpa.policy.models",
        }
