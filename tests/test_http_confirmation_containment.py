"""HTTP cannot approve a pending local action without naming one.

4.12G found that ``POST /v1/local-actions/{id}/approve`` approves on an
``action_id`` alone. 4.12J found that two *other* HTTP paths approve without any
id at all, which is worse: they need no prior knowledge and, in one case, no
second request.

* ``POST /v1/chat/completions`` with ``"yes"`` reaches
  ``_handle_confirmation_command`` -> ``latest_pending()`` -> ``_execute``.
  Whatever is pending runs, blind.
* ``POST /v1/voice/command`` with ``{"confirmed": true}`` stages *and* approves
  in the same call. The caller asserts its own confirmation as a request field.

This file pins the containment for those two. The invariant is deliberately
weaker than the one 4.13 will establish:

    No HTTP request may approve a pending local action without naming a
    specific ``action_id`` in a separate request.

``/v1/local-actions/{id}/approve`` and ``/v1/voice/confirm`` still approve on an
id with no out-of-band code. That is knowingly left open here -- closing it is
4.13's out-of-band-code work, and ``test_the_id_bearing_routes_are_still_open``
records that rather than letting it look accidental.

Nothing actuates: ``webbrowser.open`` and ``os.startfile`` are recorders, and
``GRANDPA_HOME`` is redirected so the approval store is a temp file.
"""

from __future__ import annotations

import os
import webbrowser
from typing import Any

import pytest

#: The phrases ``_handle_confirmation_command`` treats as approval. Duplicated
#: here rather than imported, because the point of the guard is that the HTTP
#: surface decides for itself what it will not forward. ``test_every_blocked
#: _phrase_really_is_a_confirmation`` proves the copy has not drifted.
APPROVAL_PHRASES = ("yes", "confirm", "approve", "run it", "do it")

#: A staged action whose execution is observable through a recorder.
STAGING_COMMAND = "open https://example.com"


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    """One approval store per test, in the test's own directory.

    ``conftest`` already redirects ``GRANDPA_HOME``, so the real
    ``~/.grandpa`` store is never in play -- but that redirect is session-wide,
    so pending rows would otherwise leak between tests. ``LocalActionApprovalStore``
    binds its default path at import time, so the substitution has to be on the
    name ``local_actions`` resolved, which is what ``tests/test_local_actions.py``
    does too.
    """
    import grandpa.local_actions as local_actions
    from grandpa.local_action_approvals import LocalActionApprovalStore

    isolated = LocalActionApprovalStore(tmp_path / "approvals.db")
    monkeypatch.setattr(local_actions, "LocalActionApprovalStore", lambda: isolated)
    return isolated


@pytest.fixture
def actuated(monkeypatch):
    """Record anything that would have reached the desktop."""
    seen: list[tuple[str, Any]] = []

    def recorder(name):
        def call(*args, **kwargs):
            seen.append((name, args[:1]))
            return True

        return call

    monkeypatch.setattr(webbrowser, "open", recorder("webbrowser.open"))
    monkeypatch.setattr(webbrowser, "open_new_tab", recorder("open_new_tab"))
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", recorder("os.startfile"))
    return seen


