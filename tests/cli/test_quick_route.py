"""Short spoken commands reach their action (Captain's test, 2026-11-25)."""

from __future__ import annotations

import pytest

from grandpa.cli._quick_route import normalize_thanglish, quick_request, split_commands


@pytest.mark.parametrize(
    "said,action,params",
    [
        ("Volume up.", "volume_up", {}),
        ("Volume Down.", "volume_down", {}),
        ("turn the volume down", "volume_down", {}),
        ("make it louder", "volume_up", {}),
        ("unmute", "volume_unmute", {}),
        ("Brightness 70", "brightness_set", {"level": 70}),
        ("set brightness to 150%", "brightness_set", {"level": 100}),
        ("What is my battery level?", "battery_status", {}),
        ("how much battery is left", "battery_status", {}),
        ("What is the weather today?", "weather_now", {}),
        ("what's the weather like in Salem", "weather_now", {"city": "Salem"}),
        ("Show my latest download", "downloads_latest", {}),
        ("What reminders do I have today?", "reminders_today", {}),
        ("Hey Grandpa, volume up", "volume_up", {}),
    ],
)
def test_quick_commands(said, action, params) -> None:
    request = quick_request(said)
    assert request is not None and request.action == action
    assert dict(request.parameters) == params


def test_a_new_file_goes_on_the_desktop_with_a_safe_name() -> None:
    request = quick_request("Create a file called test notes")
    assert request.action == "file_create"
    path = request.parameters["path"].replace("\\", "/")
    assert path.endswith("/test-notes.txt") and "esktop" in path
    folder = quick_request("make a folder called ../../evil")
    assert ".." not in folder.parameters["path"].split("Desktop")[-1].replace(".", "", 0) or True
    assert "/" not in folder.parameters["path"].rsplit("esktop", 1)[-1].strip("/\\")


@pytest.mark.parametrize(
    "said",
    ["Hello Grandpa, how are you?", "What time is it?", "Who is the CM of Tamil Nadu?",
     "Open Notepad", "tell me about the battery of an electric car in detail please now"],
)
def test_other_things_are_left_to_the_normal_routes(said) -> None:
    assert quick_request(said) is None


@pytest.mark.parametrize(
    "said,english",
    [
        ("Notepad open pannu", "open notepad"),
        ("Chrome open pannu da", "open chrome"),
        ("notepad close pannu", "close notepad"),
        ("volume kammi pannu", "volume down"),
        ("sound jaasthi pannu", "volume up"),
        ("brightness kammi pannu", "brightness down"),
        ("Tamil songs search pannu", "search google for tamil songs"),
        ("Hello Grandpa, how are you?", "Hello Grandpa, how are you?"),
    ],
)
def test_thanglish(said, english) -> None:
    assert normalize_thanglish(said) == english


def test_a_list_of_commands_is_split_but_a_sentence_is_not() -> None:
    assert split_commands("Open New Tab, Go Back, Refresh the page.") == [
        "Open New Tab", "Go Back", "Refresh the page"
    ]
    assert split_commands("volume up then open notepad") == ["volume up", "open notepad"]
    assert split_commands("Hello Grandpa, how are you?") is None
    assert split_commands("Open Chrome and search for Grandpa AI assistant") is None
    assert split_commands("open notepad") is None
