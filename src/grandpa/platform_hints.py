"""Install hints that depend on the operating system.

Grandpa runs on Windows and Linux (and macOS), so advice such as "install
Ollama" must point at the installer for the system the user is actually on.
"""

from __future__ import annotations

import sys

OLLAMA_WINDOWS = "https://ollama.com/download/windows"
OLLAMA_MAC = "https://ollama.com/download/mac"
OLLAMA_LINUX = "curl -fsSL https://ollama.com/install.sh | sh"


def ollama_installer(platform: str | None = None) -> str:
    """The download page (Windows, macOS) or the install command (Linux)."""
    platform = platform or sys.platform
    if platform.startswith("win"):
        return OLLAMA_WINDOWS
    if platform == "darwin":
        return OLLAMA_MAC
    return OLLAMA_LINUX


def install_ollama_hint(platform: str | None = None) -> str:
    """``Install Ollama from <page>`` or ``Install Ollama with: <command>``."""
    installer = ollama_installer(platform)
    if installer.startswith("http"):
        return f"Install Ollama from {installer}"
    return f"Install Ollama with: {installer}"


__all__ = ["install_ollama_hint", "ollama_installer"]