@pytest.fixture
def chat_client():
    """``/v1/chat/completions`` with a stand-in engine.

    The engine is never reached for a local action; it exists because the route
    reads ``app.state.engine`` before dispatching.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from grandpa.server.routes import router

    class _Engine:
        """Reached only when nothing local claims the text.

        A withheld confirmation phrase is *supposed* to arrive here: refusing it
        at the boundary means it becomes ordinary conversation, which is the
        least surprising thing the route can do with it.
        """

        def __getattr__(self, name):
            raise RuntimeError("engine stub")

    app = FastAPI()
    app.include_router(router)
    app.state.engine = _Engine()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def voice_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from grandpa.server.api_routes import voice_router

    app = FastAPI()
    app.include_router(voice_router)
    return TestClient(app)


def _say(client, text: str) -> str:
    """Send a chat turn and return the assistant text, or "" if it fell through.

    A local action answers with 200. Text nothing local claims reaches the
    engine stub, which is not an error for this file's purposes -- what matters
    is whether anything actuated.
    """
    body = {"model": "x", "messages": [{"role": "user", "content": text}]}
    response = client.post("/v1/chat/completions", json=body)
    if response.status_code != 200:
        return ""
    return response.json()["choices"][0]["message"]["content"]


def _say_locally_handled(client, text: str) -> str:
    """As above, but the turn must have been answered without the engine."""
    body = {"model": "x", "messages": [{"role": "user", "content": text}]}
    response = client.post("/v1/chat/completions", json=body)
    assert response.status_code == 200, response.text
    return response.json()["choices"][0]["message"]["content"]


def _pending_count(store) -> int:
    return len(store.list_pending())


# ---------------------------------------------------------------------------
# A/B -- the implicit confirmation phrase over HTTP chat
# ---------------------------------------------------------------------------


class TestChatCompletionsCannotConfirm:
    @pytest.mark.parametrize("phrase", APPROVAL_PHRASES)
    def test_a_confirmation_phrase_does_not_actuate(
        self, phrase: str, chat_client, actuated, store
    ) -> None:
        _say_locally_handled(chat_client, STAGING_COMMAND)
        assert _pending_count(store) == 1, "the action under test was never staged"

        _say(chat_client, phrase)

        assert actuated == [], phrase

    @pytest.mark.parametrize("phrase", APPROVAL_PHRASES)
    def test_the_pending_action_survives(
        self, phrase: str, chat_client, actuated, store
    ) -> None:
        """Not approved, not silently consumed -- still awaiting a real one."""
        _say(chat_client, STAGING_COMMAND)

        _say(chat_client, phrase)

        assert _pending_count(store) == 1, phrase

    @pytest.mark.parametrize("phrase", ("YES", "Yes.", " yes ", "Confirm!"))
    def test_casing_and_punctuation_do_not_slip_past(
        self, phrase: str, chat_client, actuated, store
    ) -> None:
        """The guard normalises the way Funnel A does, so these are the same word."""
        _say(chat_client, STAGING_COMMAND)

        _say(chat_client, phrase)

        assert actuated == [], phrase
        assert _pending_count(store) == 1, phrase

    def test_every_blocked_phrase_really_is_a_confirmation(self, actuated) -> None:
        """Drift guard: the copy above must still match Funnel A's behaviour.

        If ``_handle_confirmation_command`` gains or loses a phrase, this fails
        rather than leaving the HTTP guard quietly incomplete.
        """
        from grandpa.local_actions import handle_local_action

        for phrase in APPROVAL_PHRASES:
            handle_local_action(STAGING_COMMAND)
            result = handle_local_action(phrase)
            assert result.status != "no_match", phrase


# ---------------------------------------------------------------------------
# C/D -- the client-asserted confirmation flag
# ---------------------------------------------------------------------------


class TestVoiceCommandCannotSelfConfirm:
    """Live since M4 4.12K-B.

    These were ``xfail(strict=True)`` while
    ``tests/test_voice_v2.py::test_voice_command_confirmed_desktop_action_
    executes_with_mocked_automation`` still asserted the one-shot contract.
    4.12K-DEC superseded it, that test was amended to the two-step flow, and the
    call site now passes ``confirmed=False``.
    """

    def test_confirmed_true_does_not_actuate(self, voice_client, actuated) -> None:
        response = voice_client.post(
            "/v1/voice/command", json={"text": STAGING_COMMAND, "confirmed": True}
        )

        assert response.status_code == 200
        assert actuated == []

    def test_confirmed_true_still_asks_for_confirmation(
        self, voice_client, actuated
    ) -> None:
        response = voice_client.post(
            "/v1/voice/command", json={"text": STAGING_COMMAND, "confirmed": True}
        )

        assert response.json().get("action_status") == "needs_confirmation"

    def test_both_flags_now_agree(self, voice_client, actuated) -> None:
        """The flag no longer changes the outcome, which is the whole point."""
        first = voice_client.post(
            "/v1/voice/command", json={"text": STAGING_COMMAND, "confirmed": True}
        ).json()
        second = voice_client.post(
            "/v1/voice/command", json={"text": STAGING_COMMAND, "confirmed": False}
        ).json()

        assert first.get("action_status") == second.get("action_status")


# ---------------------------------------------------------------------------
# E/F -- what must not change
# ---------------------------------------------------------------------------


class TestLegitimateBehaviourIsUnchanged:
    def test_voice_command_without_confirmed_is_unchanged(
        self, voice_client, actuated
    ) -> None:
        """D: the honest case behaved correctly already and still does.

        Outside the xfail class on purpose -- this one passes today and must
        keep passing whichever way the ``confirmed`` decision goes.
        """
        response = voice_client.post(
            "/v1/voice/command", json={"text": STAGING_COMMAND, "confirmed": False}
        )

        assert response.json().get("action_status") == "needs_confirmation"
        assert actuated == []

    def test_a_non_confirmation_http_local_action_still_works(
        self, chat_client, actuated
    ) -> None:
        """E: only confirmation phrases are withheld from Funnel A."""
        reply = _say_locally_handled(chat_client, "what time is it")

        assert reply.strip()
        assert "confirmation" not in reply.lower()

    def test_a_staging_command_still_stages_over_http(
        self, chat_client, actuated, store
    ) -> None:
        reply = _say_locally_handled(chat_client, STAGING_COMMAND)

        assert "confirmation required" in reply.lower()
        assert _pending_count(store) == 1
        assert actuated == []

    def test_the_in_process_confirmation_path_is_untouched(self, actuated) -> None:
        """F: the CLI and local voice assistant call this directly.

        ``handle_local_action`` is unchanged, so a local operator's "yes" still
        approves the latest pending action. Containment lives at the HTTP entry,
        not in the shared function.
        """
        from grandpa.local_actions import handle_local_action

        staged = handle_local_action(STAGING_COMMAND)
        assert staged.status == "requires_confirmation"

        approved = handle_local_action("yes")

        assert approved.status == "handled"
        assert actuated != []

    def test_the_shared_confirmation_handler_is_unmodified(self) -> None:
        """The guard must not have been implemented by weakening Funnel A."""
        import inspect

        from grandpa.local_actions import _handle_confirmation_command

        source = inspect.getsource(_handle_confirmation_command)

        for phrase in APPROVAL_PHRASES:
            assert f'"{phrase}"' in source, phrase

    def test_handle_local_action_signature_is_unchanged(self) -> None:
        """AD-023 froze this signature; the containment must not touch it."""
        import inspect

        from grandpa.local_actions import handle_local_action

        signature = inspect.signature(handle_local_action)

        assert list(signature.parameters) == ["text", "execute"]


class TestWhatThisSliceDeliberatelyLeavesOpen:
    """Recorded so the remaining exposure is a decision, not an oversight."""

    def test_the_id_bearing_routes_are_still_open(self) -> None:
        """4.13 closes these with the out-of-band code. Not this slice."""
        from grandpa.server import api_routes, routes

        assert "approve_pending_action" in inspect_source(routes)
        assert "approve_pending_action" in inspect_source(api_routes)

    def test_voice_confirm_was_since_removed(self) -> None:
        """Left open by 4.12K, removed by 4.13E.

        The id-bearing routes were out of scope for this file's containment.
        One of them was later closed by deletion rather than by adding a code:
        the response that staged an action also carried the value that approved
        it, so no out-of-band credential was possible over that channel.
        """
        from grandpa.server import api_routes

        assert not hasattr(api_routes, "voice_confirm")


def inspect_source(module) -> str:
    import inspect

    return inspect.getsource(module)
