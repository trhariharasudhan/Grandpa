"""The startup banner, and the fact that chat actually prints it.

``render_startup_banner`` existed, read correctly, and was imported by
nothing -- a background model download or a Rust extension build was
invisible for the whole session that was waiting on it. The notification
dispatcher does not cover this: it is constructed from the opening snapshot
and treats everything already running as reported, so work in flight when
chat opens never transitions into view.
"""

from __future__ import annotations

import inspect

from grandpa.cli._bg_state import BgStatus
from grandpa.cli._chat_banner import render_startup_banner

# --- what the banner says ---------------------------------------------------


def test_nothing_to_say_once_everything_is_ready() -> None:
    """An empty string, because the caller prints nothing on empty."""
    status = BgStatus(rust_extension="ready", models={"llama3": "ready"})

    assert status.all_ready()
    assert render_startup_banner(status) == ""


def test_a_build_in_flight_is_named() -> None:
    status = BgStatus(rust_extension="pending")

    assert (
        render_startup_banner(status)
        == "Background: Rust extension building. Type to start."
    )


def test_a_download_in_flight_is_named() -> None:
    status = BgStatus(rust_extension="ready", models={"llama3": "downloading"})

    assert (
        render_startup_banner(status)
        == "Background: llama3 downloading. Type to start."
    )


def test_a_ready_model_is_not_mentioned() -> None:
    """Only what the person is still waiting on."""
    status = BgStatus(
        rust_extension="ready",
        models={"llama3": "ready", "qwen2": "downloading"},
    )

    banner = render_startup_banner(status)

    assert "qwen2" in banner
    assert "llama3" not in banner


def test_everything_in_flight_shares_one_line() -> None:
    status = BgStatus(
        rust_extension="pending",
        models={"llama3": "downloading", "qwen2": "failed"},
    )

    banner = render_startup_banner(status)

    assert "\n" not in banner
    assert banner.startswith("Background: ")
    assert banner.endswith(". Type to start.")
    assert "Rust extension building" in banner
    assert "llama3 downloading" in banner


def test_a_failure_says_where_to_look() -> None:
    """``Grandpa doctor`` is the surface that carries the error text itself."""
    status = BgStatus(rust_extension="failed", models={"llama3": "failed"})

    banner = render_startup_banner(status)

    assert banner.count("Grandpa doctor") == 2
    assert "Rust extension failed" in banner
    assert "llama3 failed" in banner


def test_a_banner_that_would_be_empty_is_empty() -> None:
    """``all_ready`` is false and yet there is nothing to report: a model in
    the ``pending`` state, which is neither finished nor started. The function
    must not return the bare furniture around an empty list."""
    status = BgStatus(rust_extension="ready", models={"llama3": "pending"})

    assert not status.all_ready()
    assert render_startup_banner(status) == ""


# --- and chat prints it -----------------------------------------------------


def test_chat_prints_the_banner_before_the_first_prompt() -> None:
    """Mechanical, because the defect was mechanical: the function was
    correct and unreachable, which no test of the function alone would
    notice."""
    from grandpa.cli import chat_cmd

    # .callback, because click wraps the function in a Command object.
    source = inspect.getsource(chat_cmd.chat.callback)
    startup = source[: source.index("while True:")]

    assert "render_startup_banner" in startup, (
        "chat must render the background banner at startup; the dispatcher "
        "only reports transitions and never the work already in flight"
    )


def test_the_banner_and_the_dispatcher_read_the_same_moment() -> None:
    """Two ``get_status()`` calls at startup could disagree -- a download that
    finishes between them is announced as a completion the banner never said
    was running."""
    from grandpa.cli import chat_cmd

    source = inspect.getsource(chat_cmd.chat.callback)
    startup = source[: source.index("while True:")]

    assert startup.count("get_status()") == 1
    assert "NotificationDispatcher(" in startup
