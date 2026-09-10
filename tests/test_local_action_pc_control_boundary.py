"""``_execute`` branches that run behind ``pc_control`` instead of beside it.

The 4.14 preflight found that twelve of ``_execute``'s thirteen branches called
a raw actuator directly: ``os.startfile``, ``webbrowser.open``, ``launch_app``,
``execute_automation`` and the rest. Only ``kind == "pc_control"`` went through
``run_local_action``, so the emergency stop, risk classification and the
``pc_control`` audit trail covered one branch out of thirteen.

This file accumulated across four slices, and each section below states which:

* **4.14A** -- two flat kind-to-action_type routes, both LOW risk there so
  neither gains a second approval prompt::

      kind="folder" -> open_folder
      kind="url"    -> browser_open

* **4.14D** -- five ``window`` verbs (``close``, ``focus``, ``minimize``,
  ``maximize``, ``restore``). They encode verb and target in one field, so they
  route by a separate map. 4.14C measured that every ``*_window`` action is
  MEDIUM but **none is in ``APPROVAL_REQUIRED_ACTIONS``**, so the existing
  ``local_actions`` confirmation stays the only prompt. ``list`` stays local: it
  is a read, and routing it would let the emergency stop block *querying*
  windows.

* **4.14E** -- ten ``browser`` targets: eight read-only observations plus
  ``about:blank`` and a Google search. The rest are carved out, each for its own
  reason, in ``TestTheCarveOutsStayLocal``.

* **AD-025 / 4.14P** -- ``automation`` is no longer here to route. The duplicate
  Funnel-A automation path was retired in favour of ``grandpa/automation/``, so
  ``TestTheOtherBranchesAreUnchanged`` asserts the kind cannot be minted at
  all, which is stronger than the "does not reach ``pc_control``" assertion it
  replaced.

``app`` was in the 4.14A slice and was pulled before landing. It maps cleanly to
``open_app`` and is LOW risk, but
``tests/test_windows_app_resolver.py::test_local_action_open_app_uses_resolver``
pins that an app launch returns the *resolved* executable path as its target,
and ``pc_control``'s application service does not surface that the same way --
two committed tests went from ``handled`` to ``error``. That is product
behaviour, not a stale assertion about routing, so ``app`` needs its own slice.

Still unrouted on purpose: ``agent_plan`` and ``chrome_profile`` have no
``pc_control`` action type, and inventing one is out of scope.

What routing buys: emergency stop, risk classification, a ``pc_control`` audit
line, and -- for ``folder`` -- a protected-path check that did not exist before.
The underlying actuators are unchanged: ``open_folder`` still ends at
``os.startfile``, ``browser_open`` still ends at ``webbrowser.open``.
"""

from __future__ import annotations

import os
import webbrowser
from typing import Any

import pytest

from grandpa.local_actions import LocalActionResult

#: kind -> the ``pc_control`` action type it must now route through.
ROUTED = {
    "folder": "open_folder",
    "url": "browser_open",
}

#: Kinds this suite deliberately leaves on their raw actuators.
#:
#: ``agent_plan`` and ``chrome_profile`` are also unrouted, but are not asserted
#: below: ``agent_plan`` delegates to ``create_goal``, whose agent legitimately
#: reaches ``pc_control`` for its own observation step (characterized in
#: 4.12E-1), so "did not reach ``pc_control``" is the wrong question for it.
#:
#: ``automation`` was the only member until AD-025 retired that path (4.14P).
#: Asserting "``automation`` does not reach ``pc_control``" now passes for the
#: wrong reason -- the kind cannot be minted at all -- so
#: ``TestTheRetiredAutomationKind`` below asserts the stronger property instead.
NOT_ROUTED: tuple[str, ...] = ()


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """Keep every store and log inside the test's own directory.

    ``conftest`` already redirects ``GRANDPA_HOME``; this narrows it further so
    one test cannot see another's audit rows. No production database is opened.
    """
    monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(tmp_path / "pc.db"))
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "audit.jsonl"))


@pytest.fixture
def funnel_b(monkeypatch):
    """Record the payloads reaching ``pc_control.run_local_action``."""
    import grandpa.pc_control as pc_control

    payloads: list[dict[str, Any]] = []

    def recorder(payload):
        payloads.append(dict(payload) if isinstance(payload, dict) else payload)
        return pc_control.LocalActionResponse(
            ok=True,
            action_id=None,
            status="completed",
            message="Done.",
            approval_required=False,
            risk_level="LOW",
            evidence={},
        )

    monkeypatch.setattr(pc_control, "run_local_action", recorder)
    return payloads


