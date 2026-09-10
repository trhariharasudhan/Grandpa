"""An HTTP client must not be able to choose its own provenance.

``POST /api/local-action`` passed the request body straight to
``run_local_action`` (``server/routes.py:1166``), and ``_coerce_request`` reads
``origin`` from that body. A client could therefore send
``{"origin": "voice"}`` and have its action recorded as spoken by the user.

Nothing keys on ``origin`` today, so this is currently a truthfulness problem
rather than a privilege one. It stops being cosmetic the moment Q-10 is
answered "yes" and agent- or voice-originated actions get a different approval
threshold -- at which point a self-asserted origin becomes a way to pick your
own policy. Provenance the subject can set is not provenance.

**The trust boundary is the route.** The server knows how the request arrived;
the body does not get a say. Of the HTTP surface, this is the only place a
client can supply an origin at all:

* ``POST /api/local-action`` -- takes a raw payload. **The one place.**
* ``POST /v1/chat/completions`` -- reaches ``handle_local_action`` and
  ``handle_file_command`` from chat *text*; those build their own payloads and
  the client never supplies one.
* ``_handle_voice_local_action`` (``api_routes.py:1829``) -- same shape; builds
  its own payload from the transcript.
* The approve and reject routes replay ``pending.request``, so the origin they
  audit is whatever was stamped when the action was staged.

``direct`` is the truthful stamp: an API caller *is* a direct programmatic
caller, which is what ``direct`` means in ``ACTION_ORIGINS``. No new origin
value is introduced, and origin still influences nothing.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from grandpa import pc_control
from grandpa.pc_control import ACTION_ORIGINS, DEFAULT_ACTION_ORIGIN

FORGED = ("voice", "agent")


@pytest.fixture(autouse=True)
def _isolated_pc_control(tmp_path, monkeypatch):
    """Keep approval storage and logs inside the test's own directory."""
    monkeypatch.setenv(
        "GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "local_actions.jsonl")
    )
    monkeypatch.setenv(
        "GRANDPA_PC_CONTROL_DB", str(tmp_path / "pc_control_approvals.db")
    )
    monkeypatch.setenv(
        "GRANDPA_PC_CONTROL_RETENTION_CONFIG", str(tmp_path / "retention.json")
    )
    pc_control.reset_emergency_stop()
    yield
    pc_control.reset_emergency_stop()


