"""``POST /v1/local-actions/{id}/approve`` now requires the out-of-band code.

4.12G proved this endpoint approved -- and executed -- on an ``action_id``
alone, with no credential, no ``pc_control`` gate and no emergency stop. 4.12K
closed the two paths that needed no id at all; this one still needed the id, so
it was left for 4.13.

The code it now demands is the one ``create_pending`` logs to the console
(4.13C). An HTTP caller that stages an action cannot read that log, which is the
entire point: **the party that requests an action is no longer the party that
can approve it.**

What this slice deliberately does *not* do, so the remaining exposure stays
visible rather than looking finished:

* ``/v1/voice/confirm`` still approves on an id alone -- 4.13E.
* The execution path still bypasses ``pc_control``, so the emergency stop still
  does not cover it. ``test_emergency_stop_is_still_not_consulted`` records that
  as unchanged rather than letting silence imply it was fixed.
"""

from __future__ import annotations

import os
import webbrowser
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.local_action_approvals import (
    MAX_APPROVAL_ATTEMPTS,
    LocalActionApprovalStore,
)

STAGING = {
    "source_text": "open https://example.com",
    "kind": "url",
    "target": "https://example.com",
    "message": "Confirmation required.",
    "tts_text": "Please confirm.",
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """One isolated store, shared by the route and the test.

    The route resolves ``LocalActionApprovalStore`` through ``local_actions``,
    the same name every other caller uses, so patching it here covers both
    sides. The real ``~/.grandpa`` database is never constructed.
    """
    import grandpa.local_actions as local_actions

    isolated = LocalActionApprovalStore(tmp_path / "approvals.db")
    monkeypatch.setattr(local_actions, "LocalActionApprovalStore", lambda: isolated)
    return isolated


@pytest.fixture
def actuated(monkeypatch):
    seen: list[Any] = []

    def recorder(*args, **kwargs):
        seen.append(args[:1])
        return True

    monkeypatch.setattr(webbrowser, "open", recorder)
    monkeypatch.setattr(webbrowser, "open_new_tab", recorder)
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", recorder)
    return seen


@pytest.fixture
def client():
    from grandpa.server.routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _stage(store, **overrides):
    payload = dict(STAGING)
    payload.update(overrides)
    return store.create_pending(**payload)


def _approve(client, action_id: str, body: dict | None = None):
    return client.post(f"/v1/local-actions/{action_id}/approve", json=body)


# ---------------------------------------------------------------------------
# A-E, L -- everything that must now be refused
# ---------------------------------------------------------------------------


class TestApprovalIsRefusedWithoutTheCode:
    def test_id_only_approval_no_longer_works(self, store, client, actuated) -> None:
        """A: the 4.12G vulnerability, closed."""
        pending = _stage(store)

        response = _approve(client, pending["id"], None)

        assert response.status_code == 403
        assert actuated == []
        assert store.get_pending(pending["id"])["status"] == "pending"

    def test_a_missing_token_field_is_refused(self, store, client, actuated) -> None:
        """B."""
        pending = _stage(store)

        response = _approve(client, pending["id"], {})

        assert response.status_code == 403
        assert actuated == []

    def test_a_wrong_token_is_refused(self, store, client, actuated) -> None:
        """C."""
        pending = _stage(store)

        response = _approve(client, pending["id"], {"approval_token": "00000000"})

        assert response.status_code == 403
        assert actuated == []

    def test_an_empty_token_is_refused(self, store, client, actuated) -> None:
        """D."""
        pending = _stage(store)

        response = _approve(client, pending["id"], {"approval_token": ""})

        assert response.status_code == 403
        assert actuated == []

    def test_a_legacy_unbound_row_is_refused(self, store, client, actuated) -> None:
        """E: a row with no code bound to it cannot be approved at all."""
        pending = _stage(store)
        with store._connect() as conn:
            conn.execute(
                "UPDATE pending_actions SET approval_token = '' WHERE id = ?",
                (pending["id"],),
            )

        response = _approve(client, pending["id"], {"approval_token": ""})

        assert response.status_code == 403
        assert actuated == []
        assert store.get_pending(pending["id"])["status"] == "pending"

    def test_an_unknown_action_is_refused(self, store, client, actuated) -> None:
        """L."""
        response = _approve(client, "deadbeef" * 4, {"approval_token": "00000000"})

        assert response.status_code == 403
        assert actuated == []

    def test_an_expired_action_is_refused(self, store, client, actuated) -> None:
        """K: even the right code cannot revive a lapsed action."""
        pending = _stage(store)
        token = store.approval_token(pending["id"])
        store.expire_old(now=9_999_999_999.0)

        response = _approve(client, pending["id"], {"approval_token": token})

        assert response.status_code == 403
        assert actuated == []


# ---------------------------------------------------------------------------
# F, G, I, J -- the code that works
# ---------------------------------------------------------------------------


class TestApprovalSucceedsWithTheCode:
    def test_the_correct_code_approves_and_executes(
        self, store, client, actuated
    ) -> None:
        """F, and the non-vacuity case: real store, real endpoint, real code."""
        pending = _stage(store)
        token = store.approval_token(pending["id"])

        response = _approve(client, pending["id"], {"approval_token": token})

        assert response.status_code == 200
        assert response.json()["local_action"]["status"] == "handled"
        assert actuated != []
        assert store.get_pending(pending["id"])["status"] == "approved"

    def test_a_code_for_one_action_does_not_approve_another(
        self, store, client, actuated
    ) -> None:
        """G."""
        first = _stage(store, source_text="first")
        second = _stage(store, source_text="second")
        first_token = store.approval_token(first["id"])

        response = _approve(client, second["id"], {"approval_token": first_token})

        assert response.status_code == 403
        assert actuated == []
        assert store.get_pending(second["id"])["status"] == "pending"

    def test_approval_transitions_exactly_once(self, store, client, actuated) -> None:
        """I."""
        pending = _stage(store)
        token = store.approval_token(pending["id"])

        _approve(client, pending["id"], {"approval_token": token})

        assert store.get_pending(pending["id"])["status"] == "approved"
        assert len(actuated) == 1

    def test_replaying_the_code_is_refused(self, store, client, actuated) -> None:
        """J: the code is single-use because the row leaves ``pending``."""
        pending = _stage(store)
        token = store.approval_token(pending["id"])
        _approve(client, pending["id"], {"approval_token": token})

        replay = _approve(client, pending["id"], {"approval_token": token})

        assert replay.status_code == 403
        assert len(actuated) == 1


# ---------------------------------------------------------------------------
# Attempt cap, over HTTP
# ---------------------------------------------------------------------------


class TestTheAttemptCapAppliesToTheEndpoint:
    def test_wrong_guesses_are_counted(self, store, client, actuated) -> None:
        pending = _stage(store)

        for _ in range(3):
            _approve(client, pending["id"], {"approval_token": "00000000"})

        assert store.failed_attempts(pending["id"]) == 3

    def test_the_cap_blocks_further_guesses(self, store, client, actuated) -> None:
        pending = _stage(store)
        for _ in range(MAX_APPROVAL_ATTEMPTS):
            _approve(client, pending["id"], {"approval_token": "00000000"})

        response = _approve(client, pending["id"], {"approval_token": "11111111"})

        assert response.status_code == 403
        assert store.failed_attempts(pending["id"]) == MAX_APPROVAL_ATTEMPTS

    def test_the_correct_code_after_the_cap_is_refused(
        self, store, client, actuated
    ) -> None:
        pending = _stage(store)
        token = store.approval_token(pending["id"])
        for _ in range(MAX_APPROVAL_ATTEMPTS):
            _approve(client, pending["id"], {"approval_token": "00000000"})

        response = _approve(client, pending["id"], {"approval_token": token})

        assert response.status_code == 403
        assert actuated == []

    def test_a_successful_approval_spends_no_attempt(
        self, store, client, actuated
    ) -> None:
        pending = _stage(store)
        token = store.approval_token(pending["id"])

        _approve(client, pending["id"], {"approval_token": token})

        assert store.failed_attempts(pending["id"]) == 0


# ---------------------------------------------------------------------------
# M, N, O, P -- the response and the log
# ---------------------------------------------------------------------------


class TestNothingLeaksThroughTheEndpoint:
    def test_the_supplied_token_is_not_returned(self, store, client) -> None:
        """M."""
        pending = _stage(store)

        response = _approve(client, pending["id"], {"approval_token": "SUPPLIED0"})

        assert "SUPPLIED0" not in response.text

    def test_the_expected_token_is_not_returned_on_failure(self, store, client) -> None:
        """N."""
        pending = _stage(store)
        token = store.approval_token(pending["id"])

        response = _approve(client, pending["id"], {"approval_token": "00000000"})

        assert token not in response.text

    def test_the_expected_token_is_not_returned_on_success(
        self, store, client, actuated
    ) -> None:
        pending = _stage(store)
        token = store.approval_token(pending["id"])

        response = _approve(client, pending["id"], {"approval_token": token})

        assert response.status_code == 200
        assert token not in response.text

    def test_a_failed_attempt_does_not_log_either_token(
        self, store, client, caplog
    ) -> None:
        """O."""
        import logging

        pending = _stage(store)
        token = store.approval_token(pending["id"])
        caplog.clear()

        with caplog.at_level(logging.DEBUG):
            _approve(client, pending["id"], {"approval_token": "SUPPLIED0"})

        assert "SUPPLIED0" not in caplog.text
        assert token not in caplog.text

    def test_the_counter_is_not_returned(self, store, client) -> None:
        pending = _stage(store)

        response = _approve(client, pending["id"], {"approval_token": "00000000"})

        assert "failed_attempts" not in response.text

    @pytest.mark.parametrize(
        "field", ("token", "code", "confirmation_token", "id", "action_id", "target")
    )
    def test_no_alternate_field_substitutes_for_the_code(
        self, field: str, store, client, actuated
    ) -> None:
        """P."""
        pending = _stage(store)
        token = store.approval_token(pending["id"])

        response = _approve(client, pending["id"], {field: token})

        assert response.status_code == 403, field
        assert actuated == [], field

    @pytest.mark.parametrize("substitute", ("source_text", "target", "message"))
    def test_a_row_field_cannot_be_the_credential(
        self, substitute: str, store, client, actuated
    ) -> None:
        pending = _stage(store)

        response = _approve(
            client, pending["id"], {"approval_token": pending[substitute]}
        )

        assert response.status_code == 403, substitute

    def test_the_action_id_cannot_be_the_credential(
        self, store, client, actuated
    ) -> None:
        pending = _stage(store)

        response = _approve(client, pending["id"], {"approval_token": pending["id"]})

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# R, S -- what this slice deliberately did not change
# ---------------------------------------------------------------------------


class TestScopeIsUnchanged:
    def test_pc_control_is_now_consulted_for_this_kind(
        self, store, client, actuated
    ) -> None:
        """Amended by M4 4.14A -- this assertion was inverted deliberately.

        It used to assert ``pc_control`` was *never* reached, which was true of
        every ``_execute`` branch but one. 4.14A routed the three LOW-risk kinds
        -- ``app``, ``folder`` and ``url`` -- through ``run_local_action``, and
        this suite stages a ``url``. So the boundary is now consulted, and with
        it the emergency stop, risk classification and the ``pc_control`` audit.

        The endpoint itself is unchanged; what moved is one layer below it.
        """
        import grandpa.pc_control as pc_control

        calls: list[Any] = []
        original = pc_control.run_local_action
        pc_control.run_local_action = lambda payload: calls.append(payload)
        try:
            pending = _stage(store)
            token = store.approval_token(pending["id"])
            _approve(client, pending["id"], {"approval_token": token})
        finally:
            pc_control.run_local_action = original

        assert [p["action_type"] for p in calls] == ["browser_open"]

    def test_the_endpoint_itself_still_does_not_mention_the_emergency_stop(
        self, store, client
    ) -> None:
        """Amended by M4 4.14A.

        The e-stop is now honoured for this kind, but not by the route -- it is
        enforced inside ``pc_control``, where it always was. The route stays a
        thin authorization layer, which is what this asserts. The nine unrouted
        ``_execute`` branches remain outside e-stop coverage; that is 4.14's
        remaining work, not this endpoint's.
        """
        import inspect

        from grandpa.server import routes

        source = inspect.getsource(routes.approve_local_action)

        assert "emergency" not in source.lower()

    def test_voice_confirm_was_since_removed(self) -> None:
        """4.13D left it open; 4.13E removed it.

        This asserted the route still approved on an id alone -- true when this
        file was written, and recorded so the exposure stayed visible. The
        decision landed: it was a network surface handing the caller its own
        credential, so it is gone rather than hardened.
        """
        from grandpa.server import api_routes

        assert not hasattr(api_routes, "voice_confirm")

    def test_the_deny_route_still_needs_no_code(self, store, client) -> None:
        """Denial executes nothing, so it is not gated."""
        pending = _stage(store)

        response = client.post(f"/v1/local-actions/{pending['id']}/deny")

        assert response.status_code == 200
        assert store.get_pending(pending["id"])["status"] == "denied"