@pytest.fixture
def raw_actuators(monkeypatch):
    """Record any *direct* actuator call that bypasses ``pc_control``."""
    seen: list[str] = []

    def recorder(name):
        def call(*args, **kwargs):
            seen.append(name)
            return True

        return call

    monkeypatch.setattr(webbrowser, "open", recorder("webbrowser.open"))
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", recorder("os.startfile"))
    return seen


def _result(kind: str, target: str) -> LocalActionResult:
    return LocalActionResult(
        status="handled",
        kind=kind,
        target=target,
        message="Doing the thing.",
        tts_text="Doing the thing.",
        permission="allowed",
    )


def _execute(kind: str, target: str) -> LocalActionResult:
    from grandpa.local_actions import _execute as run

    return run(_result(kind, target))


TARGETS = {"folder": ".", "url": "https://example.com"}


# ---------------------------------------------------------------------------
# The routing itself
# ---------------------------------------------------------------------------


class TestTheThreeKindsRouteThroughPcControl:
    @pytest.mark.parametrize("kind,action_type", sorted(ROUTED.items()))
    def test_it_reaches_run_local_action(
        self, kind: str, action_type: str, funnel_b, raw_actuators
    ) -> None:
        _execute(kind, TARGETS[kind])

        assert len(funnel_b) == 1, kind
        assert funnel_b[0]["action_type"] == action_type

    @pytest.mark.parametrize("kind", sorted(ROUTED))
    def test_the_target_is_carried_through(
        self, kind: str, funnel_b, raw_actuators
    ) -> None:
        _execute(kind, TARGETS[kind])

        assert funnel_b[0]["target"] == TARGETS[kind]

    @pytest.mark.parametrize("kind", sorted(ROUTED))
    def test_no_raw_actuator_is_called_directly(
        self, kind: str, funnel_b, raw_actuators
    ) -> None:
        """6: no fallback path may reach the actuator around ``pc_control``."""
        _execute(kind, TARGETS[kind])

        assert raw_actuators == [], kind

    @pytest.mark.parametrize("kind", sorted(ROUTED))
    def test_no_second_approval_is_requested(
        self, kind: str, funnel_b, raw_actuators
    ) -> None:
        """These three are LOW risk, so the boundary must not stage them."""
        _execute(kind, TARGETS[kind])

        assert "require_approval" not in funnel_b[0] or not funnel_b[0].get(
            "require_approval"
        )

    @pytest.mark.parametrize("kind", sorted(ROUTED))
    def test_the_result_shape_is_preserved(
        self, kind: str, funnel_b, raw_actuators
    ) -> None:
        """1: the caller still gets a ``LocalActionResult`` of the same kind."""
        result = _execute(kind, TARGETS[kind])

        assert isinstance(result, LocalActionResult)
        assert result.kind == kind
        assert result.target == TARGETS[kind]
        assert result.status == "handled"
        assert result.permission == "allowed"

    @pytest.mark.parametrize("kind", sorted(ROUTED))
    def test_a_blocked_response_is_surfaced(
        self, kind: str, monkeypatch, raw_actuators
    ) -> None:
        """A refusal from the boundary must reach the user, not be swallowed."""
        import grandpa.pc_control as pc_control

        monkeypatch.setattr(
            pc_control,
            "run_local_action",
            lambda payload: pc_control.LocalActionResponse(
                ok=False,
                action_id=None,
                status="blocked",
                message="I blocked this action for safety.",
                approval_required=False,
                risk_level="HIGH",
                evidence={},
                error="protected_path",
            ),
        )

        result = _execute(kind, TARGETS[kind])

        assert result.status == "blocked", kind
        assert "blocked" in result.message.lower()
        assert raw_actuators == []


# ---------------------------------------------------------------------------
# What the boundary buys: emergency stop
# ---------------------------------------------------------------------------