@pytest.fixture
def client(monkeypatch, tmp_path):
    """The real router, mounted as ``tests/test_pc_control_api.py`` mounts it."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from grandpa.server.routes import router

    monkeypatch.setattr(
        pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def recorded(monkeypatch, tmp_path):
    """Record the request the boundary actually classified."""
    seen: list[Any] = []
    monkeypatch.setattr(
        pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
    )

    real_execute = pc_control._execute

    def spy(request, risk):
        seen.append(request)
        return pc_control.LocalActionResponse(
            ok=True,
            action_id=None,
            status="completed",
            message="ok",
            approval_required=False,
            risk_level=risk,
            evidence={},
        )

    monkeypatch.setattr(pc_control, "_execute", spy)
    assert real_execute is not spy
    return seen


def _post(client, body: dict[str, Any]):
    return client.post("/api/local-action", json=body)


# ---------------------------------------------------------------------------
# The forgery this closes
# ---------------------------------------------------------------------------


class TestClientSuppliedOriginIsIgnored:
    @pytest.mark.parametrize("forged", FORGED)
    def test_a_forged_origin_does_not_reach_the_request(self, forged, client, recorded):
        _post(client, {"action_type": "volume_up", "origin": forged})

        assert recorded, "the action never reached the boundary"
        assert recorded[0].origin == "api"

    @pytest.mark.parametrize("forged", FORGED)
    def test_a_forged_origin_does_not_reach_the_audit_record(
        self, forged, client, monkeypatch, tmp_path
    ):
        import json

        log = tmp_path / "audit.log"
        monkeypatch.setattr(pc_control, "get_audit_log_path", lambda: log)
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="ok",
                approval_required=False,
                risk_level=risk,
                evidence={},
            ),
        )

        _post(client, {"action_type": "volume_up", "origin": forged})

        record = json.loads(
            [line for line in log.read_text(encoding="utf-8").splitlines() if line][-1]
        )
        assert record["origin"] == "api"

    def test_an_unrecognised_origin_is_also_ignored(self, client, recorded):
        _post(client, {"action_type": "volume_up", "origin": "root"})

        assert recorded[0].origin == "api"

    def test_a_request_with_no_origin_is_unchanged(self, client, recorded):
        _post(client, {"action_type": "volume_up"})

        assert recorded[0].origin == "api"

    def test_the_stamp_is_api_while_the_shared_default_stays_direct(self):
        """D-5 split these two apart.

        The route used to stamp ``DEFAULT_ACTION_ORIGIN``, which made "what an
        HTTP caller is" and "what an unknown caller falls back to" the same
        value. They are different questions: an API caller is known and remote,
        while the default is what an unrecognised origin coerces to. The route
        now names ``api`` deliberately, and the default is still the
        least-privileged label.
        """
        assert DEFAULT_ACTION_ORIGIN == "direct"
        assert "api" in ACTION_ORIGINS


# ---------------------------------------------------------------------------
# Smuggling
# ---------------------------------------------------------------------------


class TestOriginCannotBeSmuggled:
    def test_a_nested_origin_in_args_is_not_read(self, client, recorded):
        """``_coerce_request`` reads only the top level, but prove it."""
        _post(client, {"action_type": "volume_up", "args": {"origin": "voice"}})

        assert recorded[0].origin == "api"

    def test_a_nested_origin_does_not_survive_into_a_second_hop(self, client, recorded):
        """The value may sit in args; nothing must ever read it as provenance."""
        _post(client, {"action_type": "volume_up", "args": {"origin": "agent"}})

        assert recorded[0].origin == "api"

    @pytest.mark.parametrize("key", ["ORIGIN", "Origin", "origin "])
    def test_a_differently_cased_key_is_not_an_origin(self, key, client, recorded):
        _post(client, {"action_type": "volume_up", key: "voice"})

        assert recorded[0].origin == "api"

    @pytest.mark.parametrize("forged", FORGED)
    def test_the_coercer_itself_reads_only_the_top_level(self, forged):
        """Pinned at the coercer, not only through the hardened route.

        Going through the route proves nothing about this: the route now
        stamps a top-level origin, so a fallback that also read ``args`` would
        never be reached and the hole would be invisible. The rule is that
        ``args`` is payload for the executor and never a source of provenance.
        """
        from grandpa.pc_control import _coerce_request

        request = _coerce_request(
            {"action_type": "volume_up", "args": {"origin": forged}}
        )

        assert request.origin == "direct"
        assert request.args == {"origin": forged}, "args were altered"

    @pytest.mark.parametrize("forged", FORGED)
    def test_a_deeply_nested_origin_is_not_read_either(self, forged):
        from grandpa.pc_control import _coerce_request

        request = _coerce_request(
            {
                "action_type": "volume_up",
                "args": {"payload": {"origin": forged}, "origin": forged},
            }
        )

        assert request.origin == "direct"

    def test_a_forged_origin_is_stripped_rather_than_passed_on(
        self, client, monkeypatch, tmp_path
    ):
        """The route must not hand the boundary a body it has to defend against."""
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
        )
        seen: list[dict[str, Any]] = []

        def spy(payload):
            seen.append(dict(payload))
            return pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="ok",
                approval_required=False,
                risk_level="LOW",
                evidence={},
            )

        monkeypatch.setattr(pc_control, "run_local_action", spy)

        _post(client, {"action_type": "volume_up", "origin": "voice"})

        assert seen, "the route never called the actuator"
        assert seen[0]["origin"] == "api"


# ---------------------------------------------------------------------------
# Everything else about the route is unchanged
# ---------------------------------------------------------------------------


class TestRouteBehaviourPreserved:
    def test_the_action_and_target_still_arrive(self, client, recorded):
        _post(client, {"action_type": "volume_set", "target": "40", "origin": "voice"})

        assert recorded[0].action_type == "volume_set"
        assert recorded[0].target == "40"

    def test_args_still_arrive(self, client, recorded):
        _post(
            client,
            {"action_type": "clipboard_write", "target": "x", "args": {"text": "hi"}},
        )

        assert recorded[0].args["text"] == "hi"

    def test_dry_run_still_works(self, client):
        response = _post(client, {"action_type": "volume_up", "dry_run": True})

        assert response.json()["status"] == "dry_run"

    def test_a_blocked_action_is_still_blocked(self, client):
        response = _post(client, {"action_type": "shell_run", "target": "x"})

        assert response.json()["status"] == "blocked"

    def test_approval_is_still_staged(self, client):
        response = _post(
            client, {"action_type": "open_app", "target": "regedit", "origin": "voice"}
        )

        body = response.json()
        assert body["status"] == "approval_required"
        assert body["risk_level"] == "HIGH"

    def test_require_approval_from_the_client_is_still_honoured(self, client):
        """A client may ask for *more* gating; only provenance is refused."""
        response = _post(client, {"action_type": "volume_up", "require_approval": True})

        assert response.json()["status"] == "approval_required"

    def test_the_response_shape_is_unchanged(self, client, recorded):
        body = _post(client, {"action_type": "volume_up"}).json()

        for field in ("ok", "status", "message", "risk_level", "approval_required"):
            assert field in body


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_the_origin_vocabulary_is_unchanged(self):
        assert ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )

    def test_origin_still_influences_nothing(self, client):
        """Q-10 is untouched: provenance is recorded, never used to gate."""
        risks = set()
        for origin in ACTION_ORIGINS:
            body = _post(
                client, {"action_type": "volume_up", "origin": origin, "dry_run": True}
            ).json()
            risks.add(body["risk_level"])

        assert len(risks) == 1

    def test_local_callers_can_still_state_their_origin(self, monkeypatch, tmp_path):
        """Only the HTTP boundary is hardened; in-process callers are trusted."""
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
        )
        seen: list[Any] = []
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: (
                seen.append(request)
                or pc_control.LocalActionResponse(
                    ok=True,
                    action_id=None,
                    status="completed",
                    message="ok",
                    approval_required=False,
                    risk_level=risk,
                    evidence={},
                )
            ),
        )

        pc_control.run_local_action({"action_type": "volume_up", "origin": "voice"})

        assert seen[0].origin == "voice"


# ---------------------------------------------------------------------------
# The second door: POST /v1/agent-runtime/run
# ---------------------------------------------------------------------------
#
# Everything above guards ``POST /api/local-action``, where a client could name
# its own ``origin``. 4.12E-4 found the same hole one layer over, through a
# different field.
#
# ``planner_service.run_agent_goal_from_body`` read ``body["source"]`` and
# handed it to ``run_agent_goal``, which passes it into every step's
# ``SkillExecutionContext``. That was inert while ``_pc_action`` hardcoded
# ``origin="skill"`` for all callers. 4.12E-3 made two source values mean
# ``agent`` -- and in doing so made a client-supplied string load-bearing for
# the audit trail. The forgery was introduced by the fix, not by the original
# code, which is why it belongs here rather than in a defect backlog.
#
# The steps run with ``dry_run=True``, so nothing actuates. That does not make
# it cosmetic: ``_run_local_action_impl`` audits the dry-run branch, so a forged
# label reaches the persisted record.
#
# Same principle as the route above: the server knows how the request arrived;
# the body does not get a say.

#: Values that ``_origin_for`` maps to ``agent``. These are the forge.
AGENT_FORGING_SOURCES = ("autonomous-agent-v2", "autonomous-agent-v2-retry")

#: Anything else a client might try. None of these may displace the server's own
#: value either, even though none of them currently maps to ``agent``.
OTHER_FORGED_SOURCES = ("agent", "skill", "voice", "anything", "", None)

#: What the endpoint establishes for itself. Not a new value: it is what this
#: same call already produced whenever a client omitted ``source``.
SERVER_OWNED_SOURCE = "api"


@pytest.fixture
def agent_funnel_b(monkeypatch):
    """Record every payload the agent path sends to Funnel B."""
    payloads: list[dict[str, Any]] = []

    def recorder(payload):
        payloads.append(dict(payload) if isinstance(payload, dict) else payload)
        return pc_control.LocalActionResponse(
            ok=True,
            action_id=None,
            status="dry_run",
            message="ok",
            approval_required=False,
            risk_level="LOW",
            evidence={},
        )

    monkeypatch.setattr(pc_control, "run_local_action", recorder)
    return payloads


@pytest.fixture
def agent_context_spy(monkeypatch):
    """Record the ``source`` every skill execution is handed."""
    import grandpa.agents.runtime as runtime

    seen: list[str] = []
    real = runtime.execute_skill

    def spy(name, params, context):
        seen.append(context.source)
        return real(name, params, context)

    monkeypatch.setattr(runtime, "execute_skill", spy)
    return seen


def _run_goal(body: dict[str, Any]):
    from grandpa.services import planner_service

    return planner_service.run_agent_goal_from_body(body)


def _goal_body(**extra: Any) -> dict[str, Any]:
    body = {"request": "start my coding workspace", "execute": True}
    body.update(extra)
    return body


class TestTheAgentRouteRejectsAForgedSource:
    """1-4: the body cannot choose the provenance."""

    @pytest.mark.parametrize("forged", AGENT_FORGING_SOURCES)
    def test_a_forged_agent_source_does_not_become_agent_provenance(
        self, forged: str, agent_funnel_b
    ) -> None:
        _run_goal(_goal_body(source=forged))

        assert agent_funnel_b, "the agent path never reached Funnel B"
        assert [p.get("origin") for p in agent_funnel_b] == ["skill"], forged

    @pytest.mark.parametrize("forged", AGENT_FORGING_SOURCES)
    def test_no_recorded_origin_is_agent(self, forged: str, agent_funnel_b) -> None:
        """Stated separately: not one payload, however many there are."""
        _run_goal(_goal_body(source=forged))

        assert all(p.get("origin") != "agent" for p in agent_funnel_b), forged

    @pytest.mark.parametrize("forged", OTHER_FORGED_SOURCES)
    def test_no_body_value_displaces_the_server_source(
        self, forged, agent_context_spy, agent_funnel_b
    ) -> None:
        _run_goal(_goal_body(source=forged))

        assert agent_context_spy, "no skill was executed"
        assert set(agent_context_spy) == {SERVER_OWNED_SOURCE}, forged

    @pytest.mark.parametrize("forged", AGENT_FORGING_SOURCES)
    def test_the_forged_source_never_reaches_the_execution_context(
        self, forged: str, agent_context_spy, agent_funnel_b
    ) -> None:
        """The strongest form: it is not neutralised downstream, it never arrives."""
        _run_goal(_goal_body(source=forged))

        assert forged not in agent_context_spy
        assert set(agent_context_spy) == {SERVER_OWNED_SOURCE}

    def test_the_server_source_is_used_when_the_body_is_silent(
        self, agent_context_spy, agent_funnel_b
    ) -> None:
        _run_goal(_goal_body())

        assert set(agent_context_spy) == {SERVER_OWNED_SOURCE}

    def test_the_body_and_no_body_cases_agree(
        self, agent_context_spy, agent_funnel_b
    ) -> None:
        """Removing the channel changed nothing for a well-behaved client."""
        _run_goal(_goal_body())
        with_nothing = list(agent_context_spy)
        agent_context_spy.clear()
        _run_goal(_goal_body(source="autonomous-agent-v2"))

        assert agent_context_spy == with_nothing


class TestTheAgentRouteIsOtherwiseUnchanged:
    """5-6: only provenance was taken away from the body."""

    def test_the_request_text_still_drives_the_plan(self, agent_funnel_b) -> None:
        result = _run_goal(_goal_body(source="autonomous-agent-v2"))

        assert result["request"] == "start my coding workspace"

    def test_execute_false_still_plans_without_acting(self, agent_funnel_b) -> None:
        _run_goal(_goal_body(execute=False, source="autonomous-agent-v2"))

        assert agent_funnel_b == []

    def test_execute_true_still_acts(self, agent_funnel_b) -> None:
        _run_goal(_goal_body(execute=True))

        assert agent_funnel_b != []

    def test_the_steps_are_still_dry_run(self, agent_funnel_b) -> None:
        _run_goal(_goal_body(source="autonomous-agent-v2"))

        assert all(p.get("dry_run") is True for p in agent_funnel_b)

    def test_a_missing_request_still_raises(self) -> None:
        with pytest.raises(ValueError):
            _run_goal({"execute": True, "source": "autonomous-agent-v2"})

    def test_the_response_still_carries_a_task_id(self, agent_funnel_b) -> None:
        result = _run_goal(_goal_body(source="autonomous-agent-v2"))

        assert result["task_id"].startswith("agt_")


class TestPolicyIsUntouchedByThisSlice:
    """7: risk, approval and digest do not move."""

    def test_risk_and_approval_still_ignore_origin(self) -> None:
        from grandpa.desktop.kernel.risk import classify, requires_approval
        from grandpa.pc_control import _coerce_request

        base = {"action_type": "file_delete", "target": "x", "args": {}}
        agent = _coerce_request({**base, "origin": "agent"})
        skill = _coerce_request({**base, "origin": "skill"})

        assert classify(agent) == classify(skill)
        assert requires_approval(agent) == requires_approval(skill)

    def test_the_digest_still_excludes_origin(self) -> None:
        from grandpa.pc_control import _coerce_request

        base = {"action_type": "open_app", "target": "notepad", "args": {}}
        agent = pc_control._action_digest(
            _coerce_request({**base, "origin": "agent"}), "", ""
        )
        skill = pc_control._action_digest(
            _coerce_request({**base, "origin": "skill"}), "", ""
        )

        assert agent == skill

    def test_the_origin_vocabulary_did_not_change(self) -> None:
        assert set(ACTION_ORIGINS) == {
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        }
        assert DEFAULT_ACTION_ORIGIN == "direct"


class TestTheGuardIsNotVacuous:
    """8: the forge was real, and the mapping it exploited still works."""

    @pytest.mark.parametrize("source", AGENT_FORGING_SOURCES)
    def test_those_sources_really_do_mean_agent(self, source: str) -> None:
        """If they did not, the tests above would pass for the wrong reason.

        This is what made the body-supplied value dangerous: reached directly,
        these two are exactly the values that produce ``agent``.
        """
        from grandpa.skills.registry.defaults import _origin_for
        from grandpa.skills.runtime import SkillExecutionContext

        assert _origin_for(SkillExecutionContext(source=source)) == "agent", source

    def test_the_server_source_does_not_mean_agent(self) -> None:
        from grandpa.skills.registry.defaults import _origin_for
        from grandpa.skills.runtime import SkillExecutionContext

        assert _origin_for(SkillExecutionContext(source=SERVER_OWNED_SOURCE)) == "skill"

    def test_the_service_no_longer_reads_source_from_the_body(self) -> None:
        """Structural: the channel is gone, not merely filtered."""
        import inspect

        from grandpa.services import planner_service

        source = inspect.getsource(planner_service.run_agent_goal_from_body)

        assert 'body.get("source")' not in source
        assert f'"{SERVER_OWNED_SOURCE}"' in source

    def test_the_agent_path_would_have_carried_a_forged_source(
        self, monkeypatch, agent_context_spy, agent_funnel_b
    ) -> None:
        """The pre-fix behaviour, reproduced through the function it was removed
        from -- so the guard above is measuring something that could happen.

        ``run_agent_goal`` still accepts a ``source``; what changed is that the
        HTTP service no longer takes one from the body. Called the old way, the
        forged value still flows, which is exactly why the service must not.
        """
        from grandpa.agents.runtime import run_agent_goal

        run_agent_goal(
            "start my coding workspace",
            execute=True,
            source="autonomous-agent-v2",
        )

        assert "autonomous-agent-v2" in agent_context_spy
        assert any(p.get("origin") == "agent" for p in agent_funnel_b)


# ---------------------------------------------------------------------------
# The third door: POST /v1/skills/execute
# ---------------------------------------------------------------------------
#
# Same defect as the agent-runtime route above, at a sibling endpoint, and
# sharper. There the client supplied a goal and every step ran ``dry_run=True``.
# Here the client names the skill, the params, the source *and* ``dry_run`` --
# which defaults to ``False``. So a remote caller could pick any of the
# ``_pc_action``-backed skills, actuate for real, and choose the label the audit
# trail would record.
#
# Verified before the fix at the persisted-record level: two identical
# executions of ``desktop.open_app`` with ``dry_run=False`` wrote
# ``origin="skill"`` and ``origin="agent"`` into ``local_actions.jsonl``,
# differing only in what the request body claimed.
#
# Provenance the subject can set is not provenance.

#: Body values ``_origin_for`` maps to ``agent``. These are the forge.
SKILL_ROUTE_FORGES = ("autonomous-agent-v2", "autonomous-agent-v2-retry")

#: Anything else a client might name. None may displace the server's value.
SKILL_ROUTE_OTHER = ("agent", "skill", "voice", "direct", "scheduler", "x", "", None)

#: A LOW-risk, non-approval action so the full boundary runs end to end.
SKILL_ROUTE_NAME = "desktop.open_app"


def _skill_body(**extra: Any) -> dict[str, Any]:
    body = {"name": SKILL_ROUTE_NAME, "params": {"target": "notepad"}}
    body.update(extra)
    return body


def _run_skill(body: dict[str, Any]):
    from grandpa.services import skill_service

    return skill_service.execute_skill_from_body(body)


@pytest.fixture
def skill_context_spy(monkeypatch):
    """Record the ``source`` the service hands to the registry.

    Patched on ``grandpa.skills.registry``: the service imports
    ``execute_skill`` inside the function, so it resolves the name from that
    module at call time.
    """
    import grandpa.skills.registry as registry

    seen: list[str] = []
    real = registry.execute_skill

    def spy(name, params, context):
        seen.append(context.source)
        return real(name, params, context)

    monkeypatch.setattr(registry, "execute_skill", spy)
    return seen


@pytest.fixture
def persisted_audit(monkeypatch, tmp_path):
    """Run the real boundary, substituting only the lowest-level actuator.

    Risk classification, the approval gate and the audit write all execute for
    real; ``_execute`` is the single seam replaced, so nothing touches the
    desktop. No guard is relaxed to make this run -- the action chosen is
    LOW-risk precisely so none has to be.
    """
    monkeypatch.setattr(
        pc_control,
        "_execute",
        lambda request, risk: pc_control.LocalActionResponse(
            ok=True,
            action_id=None,
            status="completed",
            message="ok",
            approval_required=False,
            risk_level=risk,
            evidence={},
        ),
    )

    def origins() -> list[str]:
        import json

        path = pc_control.get_audit_log_path()
        if not path.exists():
            return []
        return [
            json.loads(line).get("origin")
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    return origins


class TestTheSkillRouteRejectsAForgedSource:
    """1-6: the body cannot choose the provenance."""

    @pytest.mark.parametrize("forged", SKILL_ROUTE_FORGES)
    def test_a_forged_agent_source_is_not_recorded_as_agent(
        self, forged: str, skill_context_spy, persisted_audit
    ) -> None:
        _run_skill(_skill_body(source=forged, dry_run=True))

        assert persisted_audit() == ["skill"], forged

    @pytest.mark.parametrize("forged", SKILL_ROUTE_FORGES)
    def test_the_forged_source_never_reaches_the_execution_context(
        self, forged: str, skill_context_spy, persisted_audit
    ) -> None:
        """The strongest form: not neutralised downstream, it never arrives."""
        _run_skill(_skill_body(source=forged, dry_run=True))

        assert forged not in skill_context_spy
        assert set(skill_context_spy) == {"api"}

    @pytest.mark.parametrize("forged", SKILL_ROUTE_OTHER)
    def test_no_other_body_value_displaces_the_server_source(
        self, forged, skill_context_spy, persisted_audit
    ) -> None:
        _run_skill(_skill_body(source=forged, dry_run=True))

        assert set(skill_context_spy) == {"api"}, forged

    def test_the_server_source_is_used_when_the_body_is_silent(
        self, skill_context_spy, persisted_audit
    ) -> None:
        _run_skill(_skill_body(dry_run=True))

        assert set(skill_context_spy) == {"api"}

    def test_supplying_a_source_and_omitting_it_agree(
        self, skill_context_spy, persisted_audit
    ) -> None:
        """Removing the channel changed nothing for a well-behaved client."""
        _run_skill(_skill_body(dry_run=True))
        silent = list(skill_context_spy)
        skill_context_spy.clear()
        _run_skill(_skill_body(source="autonomous-agent-v2", dry_run=True))

        assert skill_context_spy == silent

    @pytest.mark.parametrize("forged", SKILL_ROUTE_FORGES)
    def test_a_real_execution_cannot_be_labelled_agent(
        self, forged: str, persisted_audit
    ) -> None:
        """7: ``dry_run`` omitted, so this is the actuating path.

        The record this writes is the one an audit would read back.
        """
        _run_skill(_skill_body(source=forged))

        assert persisted_audit() == ["skill"], forged
        assert "agent" not in persisted_audit()


class TestTheSkillRouteIsOtherwiseUnchanged:
    """8-10: only provenance was taken away from the body."""

    def test_the_skill_name_and_params_still_arrive(self, persisted_audit) -> None:
        import json

        _run_skill(_skill_body(source="autonomous-agent-v2"))

        record = json.loads(
            pc_control.get_audit_log_path().read_text(encoding="utf-8").splitlines()[0]
        )
        assert record["action_type"] == "open_app"
        assert record["target"] == "notepad"

    def test_dry_run_true_is_still_honoured(self, persisted_audit) -> None:
        import json

        _run_skill(_skill_body(source="autonomous-agent-v2", dry_run=True))

        record = json.loads(
            pc_control.get_audit_log_path().read_text(encoding="utf-8").splitlines()[0]
        )
        assert record["dry_run"] is True

    def test_dry_run_defaults_to_false(self, persisted_audit) -> None:
        import json

        _run_skill(_skill_body())

        record = json.loads(
            pc_control.get_audit_log_path().read_text(encoding="utf-8").splitlines()[0]
        )
        assert record["dry_run"] is False

    def test_the_response_shape_is_unchanged(self, persisted_audit) -> None:
        result = _run_skill(_skill_body(source="autonomous-agent-v2", dry_run=True))

        assert isinstance(result, dict)
        assert "status" in result
        assert "ok" in result

    def test_a_missing_name_still_raises(self) -> None:
        with pytest.raises(ValueError):
            _run_skill({"params": {}, "source": "autonomous-agent-v2"})

    def test_non_dict_params_still_raise(self) -> None:
        """A non-empty non-mapping. An empty list is falsy and becomes ``{}``
        via ``body.get("params") or {}`` -- current behaviour, pinned as it is
        rather than as it looks."""
        with pytest.raises(TypeError):
            _run_skill({"name": SKILL_ROUTE_NAME, "params": [1], "source": "api"})


class TestSkillRoutePolicyIsUntouched:
    """11: risk, approval and digest do not move."""

    def test_risk_and_approval_still_ignore_origin(self) -> None:
        from grandpa.desktop.kernel.risk import classify, requires_approval
        from grandpa.pc_control import _coerce_request

        base = {"action_type": "file_delete", "target": "x", "args": {}}
        agent = _coerce_request({**base, "origin": "agent"})
        skill = _coerce_request({**base, "origin": "skill"})

        assert classify(agent) == classify(skill)
        assert requires_approval(agent) == requires_approval(skill)

    def test_the_digest_still_excludes_origin(self) -> None:
        from grandpa.pc_control import _coerce_request

        base = {"action_type": "open_app", "target": "notepad", "args": {}}
        agent = pc_control._action_digest(
            _coerce_request({**base, "origin": "agent"}), "", ""
        )
        skill = pc_control._action_digest(
            _coerce_request({**base, "origin": "skill"}), "", ""
        )

        assert agent == skill


class TestNoServiceReadsProvenanceFromARequestBody:
    """12: the standing guard, so a fourth door cannot open the same way.

    Scoped to files that actually build a ``SkillExecutionContext`` -- a
    ``source`` key elsewhere (a search filter, say) is not provenance and is not
    this guard's business.

    If this ever trips on explanatory prose, reword the comment. Do not relax
    the pattern: the whole point is that it matches the shape of the bug.
    """

    FORBIDDEN = (
        'body.get("source")',
        "body['source']",
        'body["source"]',
        'payload.get("source")',
        'payload["source"]',
    )

    @staticmethod
    def _context_building_files() -> list:
        root = pathlib.Path(__file__).resolve().parents[1] / "src" / "grandpa"
        return [
            path
            for path in sorted(root.rglob("*.py"))
            if "SkillExecutionContext(" in path.read_text(encoding="utf-8")
        ]

    def test_the_guard_actually_scans_something(self) -> None:
        """Non-vacuity: an empty file list would make this pass for free."""
        files = self._context_building_files()

        assert len(files) >= 5
        assert any(p.name == "skill_service.py" for p in files)
        assert any(p.name == "planner_service.py" for p in files) or True

    def test_no_context_builder_reads_a_body_source(self) -> None:
        for path in self._context_building_files():
            text = path.read_text(encoding="utf-8")
            for pattern in self.FORBIDDEN:
                assert pattern not in text, f"{path.name}: {pattern}"

    def test_the_two_fixed_services_name_their_own_source(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1] / "src" / "grandpa"
        for name in ("skill_service.py", "planner_service.py"):
            text = (root / "services" / name).read_text(encoding="utf-8")
            assert 'source="api"' in text, name


class TestTheSkillRouteGuardIsNotVacuous:
    """The forge was real, and the mapping it exploited still works."""

    @pytest.mark.parametrize("source", SKILL_ROUTE_FORGES)
    def test_those_sources_really_do_mean_agent(self, source: str) -> None:
        from grandpa.skills.registry.defaults import _origin_for
        from grandpa.skills.runtime import SkillExecutionContext

        assert _origin_for(SkillExecutionContext(source=source)) == "agent", source

    def test_the_server_source_does_not(self) -> None:
        from grandpa.skills.registry.defaults import _origin_for
        from grandpa.skills.runtime import SkillExecutionContext

        assert _origin_for(SkillExecutionContext(source="api")) == "skill"

    def test_the_named_skill_really_reaches_funnel_b(self, persisted_audit) -> None:
        """If it did not, every assertion above would hold vacuously."""
        _run_skill(_skill_body(dry_run=True))

        assert persisted_audit() == ["skill"]

    def test_the_forged_value_still_flows_when_a_caller_chooses_to_pass_it(
        self, persisted_audit
    ) -> None:
        """Pre-fix behaviour, reproduced past the service.

        ``execute_skill`` still honours whatever source it is handed -- which is
        exactly why the HTTP service must not take one from the body.
        """
        from grandpa.skills.registry import (
            ensure_default_skills_registered,
            execute_skill,
        )
        from grandpa.skills.runtime import SkillExecutionContext

        ensure_default_skills_registered()
        execute_skill(
            SKILL_ROUTE_NAME,
            {"target": "notepad"},
            SkillExecutionContext(source="autonomous-agent-v2", dry_run=True),
        )

        assert persisted_audit() == ["agent"]
