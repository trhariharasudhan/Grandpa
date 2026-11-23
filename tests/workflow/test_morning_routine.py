"""The sample morning routine (F3), end to end with the outside world mocked.

Unlike ``test_yaml_workflows.py``, nothing is mocked at ``executor._call``: the
real catalogue, executor and ``grandpa.briefing`` functions run. Only the edges
are replaced -- the weather HTTP call, the battery sensor, the reminder store's
location and the speaker -- so nothing leaves the machine or makes a sound.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from grandpa import briefing
from grandpa.reminders import ReminderStore
from grandpa.workflow.engine import WorkflowEngine
from grandpa.workflow.loader import load_yaml_workflow

_ROUTINE_REASON = (
    "runs the real grandpa.briefing; HTTP, the battery sensor and the speaker "
    "are replaced, and the reminder store is a tmp_path database"
)

ROUTINE = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "workflows"
    / "morning-routine.yaml"
)


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "audit" / "local_actions.jsonl"
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(path))
    return path


class FakeSpeaker:
    def __init__(self) -> None:
        self.said: list[str] = []

    def speak(self, text: str, on_start: Any) -> bool:
        self.said.append(text)
        return True


def _weather_api(url: str, params: dict[str, Any]) -> Any:
    if url == briefing.GEOCODE_URL:
        assert params["name"] == "Bengaluru"
        return {
            "results": [{"name": "Bengaluru", "latitude": 12.97, "longitude": 77.59}]
        }
    assert url == briefing.FORECAST_URL
    assert (params["latitude"], params["longitude"]) == (12.97, 77.59)
    return {
        "current": {"temperature_2m": 23.6, "weather_code": 2},
        "daily": {
            "temperature_2m_max": [28.2],
            "temperature_2m_min": [18.9],
            "precipitation_probability_max": [40],
        },
    }


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    store = ReminderStore(tmp_path / "reminders.db")
    speaker = FakeSpeaker()
    battery = SimpleNamespace(percent=17.4, power_plugged=False)
    monkeypatch.setattr(briefing, "_fetch_json", _weather_api)
    monkeypatch.setattr(briefing, "_sensors_battery", lambda: battery)
    monkeypatch.setattr(briefing, "_reminder_store", lambda: store)
    monkeypatch.setattr(briefing, "_speaker", lambda: (speaker, "Voice: test"))
    return SimpleNamespace(store=store, speaker=speaker, battery=battery)


def _today_at(hour: int, minute: int = 0) -> datetime:
    return (
        datetime.now()
        .astimezone()
        .replace(hour=hour, minute=minute, second=0, microsecond=0)
    )


@pytest.mark.real_actions(reason=_ROUTINE_REASON)
def test_morning_routine_speaks_weather_reminders_and_battery(
    world: SimpleNamespace, audit_log: Path
) -> None:
    world.store.create("stand-up call", _today_at(23, 30))
    world.store.create("pay the electricity bill", _today_at(23, 45))
    world.store.create("dentist", _today_at(10) + timedelta(days=2))

    result = WorkflowEngine().run(load_yaml_workflow(ROUTINE))

    assert result.success, result
    assert len(world.speaker.said) == 1
    said = world.speaker.said[0]
    assert said.startswith("Good morning Captain.")
    assert "In Bengaluru it is 24 degrees with partly cloudy" in said
    assert "between 19 and 28 degrees" in said
    assert "40 percent chance of rain" in said
    assert "You have 2 reminders today: stand-up call at 11:30 PM" in said
    assert "pay the electricity bill" in said
    assert "dentist" not in said
    assert "Battery is at 17 percent, on battery power. Please plug in" in said

    # Every step went through the action layer and its audit log.
    logged = [
        json.loads(line)["action_type"]
        for line in audit_log.read_text(encoding="utf-8").splitlines()
    ]
    for action in ("weather_now", "reminders_today", "battery_status", "speak_text"):
        assert action in logged


@pytest.mark.real_actions(reason=_ROUTINE_REASON)
def test_offline_morning_still_speaks_the_rest(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline(url: str, params: dict[str, Any]) -> Any:
        raise OSError("no network")

    monkeypatch.setattr(briefing, "_fetch_json", offline)
    world.battery.power_plugged = True

    result = WorkflowEngine().run(load_yaml_workflow(ROUTINE))

    assert result.success, result
    said = world.speaker.said[0]
    assert "I could not get the weather for Bengaluru right now." in said
    assert "You have no reminders for today." in said
    assert "charging." in said and "plug in" not in said


def test_dry_run_touches_nothing(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_run(url: str, params: dict[str, Any]) -> Any:
        raise AssertionError("dry run fetched the weather")

    monkeypatch.setattr(briefing, "_fetch_json", must_not_run)
    result = WorkflowEngine().run(load_yaml_workflow(ROUTINE), dry_run=True)
    assert result.success
    assert world.speaker.said == []


@pytest.mark.real_actions(reason="battery_status with the psutil sensor replaced")
def test_a_desktop_pc_has_no_battery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(briefing, "_sensors_battery", lambda: None)
    assert "no battery" in briefing.battery_status().message


@pytest.mark.real_actions(reason="speak_text with the speaker replaced by None")
def test_speak_text_without_a_voice_says_what_it_would_have_said(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(briefing, "_speaker", lambda: (None, "Voice: off."))
    result = briefing.speak_text("hello there")
    assert not result.success
    assert "hello there" in result.message


@pytest.mark.real_actions(reason="weather_now with the HTTP call replaced")
def test_unknown_city(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(briefing, "_fetch_json", lambda url, params: {})
    result = briefing.weather_now("Nowhereville")
    assert result.error == "unknown_city"