class TestEmergencyStopNowCoversTheseKinds:
    """The point of the slice. Before it, e-stop covered one branch of thirteen."""

    @pytest.fixture(autouse=True)
    def _stop(self):
        import grandpa.pc_control as pc_control

        pc_control.reset_emergency_stop()
        pc_control.emergency_stop()
        yield
        pc_control.reset_emergency_stop()

    @pytest.mark.parametrize("kind", sorted(ROUTED))
    def test_the_emergency_stop_blocks_execution(
        self, kind: str, raw_actuators
    ) -> None:
        result = _execute(kind, TARGETS[kind])

        assert raw_actuators == [], kind
        assert result.status != "handled", kind

    @pytest.mark.parametrize("kind", sorted(ROUTED))
    def test_the_user_is_told_why(self, kind: str, raw_actuators) -> None:
        result = _execute(kind, TARGETS[kind])

        assert "emergency stop" in result.message.lower(), kind


class TestRiskStaysLow:
    @pytest.mark.parametrize("kind,action_type", sorted(ROUTED.items()))
    def test_the_action_classifies_low(self, kind: str, action_type: str) -> None:
        """Confirmed against the real classifier, not assumed."""
        from grandpa.desktop.kernel.requests import coerce_request
        from grandpa.desktop.kernel.risk import classify, requires_approval

        request = coerce_request(
            {"action_type": action_type, "target": TARGETS[kind], "args": {}}
        )

        assert classify(request) == "LOW", action_type
        assert requires_approval(request) is False, action_type

    def test_none_of_the_three_is_approval_required(self) -> None:
        from grandpa.pc_control import APPROVAL_REQUIRED_ACTIONS, BLOCKED_ACTIONS

        for action_type in ROUTED.values():
            assert action_type not in APPROVAL_REQUIRED_ACTIONS, action_type
            assert action_type not in BLOCKED_ACTIONS, action_type


# ---------------------------------------------------------------------------
# Both entrances use the same seam
# ---------------------------------------------------------------------------


class TestBothPathsUseTheSameSeam:
    """3 and 4: the direct allowed path and the post-approval path.

    ``_execute`` is called from two places -- once for an action classified
    ``allowed`` and once after a confirmation is approved. Routing has to sit in
    ``_execute`` itself, or one entrance would keep the old behaviour.
    """

    def test_the_direct_allowed_path_routes(
        self, funnel_b, raw_actuators, monkeypatch
    ) -> None:
        """The deterministic ``allowed`` path, isolated from the intent router.

        ``handle_local_action`` consults ``_route_with_intent_router`` first, and
        for this phrase the router escalates into the agent planner -- which
        issues its own ``desktop_summary`` and never reaches the folder branch.
        That escalation is real, already characterized in 4.12E-1, and unrelated
        to this slice; leaving it in would test the router rather than the seam.
        """
        import grandpa.local_actions as local_actions

        monkeypatch.setattr(
            local_actions, "_route_with_intent_router", lambda command: None
        )

        local_actions.handle_local_action("open my downloads folder")

        assert [p["action_type"] for p in funnel_b] == ["open_folder"]
        assert raw_actuators == []

    def test_the_approved_path_routes(self, tmp_path, monkeypatch, funnel_b) -> None:
        import grandpa.local_actions as local_actions
        from grandpa.local_action_approvals import LocalActionApprovalStore

        store = LocalActionApprovalStore(tmp_path / "approvals.db")
        monkeypatch.setattr(local_actions, "LocalActionApprovalStore", lambda: store)
        pending = store.create_pending(
            source_text="open https://example.com",
            kind="url",
            target="https://example.com",
            message="Confirmation required.",
            tts_text="Please confirm.",
        )

        local_actions.approve_pending_action(pending["id"])

        assert [p["action_type"] for p in funnel_b] == ["browser_open"]

    def test_routing_lives_in_execute_not_in_a_caller(self) -> None:
        """Structural: one seam, so neither entrance can drift from the other.

        The mapping is a module constant and the dispatch is inside
        ``_execute``; no caller decides. Both entrances call ``_execute``, so
        both get the boundary.
        """
        import inspect

        from grandpa import local_actions

        assert local_actions._PC_CONTROL_ROUTED_KINDS == ROUTED

        source = inspect.getsource(local_actions._execute)
        for kind in ROUTED:
            assert f'result.kind == "{kind}"' in source, kind
            assert "_execute_via_pc_control(result)" in source


# ---------------------------------------------------------------------------
# Scope: the other nine branches are untouched
# ---------------------------------------------------------------------------


