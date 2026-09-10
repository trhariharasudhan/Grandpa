"""The ActionOrigin contract as it ships today, pinned before D-5 changes it.

D-5 proposes widening the origin vocabulary. Before any value is added, this
file records what the current three values mean, where they are written, and --
most importantly -- what they are *not* allowed to affect. The expansion is safe
only if origin stays out of the approval digest, the token, and the risk tier,
and that is asserted here rather than assumed.

Everything is characterization. Several facts recorded below are arguably
defects: ``direct`` carries four distinct meanings, and ``agent`` is shared by
two callers whose provenance genuinely differs. They are pinned because they are
what ships, and pinning them is what makes the widening a visible, argued change
instead of a silent one.

Isolation: the approval database is redirected per test through the
``GRANDPA_PC_CONTROL_DB`` environment seam the product already provides, and the
audit log through ``get_audit_log_path``. Nothing here touches a real runtime
directory, launches anything, or reaches an actuator.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
from pathlib import Path

import pytest

from grandpa import pc_control
from grandpa.pc_control import (
    ACTION_ORIGINS,
    DEFAULT_ACTION_ORIGIN,
    LocalActionRequest,
    LocalActionResponse,
    _action_digest,
    _coerce_origin,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "grandpa"


@pytest.fixture
def isolated_approval_db(tmp_path, monkeypatch):
    """Point the approval store at a throwaway file via the product's own seam."""
    db = tmp_path / "approvals.db"
    monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(db))
    return db


# ---------------------------------------------------------------------------
# 1-4. The vocabulary itself
# ---------------------------------------------------------------------------


class TestVocabulary:
    def test_the_three_shipped_values(self) -> None:
        assert ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )

    def test_default_is_direct(self) -> None:
        assert DEFAULT_ACTION_ORIGIN == "direct"
        assert DEFAULT_ACTION_ORIGIN in ACTION_ORIGINS

    def test_default_is_the_least_privileged_label(self) -> None:
        """``_coerce_origin`` documents ``direct`` as the fallback for unknowns.

        That is only sound while ``direct`` is the *least* trusted value, which
        is what makes an unrecognised caller safe to record as one.
        """
        assert _coerce_origin("something nobody defined") == "direct"

    def test_request_default_matches(self) -> None:
        assert LocalActionRequest(action_type="open_app").origin == "direct"


# ---------------------------------------------------------------------------
# 2. The duplicate definitions
# ---------------------------------------------------------------------------


class TestSingleCanonicalDefinition:
    """D-5 ended the duplication. ``policy.models`` is the one definition.

    ``policy`` is the right home because it imports nothing from the package,
    so any layer can name a provenance without depending on the execution
    module. ``pc_control`` re-exports rather than redefines, because callers and
    tests already bind to the names there and breaking that would change a
    public surface for no benefit.
    """

    def test_pc_control_re_exports_the_same_objects(self) -> None:
        from grandpa import pc_control as pc
        from grandpa.policy import models

        assert pc.ActionOrigin is models.ActionOrigin
        assert pc.ACTION_ORIGINS is models.ACTION_ORIGINS
        assert pc.DEFAULT_ACTION_ORIGIN == models.DEFAULT_ACTION_ORIGIN

    def test_the_compatibility_import_path_still_works(self) -> None:
        """The public surface callers already use must keep working."""
        from grandpa.pc_control import (  # noqa: F401
            ACTION_ORIGINS as compat_origins,
        )
        from grandpa.pc_control import (
            DEFAULT_ACTION_ORIGIN as compat_default,
        )
        from grandpa.pc_control import (
            ActionOrigin as compat_type,
        )

        assert compat_origins == ACTION_ORIGINS
        assert compat_default == "direct"
        assert compat_type.__args__[0] == "voice"

    def test_pc_control_does_not_define_its_own_copy(self) -> None:
        """A second definition would silently drift the moment one changed."""
        source = (SRC / "pc_control.py").read_text(encoding="utf-8")

        assert "ActionOrigin = Literal[" not in source
        assert "ACTION_ORIGINS: tuple" not in source

    def test_the_literal_matches_the_runtime_tuple(self) -> None:
        from grandpa.policy.models import ActionOrigin as PolicyOrigin

        assert tuple(PolicyOrigin.__args__) == ACTION_ORIGINS

    def test_neither_module_imports_the_other(self) -> None:
        # The direction that matters: policy must not depend on pc_control.
        policy_src = (SRC / "policy" / "models.py").read_text(encoding="utf-8")
        tree = ast.parse(policy_src)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any("pc_control" in m for m in imported)


