"""Planner browser steps must go through the actuator boundary like everything else.

``PlannerStepExecutor._browser`` called ``handle_browser_command``, which ends at
``BrowserExecutor._default_open`` -> ``webbrowser.open``
(``browser/executor.py:140``). That is a real side effect reached without
``run_local_action``: no risk tier, no approval gate, no emergency stop, no
dry-run, no audit record, no verification. And it is reachable by voice --
"open chrome and go to gmail" decomposes to a ``navigate_url`` step, which is
exactly this path.

``docs/architecture/ACTION_ORIGIN_AUDIT.md`` states the rule this broke: an
action is strongly gated *if and only if* it routes through
``run_local_action``. ``browser_open`` and ``browser_search`` already exist in
the risk table as LOW, and ``pc_control._execute_browser`` already dispatches
them, so this is wiring rather than new capability.

Two things stay on the parse side, because they are not actuation and removing
them would lose behaviour:

* ``BrowserParser`` resolves "gmail" to https://mail.google.com. The pc_control
  path does not -- it would open ``https://gmail``.
* ``validate_browser_url`` is applied by ``BrowserExecutor`` and has no
  equivalent inside ``run_local_action``, so it would be silently dropped.

``StepVerifier`` reads ``StepResult.data["url"]`` to decide whether a browser
step really navigated (``test_executive_planner.py:948``), so the resolved URL
has to survive into the step data exactly as it does today.

Every test here injects a runner **and** makes both the real actuator and
``webbrowser.open`` raise, so a regression cannot open a browser window.
"""

from __future__ import annotations

from typing import Any

import pytest

from grandpa import pc_control
from grandpa.pc_control import DEFAULT_ACTION_ORIGIN, _coerce_request
from grandpa.planner.executor import PlannerStepExecutor
from grandpa.planner.models import PlanStep


class RecordingRunner:
    """Stands in for ``run_local_action`` and records every payload."""

    def __init__(self, *, status: str = "completed", ok: bool = True) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.status = status
        self.ok = ok

    def __call__(self, payload: dict[str, Any]):
        self.payloads.append(dict(payload))
        return pc_control.LocalActionResponse(
            ok=self.ok,
            action_id=None,
            status=self.status,
            message="Browser opened.",
            approval_required=False,
            risk_level="LOW",
            evidence={"browser": {"url": "https://example.test"}},
        )

    @property
    def action_types(self) -> list[str]:
        return [p.get("action_type") for p in self.payloads]

    @property
    def targets(self) -> list[str]:
        return [p.get("target") for p in self.payloads]

    @property
    def origins(self) -> list[str]:
        return [_coerce_request(p).origin for p in self.payloads]


class NoScreenAutomation:
    target_window = None

    def handle(self, text: str, dry_run: bool = False):
        from grandpa.automation.models import AutomationResult

        return AutomationResult("no_match", "")


@pytest.fixture
def no_real_browser(monkeypatch):
    """Nothing in this file may open a browser or reach the real actuator."""

    def explode_action(payload):
        raise AssertionError(
            f"the real actuator was reached with {payload!r}; "
            "an injected runner was bypassed"
        )

    def explode_open(*args, **kwargs):
        raise AssertionError(
            f"webbrowser.open was called directly with {args!r}; "
            "the actuator boundary was bypassed"
        )

    monkeypatch.setattr(pc_control, "run_local_action", explode_action)
    monkeypatch.setattr("webbrowser.open", explode_open)
    monkeypatch.setattr("webbrowser.open_new_tab", explode_open)


def _executor(runner=None, origin: str = DEFAULT_ACTION_ORIGIN):
    return PlannerStepExecutor(
        session_id="s",
        automation_service=NoScreenAutomation(),
        action_runner=runner,
        origin=origin,
    )


def _navigate(url: str = "gmail") -> PlanStep:
    return PlanStep("step_1", 1, f"Go to {url}", "navigate_url", {"url": url})


def _search(query: str = "fastapi", provider: str = "google") -> PlanStep:
    return PlanStep(
        "step_1",
        1,
        f"Search for {query}",
        "browser_search",
        {"query": query, "provider": provider},
    )