class TestTheOtherBranchesAreUnchanged:
    def test_the_retired_automation_kind_is_not_minted(self, funnel_b) -> None:
        """AD-025/4.14P replaced the old ``NOT_ROUTED`` assertion.

        That assertion said ``kind="automation"`` did not reach ``pc_control``.
        It still passes, but only because the kind cannot be produced any more --
        a test that cannot fail. The property worth holding is the retirement
        itself: no command mints the kind, and nothing routed it in as a
        consolation prize.
        """
        import grandpa.local_actions as local_actions
        from grandpa.local_actions import handle_local_action

        assert not hasattr(local_actions, "_parse_automation_action")
        assert "automation" not in local_actions._PC_CONTROL_ROUTED_KINDS

        for command in ("type hello", "press enter", "scroll down"):
            assert handle_local_action(command, execute=False).kind != "automation"
        assert funnel_b == []

    def test_app_is_deliberately_not_routed(self, funnel_b, raw_actuators) -> None:
        """Pulled from this slice; see the module docstring for why."""
        import grandpa.local_actions as local_actions

        assert "app" not in local_actions._PC_CONTROL_ROUTED_KINDS

    def test_the_pc_control_kind_still_works(self, funnel_b, raw_actuators) -> None:
        """The branch that was already gated is unchanged."""
        _execute("pc_control", "desktop_summary|desktop")

        assert funnel_b[0]["action_type"] == "desktop_summary"

    def test_read_only_kinds_are_untouched(self, funnel_b) -> None:
        result = _execute("time", "")

        assert funnel_b == []
        assert result.kind == "time"


# ---------------------------------------------------------------------------
# Behaviour that must survive
# ---------------------------------------------------------------------------


class TestPreservedBehaviour:
    def test_a_missing_folder_still_reports_not_found(self, raw_actuators) -> None:
        """The existence check moved into ``pc_control``; it did not vanish.

        The wording changes -- ``pc_control`` says "I could not find the folder:
        X" where ``local_actions`` said "I could not find X." -- so this asserts
        the property, not the sentence.
        """
        result = _execute("folder", "Z:/definitely/not/here")

        assert result.status != "handled"
        assert "could not find" in result.message.lower()
        assert raw_actuators == []

    def test_the_url_actuator_is_still_webbrowser_open(self) -> None:
        """``browser_open`` ends at the same call the old branch made directly.

        Structural rather than behavioural: proving it end-to-end would mean
        opening a browser. This is why the swap is compatible.
        """
        import inspect

        from grandpa import browser_control

        source = inspect.getsource(browser_control.execute_browser_action)
        opening = source[source.index('if action == "open"') :]

        assert "webbrowser.open(url)" in opening

    def test_the_folder_actuator_is_still_startfile(self) -> None:
        import inspect

        from grandpa import pc_control

        assert "os.startfile" in inspect.getsource(pc_control._execute_open_folder)


# ---------------------------------------------------------------------------
# M4 4.14D -- window
# ---------------------------------------------------------------------------
#
# ``window`` encodes verb and target in one field (``close|chrome``), so it does
# not fit ``_PC_CONTROL_ROUTED_KINDS``' flat kind->action_type shape: the target
# has to be split and the verb suffixed. It routes through the same seam, with
# the action type and target passed explicitly.
#
# ``list`` is deliberately left behind. It is a read, and ``pc_control``'s
# emergency stop would otherwise block *querying* windows as well as changing
# them -- a behaviour change with no security benefit.
#
# 4.14C established the composition is safe here: every ``*_window`` action is
# MEDIUM but none is in ``APPROVAL_REQUIRED_ACTIONS``, so the existing
# ``local_actions`` confirmation for ``close|*`` stays the only prompt.

WINDOW_VERBS = {
    "close": "close_window",
    "focus": "focus_window",
    "minimize": "minimize_window",
    "maximize": "maximize_window",
    "restore": "restore_window",
}