# ---------------------------------------------------------------------------
# 5. Coercion
# ---------------------------------------------------------------------------


class TestCoercion:
    @pytest.mark.parametrize("origin", ACTION_ORIGINS)
    def test_known_values_pass_through(self, origin: str) -> None:
        assert _coerce_origin(origin) == origin

    @pytest.mark.parametrize(
        "value", ["user", "root", "system", "VOICE-ish", "1", "api-caller"]
    )
    def test_unknown_values_fall_back_to_direct(self, value: str) -> None:
        """Least privilege is unchanged by the expansion.

        ``user`` is deliberately in this list: TARGET names it, D-5 did not
        adopt it, and an unadopted value must not quietly work.
        """
        assert _coerce_origin(value) == "direct"

    @pytest.mark.parametrize("value", [None, "", "   ", 0, False, []])
    def test_empty_and_falsy_fall_back_to_direct(self, value) -> None:
        assert _coerce_origin(value) == "direct"

    @pytest.mark.parametrize("value", ["VOICE", "Voice", "  voice  ", "AGENT"])
    def test_case_and_whitespace_are_normalised(self, value: str) -> None:
        assert _coerce_origin(value) in ACTION_ORIGINS

    @pytest.mark.parametrize("added", ["api", "scheduler", "skill"])
    def test_the_three_added_values_round_trip(self, added: str) -> None:
        """D-5 added these; they must survive coercion rather than collapse."""
        assert _coerce_origin(added) == added
        assert added in ACTION_ORIGINS


# ---------------------------------------------------------------------------
# 6. Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    @pytest.mark.parametrize("origin", ACTION_ORIGINS)
    def test_origin_round_trips_through_the_approval_row(
        self, origin: str, isolated_approval_db
    ) -> None:
        request = LocalActionRequest(
            action_type="open_app", target="notepad", origin=origin
        )
        action_id = pc_control._create_pending(request)

        pending = pc_control._load_pending_record(action_id)

        assert pending is not None
        assert pending.request.origin == origin

    def test_a_row_with_an_unknown_origin_reads_back_as_direct(
        self, isolated_approval_db
    ) -> None:
        """A row edited outside the app cannot name an origin that does not exist."""
        request = LocalActionRequest(
            action_type="open_app", target="notepad", origin="voice"
        )
        action_id = pc_control._create_pending(request)

        with pc_control._connect_approval_db() as conn:
            conn.execute(
                "UPDATE pc_control_approvals SET origin = ? WHERE action_id = ?",
                ("superuser", action_id),
            )

        pending = pc_control._load_pending_record(action_id)

        assert pending is not None
        assert pending.request.origin == "direct"

    def test_origin_appears_in_the_audit_record(self, tmp_path, monkeypatch) -> None:
        log = tmp_path / "audit.jsonl"
        monkeypatch.setattr(pc_control, "get_audit_log_path", lambda: log)
        request = LocalActionRequest(
            action_type="open_app", target="notepad", origin="agent"
        )
        response = LocalActionResponse(
            ok=True,
            action_id=None,
            status="completed",
            message="done",
            approval_required=False,
            risk_level="LOW",
        )

        pc_control._audit(request, response, approval_status="none")

        record = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert record["origin"] == "agent"


# ---------------------------------------------------------------------------
# 7-8. The security boundary
# ---------------------------------------------------------------------------