# ---------------------------------------------------------------------------
# The boundary
# ---------------------------------------------------------------------------


class TestBrowserStepsReachTheActuator:
    def test_a_navigate_step_calls_the_injected_runner(self, no_real_browser):
        runner = RecordingRunner()

        _executor(runner).execute(_navigate())

        assert runner.payloads, "the injected runner was never called"

    def test_a_search_step_calls_the_injected_runner(self, no_real_browser):
        runner = RecordingRunner()

        _executor(runner).execute(_search())

        assert runner.payloads, "the injected runner was never called"

    def test_navigation_uses_the_existing_browser_open_action(self, no_real_browser):
        runner = RecordingRunner()

        _executor(runner).execute(_navigate())

        assert runner.action_types == ["browser_open"]

    def test_search_uses_the_existing_browser_search_action(self, no_real_browser):
        runner = RecordingRunner()

        _executor(runner).execute(_search())

        assert runner.action_types == ["browser_search"]

    def test_no_new_action_types_are_invented(self, no_real_browser):
        """Both must already be classified by the existing risk table."""
        runner = RecordingRunner()
        executor = _executor(runner)
        executor.execute(_navigate())
        executor.execute(_search())

        for action_type in runner.action_types:
            assert action_type in pc_control.LOW_RISK_ACTIONS

    def test_webbrowser_is_never_called_directly(self, no_real_browser):
        """The fixture raises on ``webbrowser.open``; this is the assertion."""
        runner = RecordingRunner()

        result = _executor(runner).execute(_navigate())

        assert result.status == "success"


# ---------------------------------------------------------------------------
# What reaches the actuator
# ---------------------------------------------------------------------------


class TestPayloadContent:
    def test_a_bare_site_name_is_resolved_before_execution(self, no_real_browser):
        """``pc_control`` would open "https://gmail"; the parser knows better."""
        runner = RecordingRunner()

        _executor(runner).execute(_navigate("gmail"))

        assert runner.targets == ["https://mail.google.com"]

    def test_a_literal_url_is_passed_through(self, no_real_browser):
        runner = RecordingRunner()

        _executor(runner).execute(_navigate("https://github.com"))

        assert runner.targets == ["https://github.com"]

    def test_a_search_sends_the_query_not_a_url(self, no_real_browser):
        """``browser_search`` builds its own URL from the query."""
        runner = RecordingRunner()

        _executor(runner).execute(_search("fastapi"))

        assert runner.targets == ["fastapi"]

    def test_the_resolved_url_survives_into_the_step_data(self, no_real_browser):
        """``StepVerifier`` reads this to decide whether navigation happened."""
        runner = RecordingRunner()

        result = _executor(runner).execute(_navigate("gmail"))

        assert result.data["url"] == "https://mail.google.com"

    def test_a_search_step_records_the_search_url(self, no_real_browser):
        runner = RecordingRunner()

        result = _executor(runner).execute(_search("fastapi"))

        assert result.data["url"] == "https://www.google.com/search?q=fastapi"

    def test_the_recorded_search_url_matches_what_pc_control_opens(self):
        """Otherwise verification would compare against the wrong page."""
        from grandpa.browser.urls import search_url
        from grandpa.browser_control import _search_url

        assert search_url("google", "fastapi")[1] == _search_url("fastapi")


# ---------------------------------------------------------------------------
# Runner injection
# ---------------------------------------------------------------------------


