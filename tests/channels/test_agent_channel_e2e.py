"""Agent-channel resilience tests."""

from __future__ import annotations

from tests.agents.scenario_harness import ScenarioHarness


def test_channel_failure_does_not_crash_agent(scenario_harness: ScenarioHarness):
    """Agent continues if channel send fails."""
    h = scenario_harness
    agent = h.manager.create_agent(
        "Resilient Agent",
        config={
            "schedule_type": "manual",
            "instruction": "Try to send a message.",
        },
    )

    h.executor.execute_tick(agent["id"])
    data = h.manager.get_agent(agent["id"])
    assert data["status"] == "idle"
    assert data["total_runs"] == 1
