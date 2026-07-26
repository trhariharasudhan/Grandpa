"""Read-only Screen Vision v1."""

from grandpa.screen.intents import handle_screen_command
from grandpa.screen.service import ScreenVisionService

__all__ = ["ScreenVisionService", "handle_screen_command"]