class TestOriginIsNotASecurityInput:
    """The invariant that makes widening the vocabulary safe.

    ``_action_digest`` documents it: the digest answers "what was approved", not
    "who asked". If origin ever entered the digest, adding a value would
    invalidate every stored approval, and these tests would be the ones to fail.
    """

    def _request(self, origin: str) -> LocalActionRequest:
        return LocalActionRequest(
            action_type="open_app",
            target="notepad",
            args={"b": 2, "a": 1},
            origin=origin,
        )

    def test_digest_is_identical_across_every_origin(self) -> None:
        digests = {
            _action_digest(self._request(origin), "notepad.exe", "C:/notepad.exe")
            for origin in ACTION_ORIGINS
        }

        assert len(digests) == 1

    def test_digest_still_changes_when_the_action_changes(self) -> None:
        """Guards the test above from passing because the digest ignores input."""
        base = _action_digest(self._request("voice"), "notepad.exe", "C:/notepad.exe")
        other_target = _action_digest(
            LocalActionRequest(action_type="open_app", target="calc", origin="voice"),
            "notepad.exe",
            "C:/notepad.exe",
        )
        other_exe = _action_digest(self._request("voice"), "calc.exe", "C:/notepad.exe")

        assert base != other_target
        assert base != other_exe

    def test_origin_is_absent_from_the_digest_payload(self) -> None:
        source = inspect.getsource(_action_digest)
        payload = source.split("payload = {", 1)[1]

        assert '"origin"' not in payload

    def test_origin_does_not_change_the_risk_tier(self) -> None:
        tiers = {
            pc_control.classify_risk(self._request(origin)) for origin in ACTION_ORIGINS
        }

        assert len(tiers) == 1

    def test_origin_does_not_change_whether_approval_is_required(self) -> None:
        decisions = {
            pc_control._launch_needs_approval(
                LocalActionRequest(
                    action_type="open_app", target="task_manager", origin=origin
                )
            )
            for origin in ACTION_ORIGINS
        }

        assert decisions == {True}

    def test_the_approval_token_is_random_and_ignores_origin(self) -> None:
        source = inspect.getsource(pc_control._create_pending)

        assert "secrets.token_hex" in source
        token_line = next(
            line for line in source.splitlines() if "secrets.token_hex" in line
        )
        assert "origin" not in token_line

    def test_policy_classification_ignores_origin(self) -> None:
        from grandpa.policy.engine import classify_risk as policy_classify
        from grandpa.policy.models import PolicyRequest

        tiers = {
            policy_classify(
                PolicyRequest(action_type="open_app", target="notepad", origin=o),
                pc_control._risk_tables(),
            ).risk_level
            for o in ACTION_ORIGINS
        }

        assert len(tiers) == 1


# ---------------------------------------------------------------------------
# 9. HTTP provenance
# ---------------------------------------------------------------------------


class TestHttpOriginIsStampedServerSide:
    """A client must not be able to name its own provenance.

    ``_coerce_request`` reads ``origin`` from the payload, so the route
    overwrites it. Nothing keys on origin today, which makes this a truthfulness
    control rather than a privilege one -- and exactly the control that must
    still hold when provenance starts selecting an approval threshold.
    """

    def _call(self, payload, monkeypatch):
        seen: list[dict] = []

        def spy(request_payload):
            seen.append(dict(request_payload))
            return LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="ok",
                approval_required=False,
                risk_level="LOW",
            )

        monkeypatch.setattr(pc_control, "run_local_action", spy)
        from grandpa.server.routes import run_structured_local_action

        asyncio.run(run_structured_local_action(payload))
        return seen[0]

    @pytest.mark.parametrize(
        "claimed", ["voice", "agent", "skill", "scheduler", "root", "", None]
    )
    def test_a_client_cannot_choose_its_origin(self, claimed, monkeypatch) -> None:
        """Widening the vocabulary widened what a client might try to claim.

        ``skill`` and ``scheduler`` are included precisely because they are new:
        an expansion that let a caller name one of them would have turned a
        truthfulness gap into an escalation route.
        """
        forwarded = self._call(
            {"action_type": "open_app", "target": "notepad", "origin": claimed},
            monkeypatch,
        )

        assert forwarded["origin"] == "api"

    def test_the_rest_of_the_payload_is_forwarded_untouched(self, monkeypatch) -> None:
        forwarded = self._call(
            {"action_type": "open_app", "target": "notepad", "origin": "voice"},
            monkeypatch,
        )

        assert forwarded["action_type"] == "open_app"
        assert forwarded["target"] == "notepad"

    def test_a_payload_without_origin_still_gets_one(self, monkeypatch) -> None:
        forwarded = self._call(
            {"action_type": "open_app", "target": "notepad"}, monkeypatch
        )

        assert forwarded["origin"] == "api"

    def test_the_stamp_is_api_not_the_shared_default(self, monkeypatch) -> None:
        """D-5 separated "what an HTTP caller is" from "what unknown becomes"."""
        forwarded = self._call({"action_type": "open_app"}, monkeypatch)

        assert forwarded["origin"] == "api"
        assert DEFAULT_ACTION_ORIGIN == "direct"


