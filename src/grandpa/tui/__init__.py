"""Grandpa's full-screen terminal interface (``grandpa`` with no arguments)."""

from __future__ import annotations

__all__ = ["main"]


def main(chat_args: list[str] | None = None) -> int:
    """Open the interface; fall back to the plain chat if it cannot draw."""
    from grandpa.tui.app import can_run_fullscreen, run

    if not can_run_fullscreen():
        return _plain(chat_args)
    try:
        return run(chat_args or [])
    except Exception:  # noqa: BLE001 - never leave the user with nothing
        import logging

        logging.getLogger(__name__).exception("full-screen interface failed")
        print("The full-screen interface could not start; opening the plain chat.")
        return _plain(chat_args)


def _plain(chat_args: list[str] | None) -> int:
    from grandpa.cli.chat_cmd import chat

    try:
        chat.main(
            args=["--no-fullscreen", *(chat_args or [])],
            prog_name="grandpa",
            standalone_mode=False,
        )
    except SystemExit as exc:
        return int(exc.code or 0) if isinstance(exc.code, int) else 1
    return 0