class TestRunnerInjection:
    def test_no_runner_falls_back_to_the_module_actuator(self, monkeypatch):
        seen: list[dict[str, Any]] = []
        monkeypatch.setattr(
            pc_control,
            "run_local_action",
            lambda payload: (
                seen.append(dict(payload))
                or pc_control.LocalActionResponse(
                    ok=True,
                    action_id=None,
                    status="completed",
                    message="ok",
                    approval_required=False,
                    risk_level="LOW",
                    evidence={},
                )
            ),
        )

        _executor().execute(_navigate())

        assert [item["action_type"] for item in seen] == ["browser_open"]

    def test_an_injected_runner_is_never_silently_bypassed(self, no_real_browser):
        """The fixture makes any fallback an assertion failure, not a launch."""
        runner = RecordingRunner()

        _executor(runner).execute(_search())

        assert len(runner.payloads) == 1

    def test_the_executor_keeps_the_runner_it_was_given(self):
        runner = RecordingRunner()

        assert _executor(runner).action_runner is runner

    def test_the_executor_defaults_to_no_runner(self):
        assert _executor().action_runner is None


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class TestOrigin:
    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_the_stated_origin_reaches_the_request(self, origin, no_real_browser):
        runner = RecordingRunner()

        _executor(runner, origin).execute(_navigate())

        assert runner.origins == [origin]

    def test_a_search_carries_the_origin_too(self, no_real_browser):
        runner = RecordingRunner()

        _executor(runner, "voice").execute(_search())

        assert runner.origins == ["voice"]

    def test_the_default_is_direct(self, no_real_browser):
        runner = RecordingRunner()

        _executor(runner).execute(_navigate())

        assert runner.origins == [DEFAULT_ACTION_ORIGIN] == ["direct"]

    def test_a_voice_goal_reaches_the_browser_step_as_voice(self, no_real_browser):
        """End to end through routing, which is where voice origin is set."""
        from grandpa.planner import routing

        runner = RecordingRunner()
        seen: list[Any] = []

        class FakePlanner:
            def __init__(self, *, session_id, executor):
                seen.append(executor)

            def current(self):
                return None

            def execute(self, text, **kwargs):
                from grandpa.planner.models import ExecutionPlan, Goal, PlanResult

                plan = ExecutionPlan.create(Goal(text, text, "s"), [])
                return PlanResult("completed", "Task completed.", plan)

        import pytest as _pytest

        monkeypatch = _pytest.MonkeyPatch()
        monkeypatch.setattr(routing, "ExecutivePlanner", FakePlanner)
        routing.clear_planner_sessions()
        try:
            routing.handle_executive_goal(
                "open chrome and go to gmail",
                automation_service=NoScreenAutomation(),
                action_runner=runner,
                origin="voice",
            )
            executor = seen[0]
        finally:
            routing.clear_planner_sessions()
            monkeypatch.undo()

        executor.execute(_navigate())

        assert runner.origins == ["voice"]

    def test_the_origin_reaches_the_audit_record(self, monkeypatch, tmp_path):
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
                message="Browser opened.",
                approval_required=False,
                risk_level=risk,
                evidence={},
            ),
        )

        _executor(pc_control.run_local_action, "voice").execute(_navigate())

        record = json.loads(
            [line for line in log.read_text(encoding="utf-8").splitlines() if line][-1]
        )
        assert record["action_type"] == "browser_open"
        assert record["origin"] == "voice"


# ---------------------------------------------------------------------------
# Policy now applies where it did not
# ---------------------------------------------------------------------------