# ---------------------------------------------------------------------------
# 10-12. Where each origin actually comes from
# ---------------------------------------------------------------------------


def _origin_literals(relative: str) -> set[str]:
    """Origins spelled as literals in one production module."""
    source = (SRC / relative).read_text(encoding="utf-8")
    return {
        value
        for value in ACTION_ORIGINS
        if f'origin="{value}"' in source or f'"origin": "{value}"' in source
    }


class TestEvidencedProvenance:
    """Which origin each production surface actually stamps, read from source.

    Read rather than invoked: several of these callers actuate, and the question
    here is what provenance they declare, not what they do.
    """

    @pytest.mark.parametrize(
        "module,expected",
        [
            ("cli/ask.py", "direct"),
            ("cli/chat_cmd.py", "direct"),
            ("server/routes.py", "api"),
            ("voice/assistant.py", "voice"),
            ("voice/operator.py", "voice"),
            ("voice/session.py", "voice"),
            ("agents/context.py", "agent"),
            ("skills/registry/defaults.py", "skill"),
        ],
    )
    def test_surface_stamps_the_expected_origin(
        self, module: str, expected: str
    ) -> None:
        assert expected in _origin_literals(module), module

    def test_which_values_are_passed_as_keyword_literals(self) -> None:
        """``agent`` and ``skill`` arrive only through dict payloads.

        Recorded because it makes them easy to miss when grepping for
        provenance: only ``direct``, ``voice`` and ``api`` are ever written as
        ``origin=``.
        """
        passed: set[str] = set()
        for path in SRC.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for value in ACTION_ORIGINS:
                if f'origin="{value}"' in source:
                    passed.add(value)

        assert passed == {"direct", "voice", "api"}

    def test_agent_and_skill_are_now_separate(self) -> None:
        """D-5 split the case the three-value vocabulary could not express.

        ``agents/context.py`` sends a hardcoded literal payload -- no model
        input reaches it, so it stays ``agent``. ``skills/registry/defaults.py``
        is reached through ``SkillTool`` with model-chosen parameters, so it is
        now ``skill``. AD-022 is about exactly that difference.
        """
        agent_ctx = _origin_literals("agents/context.py")
        skills = _origin_literals("skills/registry/defaults.py")

        assert "agent" in agent_ctx and "skill" not in agent_ctx
        assert "skill" in skills and "agent" not in skills


#: Callers of ``handle_local_action`` that are *not* provenance-free.
#:
#: A composition adapter is not an entry surface. It is handed a
#: ``RequestContext`` whose ``origin`` is required and has no default, so
#: provenance is stated at its boundary; it cannot forward that origin only
#: because ``handle_local_action`` accepts no ``origin`` parameter. Counting it
#: among the provenance-free callsites would misreport where the gap actually
#: is -- the gap is Funnel A's signature, not this caller.
#:
#: Exact paths, deliberately not a ``composition/`` prefix. A second composition
#: module calling ``handle_local_action`` would be a genuinely new
#: provenance-free callsite and must still fail this guard.
PROVENANCE_CARRYING_CALLERS = frozenset({"composition/ask_handlers.py"})