class TestWindowVerbsRouteThroughPcControl:
    @pytest.mark.parametrize("verb,action_type", sorted(WINDOW_VERBS.items()))
    def test_the_verb_maps_to_its_window_action(
        self, verb: str, action_type: str, funnel_b
    ) -> None:
        _execute("window", f"{verb}|chrome")

        assert len(funnel_b) == 1, verb
        assert funnel_b[0]["action_type"] == action_type

    @pytest.mark.parametrize("verb", sorted(WINDOW_VERBS))
    def test_the_target_is_split_off(self, verb: str, funnel_b) -> None:
        _execute("window", f"{verb}|chrome")

        assert funnel_b[0]["target"] == "chrome"

    @pytest.mark.parametrize("verb", sorted(WINDOW_VERBS))
    def test_an_explicit_active_target_is_preserved(self, verb: str, funnel_b) -> None:
        _execute("window", f"{verb}|active")

        assert funnel_b[0]["target"] == "active"

    @pytest.mark.parametrize("verb", sorted(WINDOW_VERBS))
    def test_an_empty_target_defaults_to_active(self, verb: str, funnel_b) -> None:
        """The pre-4.14D branch used ``target or "active"``; so does this."""
        _execute("window", f"{verb}|")

        assert funnel_b[0]["target"] == "active"

    def test_a_target_containing_a_pipe_splits_only_once(self, funnel_b) -> None:
        """``partition`` semantics preserved -- the verb is the first field."""
        _execute("window", "close|a|b")

        assert funnel_b[0]["action_type"] == "close_window"
        assert funnel_b[0]["target"] == "a|b"

    @pytest.mark.parametrize("verb", sorted(WINDOW_VERBS))
    def test_no_second_approval_is_requested(self, verb: str, funnel_b) -> None:
        _execute("window", f"{verb}|chrome")

        assert not funnel_b[0].get("require_approval")

    @pytest.mark.parametrize("verb", sorted(WINDOW_VERBS))
    def test_the_result_shape_is_preserved(self, verb: str, funnel_b) -> None:
        result = _execute("window", f"{verb}|chrome")

        assert isinstance(result, LocalActionResult)
        assert result.kind == "window"
        assert result.target == f"{verb}|chrome"
        assert result.permission == "allowed"

    def test_the_raw_actuator_is_not_called_for_routed_verbs(
        self, funnel_b, monkeypatch
    ) -> None:
        import grandpa.windows_window_control as wwc

        called: list[str] = []
        monkeypatch.setattr(
            wwc, "control_window", lambda action, target: called.append(action)
        )

        for verb in WINDOW_VERBS:
            _execute("window", f"{verb}|chrome")

        assert called == []


class TestWindowStatusMappingIsPreserved:
    """``not_found`` and ``multiple_matches`` stay friendly, not errors.

    The pre-4.14D branch mapped both to ``handled`` deliberately: a window that
    is not open is an answer, not a failure. ``pc_control`` flattens both into a
    failed response, so the original status is recovered from
    ``evidence["window_status"]`` rather than lost.
    """

    @staticmethod
    def _respond(monkeypatch, window_status: str):
        import grandpa.pc_control as pc_control

        monkeypatch.setattr(
            pc_control,
            "run_local_action",
            lambda payload: pc_control.LocalActionResponse(
                ok=window_status == "handled",
                action_id=None,
                status="completed" if window_status == "handled" else "failed",
                message="No matching window.",
                approval_required=False,
                risk_level="MEDIUM",
                evidence={"window_status": window_status, "windows": []},
            ),
        )

    @pytest.mark.parametrize("window_status", ("not_found", "multiple_matches"))
    def test_a_friendly_status_is_still_handled(
        self, window_status: str, monkeypatch
    ) -> None:
        self._respond(monkeypatch, window_status)

        result = _execute("window", "close|chrome")

        assert result.status == "handled", window_status
        assert result.message == "No matching window."

    def test_a_real_error_is_still_an_error(self, monkeypatch) -> None:
        self._respond(monkeypatch, "error")

        assert _execute("window", "close|chrome").status == "error"

    def test_blocked_is_surfaced(self, monkeypatch) -> None:
        self._respond(monkeypatch, "blocked")

        assert _execute("window", "close|chrome").status == "blocked"

    def test_unsupported_is_surfaced(self, monkeypatch) -> None:
        self._respond(monkeypatch, "unsupported")

        assert _execute("window", "close|chrome").status == "unsupported"

    def test_a_handled_window_action_is_handled(self, monkeypatch) -> None:
        self._respond(monkeypatch, "handled")

        assert _execute("window", "close|chrome").status == "handled"


class TestListStaysLocal:
    """A read must not become mutation-gated."""

    @staticmethod
    def _lister(called=None):
        def call():
            if called is not None:
                called.append(True)
            return type(
                "R",
                (),
                {"status": "handled", "message": "Two windows.", "windows": ()},
            )()

        return call

    def test_list_does_not_reach_pc_control(self, funnel_b, monkeypatch) -> None:
        import grandpa.windows_window_control as wwc

        monkeypatch.setattr(wwc, "list_open_windows", self._lister())

        _execute("window", "list|windows")

        assert funnel_b == []

    def test_list_uses_the_local_lister(self, funnel_b, monkeypatch) -> None:
        import grandpa.windows_window_control as wwc

        called: list[bool] = []
        monkeypatch.setattr(wwc, "list_open_windows", self._lister(called))

        result = _execute("window", "list|windows")

        assert called == [True]
        assert result.status == "handled"
        assert result.message == "Two windows."

    def test_list_is_not_in_the_routed_verbs(self) -> None:
        import grandpa.local_actions as local_actions

        assert "list" not in local_actions._WINDOW_ROUTED_VERBS