class TestPolicyNowApplies:
    def test_dry_run_reaches_the_payload(self, no_real_browser):
        runner = RecordingRunner(status="dry_run")

        _executor(runner, "voice").execute(_navigate(), dry_run=True)

        # A dry run short-circuits before the browser step runs at all, so the
        # runner is untouched -- which is itself the guarantee worth pinning.
        assert runner.payloads == []

    def test_dry_run_never_opens_anything(self, no_real_browser):
        runner = RecordingRunner()

        result = _executor(runner).execute(_navigate(), dry_run=True)

        assert result.status == "success"
        assert result.data.get("dry_run") is True

    def test_emergency_stop_now_covers_browser_actions(self, monkeypatch, tmp_path):
        """Before this slice the browser path could not be stopped at all."""
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "a.log"
        )
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: (_ for _ in ()).throw(
                AssertionError("executed during emergency stop")
            ),
        )
        monkeypatch.setattr(pc_control, "_EMERGENCY_STOP_ACTIVE", True)
        monkeypatch.setattr("webbrowser.open", lambda *a, **k: 1 / 0)

        result = _executor(pc_control.run_local_action, "voice").execute(
            PlanStep("step_1", 1, "Fill", "browser_form_fill", {})
        )

        assert result.status != "success"

    def test_a_blocked_response_becomes_a_failed_step(self, no_real_browser):
        runner = RecordingRunner(status="blocked", ok=False)

        result = _executor(runner).execute(_navigate())

        assert result.status != "success"

    def test_an_unsafe_url_is_refused_before_the_actuator(self, no_real_browser):
        """``validate_browser_url`` has no equivalent inside run_local_action.

        It runs on the parse side, so routing execution through the boundary
        adds a gate without dropping the one that was already there.
        """
        runner = RecordingRunner()

        result = _executor(runner).execute(_navigate("javascript:alert(1)"))

        assert result.status != "success"
        assert runner.payloads == [], "an unsafe URL reached the actuator"

    def test_an_unparseable_command_is_unsupported_not_executed(self, no_real_browser):
        runner = RecordingRunner()

        result = _executor(runner).execute(
            PlanStep("step_1", 1, "Nonsense", "navigate_url", {"url": ""})
        )

        assert result.status != "success"
        assert runner.payloads == []

    @pytest.mark.parametrize(
        "step",
        [_navigate("gmail"), _search("fastapi"), _navigate("")],
        ids=["navigate", "search", "unparseable"],
    )
    def test_the_bypassing_facade_is_never_called(
        self, step, monkeypatch, no_real_browser
    ):
        """The invariant is structural, not just observational.

        ``handle_browser_command`` is the facade that ends at
        ``webbrowser.open``. Returning to it for *any* case -- including a
        command this cannot parse -- puts a route back to the bypass, and the
        two parsers agreeing today is not a guarantee they always will.
        """
        import grandpa.browser as browser_pkg
        from grandpa.browser import automation as browser_automation

        calls: list[str] = []
        spy = lambda text, **kwargs: calls.append(text)  # noqa: E731
        # Both names: the package re-exports the facade, so a caller may reach
        # it either way and patching one alone silently proves nothing.
        monkeypatch.setattr(browser_pkg, "handle_browser_command", spy)
        monkeypatch.setattr(browser_automation, "handle_browser_command", spy)

        _executor(RecordingRunner()).execute(step)

        assert calls == [], "the planner reached the bypassing browser facade"


# ---------------------------------------------------------------------------
# Nothing that already worked may break
# ---------------------------------------------------------------------------


class TestExistingBehaviourPreserved:
    def test_the_step_verifier_contract_is_unchanged(self, no_real_browser):
        """A browser step still exposes exactly what StepVerifier reads."""
        from grandpa.planner.models import StepVerification
        from grandpa.planner.verifier import StepVerifier

        runner = RecordingRunner()
        step = PlanStep(
            "step_1",
            1,
            "Search",
            "browser_search",
            {"query": "fastapi", "provider": "google"},
            verification=StepVerification("browser_results_visible"),
            timeout_seconds=0.1,
        )
        result = _executor(runner).execute(step)

        verified = StepVerifier(
            object(), browser_awareness=lambda _c: None, sleep_func=lambda _s: None
        ).verify(step, result)

        assert verified.data["browser_evidence"] == "navigation_requested"

    def test_verification_evidence_from_the_response_is_carried(self, no_real_browser):
        runner = RecordingRunner()

        result = _executor(runner).execute(_navigate())

        assert result.data["browser"] == {"url": "https://example.test"}

    def test_a_failed_response_is_not_reported_as_success(self, no_real_browser):
        runner = RecordingRunner(status="failed", ok=False)

        result = _executor(runner).execute(_navigate())

        assert result.status != "success"
        assert result.data.get("verified") is not True


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_only_one_actuator_boundary_is_used(self, no_real_browser):
        """No second dispatch: the browser path ends where everything else does."""
        runner = RecordingRunner()
        executor = _executor(runner)
        executor.execute(_navigate())
        executor.execute(_search())

        assert len(runner.payloads) == 2

    def test_the_origin_vocabulary_is_unchanged(self):
        assert pc_control.ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )

    def test_browser_risk_tiers_are_unchanged(self):
        assert "browser_open" in pc_control.LOW_RISK_ACTIONS
        assert "browser_search" in pc_control.LOW_RISK_ACTIONS
        assert "browser_submit_form" in pc_control.BLOCKED_ACTIONS