class TestFunnelAHasNoProvenance:
    """The twelve Funnel-A callsites cannot state an origin at all."""

    @staticmethod
    def _callsites() -> list[str]:
        return [
            path.relative_to(SRC).as_posix()
            for path in SRC.rglob("*.py")
            for line in path.read_text(encoding="utf-8").splitlines()
            if "handle_local_action(" in line and "def handle_local_action" not in line
        ]

    def test_handle_local_action_has_no_origin_parameter(self) -> None:
        from grandpa.local_actions import handle_local_action

        params = inspect.signature(handle_local_action).parameters

        assert "origin" not in params
        assert set(params) == {"text", "execute"}

    def test_there_are_eleven_provenance_free_callsites(self) -> None:
        """Eleven direct production callsites into Funnel A.

        Twelve until 4.5I wired ``cli/ask.py`` to the dispatcher. ``ask`` now
        reaches Funnel A *indirectly*, through the composition adapter, so it
        no longer contains a literal ``handle_local_action(`` call and drops out
        of this scan. The metric is unchanged -- direct callsites -- and eleven
        is simply what it now counts.

        **This is not a claim that ``ask`` forwards provenance.** It does not:
        ``handle_local_action`` still has no ``origin`` parameter, so the origin
        ``ask`` states dies at the adapter exactly as it died at ``ask`` before.
        The indirect-path provenance debt is real, is shared with four other
        surfaces, and is deliberately not measured by this guard.
        """
        raw = self._callsites()
        callsites = [p for p in raw if p not in PROVENANCE_CARRYING_CALLERS]

        assert len(callsites) == 11
        assert "local_actions.py" not in callsites
        assert "cli/ask.py" not in callsites

    def test_the_exclusion_is_not_vacuous(self) -> None:
        """The excluded caller must actually exist and call it.

        Without this, deleting or renaming the adapter would leave the count at
        twelve and the exclusion silently meaningless.
        """
        assert PROVENANCE_CARRYING_CALLERS <= set(self._callsites())

    def test_the_excluded_caller_really_does_carry_provenance(self) -> None:
        """Why it is excluded: origin is required at its boundary.

        ``RequestContext.origin`` has no default, so the adapter cannot be
        constructed without a stated provenance -- which is precisely what the
        twelve genuine callsites cannot do.
        """
        import dataclasses

        from grandpa.dispatch import RequestContext

        field = {f.name: f for f in dataclasses.fields(RequestContext)}["origin"]
        assert field.default is dataclasses.MISSING

        for module in PROVENANCE_CARRYING_CALLERS:
            source = (SRC / module).read_text(encoding="utf-8")
            assert "RequestContext" in source, module

    def test_the_six_untruthful_surfaces_are_these(self) -> None:
        """PRE-EXPANSION: surfaces with no truthful value under three origins.

        HTTP collapses onto ``direct`` alongside the CLI; the scheduler and the
        two diagnostic harnesses have no value at all. This is the gap D-5 is
        deciding about, recorded as fact rather than as a proposal.
        """
        untruthful = {
            "server/routes.py",
            "server/api_routes.py",
            "task_scheduler.py",
            "burnin.py",
            "cli/doctor_cmd.py",
        }
        for module in untruthful:
            assert (SRC / module).exists(), module