class TestWindowSecurityGains:
    def test_the_emergency_stop_blocks_routed_verbs(self) -> None:
        import grandpa.pc_control as pc_control

        pc_control.reset_emergency_stop()
        pc_control.emergency_stop()
        try:
            result = _execute("window", "close|chrome")
        finally:
            pc_control.reset_emergency_stop()

        assert result.status != "handled"
        assert "emergency stop" in result.message.lower()

    @pytest.mark.parametrize("action_type", sorted(WINDOW_VERBS.values()))
    def test_the_action_classifies_medium_without_approval(
        self, action_type: str
    ) -> None:
        from grandpa.desktop.kernel.requests import coerce_request
        from grandpa.desktop.kernel.risk import classify, requires_approval

        request = coerce_request(
            {"action_type": action_type, "target": "chrome", "args": {}}
        )

        assert classify(request) == "MEDIUM", action_type
        assert requires_approval(request) is False, action_type

    def test_none_of_the_window_actions_is_approval_required(self) -> None:
        from grandpa.pc_control import APPROVAL_REQUIRED_ACTIONS

        for action_type in WINDOW_VERBS.values():
            assert action_type not in APPROVAL_REQUIRED_ACTIONS, action_type

    def test_closing_task_manager_is_still_blocked_upstream(self, funnel_b) -> None:
        """The block happens at classification, before ``_execute`` is reached."""
        import grandpa.local_actions as local_actions

        result = local_actions.handle_local_action("close task manager", execute=False)

        assert result.permission == "blocked"
        assert funnel_b == []


# ---------------------------------------------------------------------------
# M4 4.14E -- browser (partial)
# ---------------------------------------------------------------------------
#
# The browser branch mints twenty-one distinct targets, and they do not share a
# fate. Ten of them map onto ``pc_control`` vocabulary exactly, are LOW risk and
# are not approval-required, so routing them adds gates and changes nothing
# else. The rest are carved out, each for its own reason -- see
# ``TestTheCarveOutsStayLocal``.
#
# The routed set is deliberately the boring half: eight read-only observations
# plus two navigations whose ``pc_control`` action type already exists.

#: ``verb|suffix`` -> (action type, the target that must be forwarded).
#:
#: The suffixes here are the literals the parser actually mints -- ``active``,
#: ``recent``, ``visible`` -- so a routed call and the pre-4.14E call reach
#: ``execute_browser_action`` with identical arguments.
BROWSER_PIPE_ROUTED = {
    "buttons|visible": ("browser_buttons", "visible"),
    "context|active": ("browser_context", "active"),
    "headings|visible": ("browser_headings", "visible"),
    "links|visible": ("browser_links", "visible"),
    "media|pause": ("browser_media", "pause"),
    "summary|visible": ("browser_summary", "visible"),
    "tabs|recent": ("browser_tabs", "recent"),
    "task|book a flight": ("browser_task", "book a flight"),
}

#: A Google search as the parser mints it, and the query inside it.
GOOGLE_TARGET = "https://www.google.com/search?q=weather+in+chennai"
GOOGLE_QUERY = "weather in chennai"

#: A YouTube search as the parser mints it. Carved out: ``execute_browser_action``
#: has a ``youtube_search`` verb and ``pc_control`` has no action type for it.
YOUTUBE_TARGET = "https://www.youtube.com/results?search_query=lofi"

#: Targets this slice leaves on the raw actuator, with why.
#:
#: The first five are terminal stubs: ``execute_browser_action`` answers
#: ``requires_confirmation`` and returns without touching a browser, so routing
#: them would buy no gate and would flatten that status into ``unsupported``
#: (``pc_control`` has no ``requires_confirmation``). The last two are the same
#: stub *and* are in ``APPROVAL_REQUIRED_ACTIONS``, so routing them would demand
#: a second out-of-band code from the other approval store for an operation that
#: does not act.
BROWSER_NOT_ROUTED = (
    "back|visible",
    "click|first video",
    "download|visible selection",
    "focus_search|visible",
    "form_fill|city=chennai",
    "forward|visible",
    "reload|visible",
)

