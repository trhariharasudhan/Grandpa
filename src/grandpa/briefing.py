"""Small read-only answers for a spoken briefing: weather, battery, today's reminders.

Each function is a catalogued action (``weather_now``, ``battery_status``,
``reminders_today``, ``speak_text``), so a workflow such as the sample
``morning-routine`` can use them as steps. They return an
:class:`~grandpa.action_layer.model.ActionResult` whose ``data`` holds the
values a later step can template (``{{ steps.weather.data.temperature }}``).

The weather comes from Open-Meteo (no account, no API key). Only the city name
and its coordinates leave this PC.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from grandpa.action_layer.model import ActionResult

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HTTP_TIMEOUT_S = 10.0

# WMO weather codes, as Open-Meteo reports them, in words a voice can say.
_WEATHER_WORDS: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "a thunderstorm",
    96: "a thunderstorm with hail",
    99: "a thunderstorm with heavy hail",
}


def _fetch_json(url: str, params: dict[str, Any]) -> Any:
    """GET ``url`` and return its JSON. The one place this module uses the network."""
    import httpx

    response = httpx.get(url, params=params, timeout=HTTP_TIMEOUT_S)
    response.raise_for_status()
    return response.json()


def _round(value: Any) -> int | None:
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def _first(values: Any) -> Any:
    if isinstance(values, list) and values:
        return values[0]
    return None


def weather_now(city: str = "Bengaluru") -> ActionResult:
    """Today's weather for ``city``: now, the high and low, and the chance of rain."""
    city = " ".join(str(city or "").split())
    if not city:
        return ActionResult.failed("invalid_parameters", message="Which city?")
    try:
        found = _fetch_json(
            GEOCODE_URL,
            {"name": city, "count": 1, "language": "en", "format": "json"},
        )
        places = (found.get("results") or []) if isinstance(found, dict) else []
        if not places:
            return ActionResult.failed(
                "unknown_city", message=f"I could not find a place called {city}."
            )
        place = places[0]
        forecast = _fetch_json(
            FORECAST_URL,
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,weather_code",
                "daily": (
                    "temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max"
                ),
                "timezone": "auto",
                "forecast_days": 1,
            },
        )
    except Exception as exc:  # noqa: BLE001 - offline must read as an answer
        logger.info("weather lookup failed: %s", exc)
        return ActionResult.failed(
            "weather_unavailable",
            message=f"I could not get the weather for {city} right now.",
        )

    name = str(place.get("name") or city)
    current = forecast.get("current") or {}
    daily = forecast.get("daily") or {}
    temperature = _round(current.get("temperature_2m"))
    code = current.get("weather_code")
    condition = _WEATHER_WORDS.get(int(code), "") if isinstance(code, int) else ""
    high = _round(_first(daily.get("temperature_2m_max")))
    low = _round(_first(daily.get("temperature_2m_min")))
    rain = _round(_first(daily.get("precipitation_probability_max")))
    if temperature is None:
        return ActionResult.failed(
            "weather_unavailable",
            message=f"I could not get the weather for {name} right now.",
        )

    parts = [f"In {name} it is {temperature} degrees"]
    if condition:
        parts[0] += f" with {condition}"
    if high is not None and low is not None:
        parts.append(f"today between {low} and {high} degrees")
    if rain is not None:
        parts.append(f"a {rain} percent chance of rain")
    message = ", ".join(parts) + "."
    return ActionResult.ok(
        message,
        city=name,
        temperature=temperature,
        condition=condition,
        high=high,
        low=low,
        rain_chance=rain,
    )


def _sensors_battery() -> Any:
    import psutil

    return psutil.sensors_battery()


def battery_status() -> ActionResult:
    """The battery level and whether the charger is plugged in."""
    try:
        battery = _sensors_battery()
    except Exception as exc:  # noqa: BLE001
        logger.info("battery read failed: %s", exc)
        battery = None
    if battery is None:
        return ActionResult.ok(
            "This PC reports no battery.", has_battery=False, percent=None
        )
    percent = _round(battery.percent)
    plugged = bool(battery.power_plugged)
    message = f"Battery is at {percent} percent" + (
        ", charging." if plugged else ", on battery power."
    )
    if not plugged and percent is not None and percent <= 20:
        message += " Please plug in the charger."
    return ActionResult.ok(message, has_battery=True, percent=percent, plugged=plugged)


def _reminder_store() -> Any:
    from grandpa.reminders import ReminderStore

    return ReminderStore()


def reminders_today() -> ActionResult:
    """The pending reminders due before midnight today, earliest first."""
    today = datetime.now().astimezone().date()
    items = []
    for reminder in _reminder_store().list(status="pending"):
        due = reminder.due_at.astimezone()
        if due.date() <= today:
            items.append((due, reminder.message))
    items.sort(key=lambda pair: pair[0])
    if not items:
        return ActionResult.ok("You have no reminders for today.", count=0, items=[])
    said = [
        f"{message} at {due.strftime('%I:%M %p').lstrip('0')}" for due, message in items
    ]
    count = len(items)
    noun = "reminder" if count == 1 else "reminders"
    message = f"You have {count} {noun} today: " + "; ".join(said) + "."
    return ActionResult.ok(
        message,
        count=count,
        items=[{"message": m, "due_at": d.isoformat()} for d, m in items],
    )


def _speaker() -> tuple[Any, str]:
    from grandpa.ui.lipsync import default_speaker

    return default_speaker()


def speak_text(text: str) -> ActionResult:
    """Say ``text`` aloud in the configured voice (ElevenLabs, Piper, or the local voice)."""
    clean = " ".join(str(text or "").split())
    if not clean:
        return ActionResult.failed("invalid_parameters", message="Nothing to say.")
    speaker, line = _speaker()
    if speaker is None:
        return ActionResult.failed(
            "voice_unavailable", message=f"{line} Not spoken: {clean}", text=clean
        )
    spoken = speaker.speak(clean, lambda _track, _start_ms: None)
    if not spoken:
        return ActionResult.failed(
            "voice_unavailable",
            message=f"The voice could not say it. Not spoken: {clean}",
            text=clean,
        )
    return ActionResult.ok(f"Said: {clean}", text=clean, voice=line)


__all__ = ["battery_status", "reminders_today", "speak_text", "weather_now"]