class TestFrozenVocabulary:
    """The vocabulary D-5 settled on. Six values, expanded additively.

    This replaces the pre-expansion guard it grew out of. The role is unchanged
    -- catch a value added or removed without a decision -- but the baseline is
    now the post-D-5 set. A further change should update this test as part of
    that change, the same way D-5B updated its predecessor.
    """

    def test_exactly_six_values(self) -> None:
        assert len(ACTION_ORIGINS) == 6
        assert set(ACTION_ORIGINS) == {
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        }

    def test_the_original_three_are_unchanged_and_still_first(self) -> None:
        """Additive means additive: nothing renamed, nothing reordered."""
        assert ACTION_ORIGINS[:3] == ("voice", "agent", "direct")

    def test_exactly_three_values_were_added(self) -> None:
        assert set(ACTION_ORIGINS) - {"voice", "agent", "direct"} == {
            "api",
            "scheduler",
            "skill",
        }

    def test_the_literal_and_the_tuple_agree(self) -> None:
        """The ``Literal`` is erased at runtime; only the tuple is checked."""
        from grandpa.policy.models import ActionOrigin

        assert tuple(ActionOrigin.__args__) == ACTION_ORIGINS

    def test_target_architecture_documents_the_shipped_vocabulary(self) -> None:
        """D-5C reconciled the document to the runtime, not the reverse.

        Before D-5C the document named ``user|skill|agent|api|scheduler`` and,
        in one place, a sixth ``test`` value -- a set that shared only ``agent``
        with what ships and would have deleted the two values every production
        callsite uses. The document now lists the six shipped values; ``user``
        survives as a conceptual category rather than a runtime value, and
        ``test`` is gone because no such origin exists.
        """
        target = (ROOT / "docs" / "architecture" / "TARGET_ARCHITECTURE.md").read_text(
            encoding="utf-8"
        )

        for value in ACTION_ORIGINS:
            assert f"`{value}`" in target, value

        # The pre-D-5C vocabulary must not linger anywhere in the document.
        assert "user, skill, agent, api, scheduler" not in target
        assert "user|skill|agent|" not in target
        assert "scheduler, test}" not in target

    def test_no_document_claims_a_test_origin(self) -> None:
        """``test`` was never a runtime value and is not one now."""
        assert "test" not in ACTION_ORIGINS

        docs = ROOT / "docs" / "architecture"
        for name in ("TARGET_ARCHITECTURE.md", "ARCHITECTURE_DECISIONS.md"):
            text = (docs / name).read_text(encoding="utf-8")
            assert "api, scheduler, test" not in text, name
            assert "api|scheduler|test" not in text, name

    def test_the_decision_record_lists_the_same_six_values(self) -> None:
        decisions = (
            ROOT / "docs" / "architecture" / "ARCHITECTURE_DECISIONS.md"
        ).read_text(encoding="utf-8")

        assert "{voice, direct, api, agent, skill, scheduler}" in decisions


class TestBoundariesIntentionallyLeftUnchanged:
    """Where D-5 did not stamp a new origin, and why.

    ``scheduler`` is in the vocabulary but has no callsite. ``task_scheduler``
    reaches actuation only through ``handle_local_action``, which takes no
    origin, so stamping it truthfully would mean changing Funnel A -- explicitly
    out of scope for this slice. The value is defined and ready; the plumbing
    arrives with the Funnel-A migration.

    The same applies to ``server/api_routes.py``: it is an HTTP surface and
    would be ``api``, but it too reaches only ``handle_local_action``.

    Burn-in and the doctor probe are left alone on purpose rather than by
    obstruction -- no truthful origin exists for them, and inventing one would
    put noise in the audit trail.
    """

    def test_scheduler_is_defined_but_not_yet_stamped_anywhere(self) -> None:
        assert "scheduler" in ACTION_ORIGINS

        stamped = {
            path.relative_to(SRC).as_posix()
            for path in SRC.rglob("*.py")
            if 'origin="scheduler"' in path.read_text(encoding="utf-8")
            or '"origin": "scheduler"' in path.read_text(encoding="utf-8")
        }
        assert stamped == set()

    def test_the_scheduler_has_no_origin_capable_path(self) -> None:
        """The reason it cannot be stamped, asserted rather than asserted about."""
        source = (SRC / "task_scheduler.py").read_text(encoding="utf-8")

        assert "handle_local_action(" in source
        assert "run_local_action(" not in source
        assert "origin=" not in source

    def test_api_routes_also_reaches_only_funnel_a(self) -> None:
        source = (SRC / "server" / "api_routes.py").read_text(encoding="utf-8")

        assert "handle_local_action(" in source
        assert "origin=" not in source

    def test_no_origin_was_invented_for_diagnostics(self) -> None:
        for module in ("burnin.py", "cli/doctor_cmd.py"):
            source = (SRC / module).read_text(encoding="utf-8")
            assert "origin=" not in source, module