#: The subset of the above whose status does not depend on a live browser.
BROWSER_TERMINAL = tuple(
    t for t in BROWSER_NOT_ROUTED if not t.startswith("form_fill|")
)


@pytest.fixture
def no_browser_opens(monkeypatch):
    """Catch every raw browser actuator, including ``open_new_tab``.

    ``raw_actuators`` above does not patch ``open_new_tab``; ``about:blank`` is
    the one routed target that would have reached it.
    """
    seen: list[str] = []

    def recorder(name):
        def call(*args, **kwargs):
            seen.append(name)
            return True

        return call

    monkeypatch.setattr(webbrowser, "open", recorder("webbrowser.open"))
    monkeypatch.setattr(webbrowser, "open_new_tab", recorder("webbrowser.open_new_tab"))
    return seen


class TestRoutedBrowserVerbsReachPcControl:
    @pytest.mark.parametrize(
        "target,action_type",
        sorted((t, v[0]) for t, v in BROWSER_PIPE_ROUTED.items()),
    )
    def test_the_verb_maps_to_its_browser_action(
        self, target: str, action_type: str, funnel_b
    ) -> None:
        _execute("browser", target)

        assert len(funnel_b) == 1, target
        assert funnel_b[0]["action_type"] == action_type

    @pytest.mark.parametrize(
        "target,forwarded",
        sorted((t, v[1]) for t, v in BROWSER_PIPE_ROUTED.items()),
    )
    def test_the_suffix_is_forwarded_as_the_target(
        self, target: str, forwarded: str, funnel_b
    ) -> None:
        _execute("browser", target)

        assert funnel_b[0]["target"] == forwarded

    def test_a_suffix_containing_a_pipe_splits_only_once(self, funnel_b) -> None:
        """``partition`` semantics: the verb is the first field, nothing else."""
        _execute("browser", "task|compare a|b pricing")

        assert funnel_b[0]["action_type"] == "browser_task"
        assert funnel_b[0]["target"] == "compare a|b pricing"

    def test_about_blank_maps_to_new_tab(self, funnel_b) -> None:
        _execute("browser", "about:blank")

        assert len(funnel_b) == 1
        assert funnel_b[0]["action_type"] == "browser_new_tab"
        assert funnel_b[0]["target"] == "about:blank"

    def test_a_google_search_maps_to_browser_search(self, funnel_b) -> None:
        _execute("browser", GOOGLE_TARGET)

        assert len(funnel_b) == 1
        assert funnel_b[0]["action_type"] == "browser_search"

    def test_a_google_search_forwards_the_query_not_the_url(self, funnel_b) -> None:
        """``browser_search`` passes ``request.target`` to the search verb.

        The pre-4.14E branch extracted ``q`` and passed the query; forwarding the
        URL instead would search Google *for* a Google URL.
        """
        _execute("browser", GOOGLE_TARGET)

        assert funnel_b[0]["target"] == GOOGLE_QUERY
        assert "google.com" not in funnel_b[0]["target"]

    def test_the_defaults_the_parser_mints_survive_routing(self, funnel_b) -> None:
        """``active``/``recent``/``visible`` are load-bearing, not decoration.

        ``pc_control`` hardcodes the same literals for these action types, so a
        dropped target would pass unnoticed in production and only show up as a
        divergence here.
        """
        for target in ("context|active", "tabs|recent", "summary|visible"):
            funnel_b.clear()
            _execute("browser", target)
            assert funnel_b[0]["target"] == target.split("|", 1)[1], target

    @pytest.mark.parametrize("target", sorted(BROWSER_PIPE_ROUTED))
    def test_no_raw_actuator_is_reached(
        self, target: str, funnel_b, no_browser_opens
    ) -> None:
        _execute("browser", target)

        assert no_browser_opens == [], target

    @pytest.mark.parametrize("target", (GOOGLE_TARGET, "about:blank"))
    def test_the_routed_navigations_reach_no_raw_actuator(
        self, target: str, funnel_b, no_browser_opens
    ) -> None:
        _execute("browser", target)

        assert no_browser_opens == []

    @pytest.mark.parametrize("target", sorted(BROWSER_PIPE_ROUTED))
    def test_the_result_shape_is_preserved(self, target: str, funnel_b) -> None:
        result = _execute("browser", target)

        assert isinstance(result, LocalActionResult)
        assert result.kind == "browser"
        assert result.target == target
        assert result.permission == "allowed"
        assert result.status == "handled"

    def test_no_second_approval_is_requested(self, funnel_b) -> None:
        for target in BROWSER_PIPE_ROUTED:
            funnel_b.clear()
            _execute("browser", target)
            assert not funnel_b[0].get("require_approval"), target


class TestTheCarveOutsStayLocal:
    """Every browser target this slice does not route must be untouched."""

    @pytest.mark.parametrize("target", BROWSER_NOT_ROUTED)
    def test_it_does_not_reach_pc_control(self, target: str, funnel_b) -> None:
        _execute("browser", target)

        assert funnel_b == [], target

    @pytest.mark.parametrize("target", BROWSER_TERMINAL)
    def test_its_terminal_status_is_not_flattened(self, target: str, funnel_b) -> None:
        """``requires_confirmation`` survives because nothing maps it away.

        ``form_fill`` is excluded: it consults ``get_visible_browser_context``
        first and answers ``unsupported`` when there is no visible browser, so
        its status depends on the machine rather than on this slice.
        """
        result = _execute("browser", target)

        assert result.status == "requires_confirmation", target

    def test_youtube_search_does_not_reach_pc_control(
        self, funnel_b, no_browser_opens
    ) -> None:
        _execute("browser", YOUTUBE_TARGET)

        assert funnel_b == []

    def test_youtube_search_still_uses_the_local_verb(
        self, funnel_b, monkeypatch
    ) -> None:
        """The verb, the extracted query and the message all stay as they were."""
        import grandpa.browser_control as browser_control

        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            browser_control,
            "execute_browser_action",
            lambda action, target: (
                calls.append((action, target))
                or browser_control.BrowserActionResult("handled", action, target, "ok")
            ),
        )

        _execute("browser", YOUTUBE_TARGET)

        assert calls == [("youtube_search", "lofi")]

    def test_no_youtube_action_type_was_invented(self) -> None:
        """The carve-out exists precisely because this vocabulary is absent."""
        import inspect

        from grandpa import local_actions, pc_control

        assert "youtube" not in inspect.getsource(pc_control._execute_browser)
        assert "browser_youtube" not in inspect.getsource(local_actions)

    def test_diagnostics_was_not_added_to_the_routed_verbs(self) -> None:
        """``diagnostics|browser`` is claimed earlier, by the runtime skill.

        Routing it here would be dead code at best and a second dispatch for the
        same target at worst.
        """
        import grandpa.local_actions as local_actions

        assert "diagnostics" not in local_actions._BROWSER_ROUTED_VERBS


class TestBrowserSecurityGains:
    def test_the_emergency_stop_blocks_routed_browser_reads(self) -> None:
        import grandpa.pc_control as pc_control

        pc_control.reset_emergency_stop()
        pc_control.emergency_stop()
        try:
            result = _execute("browser", "summary|visible")
        finally:
            pc_control.reset_emergency_stop()

        assert result.status != "handled"
        assert "emergency stop" in result.message.lower()

    @pytest.mark.parametrize(
        "action_type",
        sorted({v[0] for v in BROWSER_PIPE_ROUTED.values()})
        + ["browser_new_tab", "browser_search"],
    )
    def test_the_action_classifies_low_without_approval(self, action_type: str) -> None:
        """The precondition for routing: one gate in, one gate out."""
        from grandpa.desktop.kernel.requests import coerce_request
        from grandpa.desktop.kernel.risk import classify, requires_approval

        request = coerce_request(
            {"action_type": action_type, "target": "visible", "args": {}}
        )

        assert classify(request) == "LOW", action_type
        assert requires_approval(request) is False, action_type

    @pytest.mark.parametrize(
        "action_type",
        sorted({v[0] for v in BROWSER_PIPE_ROUTED.values()})
        + ["browser_new_tab", "browser_search"],
    )
    def test_every_routed_action_type_already_existed(self, action_type: str) -> None:
        """No new ``pc_control`` vocabulary: each name is in its own mapping."""
        import inspect

        from grandpa import pc_control

        assert f'"{action_type}"' in inspect.getsource(pc_control._execute_browser)

    def test_routing_reuses_the_single_seam(self) -> None:
        """One execution boundary, not two."""
        import inspect

        from grandpa import local_actions

        source = inspect.getsource(local_actions._route_browser)

        assert "_execute_via_pc_control" in source
        assert "run_local_action" not in source
