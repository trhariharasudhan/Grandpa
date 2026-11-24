"""Grandpa's terminal themes: only the project's seven colours.

Every colour on screen comes from the seven palette bases in
:mod:`grandpa.cli.theme` (Light Gray, Blue, Yellow, Red, Purple, Green,
Orange) or from a tint or shade of one of them. Two values were chosen by the
project owner and are used as given:

* ``#B0A2E2`` (a soft purple) for what the user writes;
* ``#FFE2A4`` (a soft yellow) for what Grandpa replies.

The chat engine prints with Rich, and Rich brings its own colours (markdown
headings, code highlighting, link blue). :func:`ThemeColors.fit` maps every
colour the engine prints onto the nearest colour this theme allows, so nothing
outside the seven can reach the screen, and a dark-theme colour never lands
unreadable on the light background.

There are two themes, ``dark`` and ``light``. The choice is saved in
``~/.grandpa/tui_settings.json``.
"""

from __future__ import annotations

import colorsys
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from grandpa.cli.theme import (
    BLUE,
    GREEN,
    LIGHT_GRAY,
    ORANGE,
    PURPLE,
    RED,
    YELLOW,
    shade,
    tint,
)

#: The project owner's chosen message colours (dark theme).
USER_PURPLE = "#B0A2E2"
GRANDPA_YELLOW = "#FFE2A4"

BASES = {
    "light_gray": LIGHT_GRAY,
    "blue": BLUE,
    "yellow": YELLOW,
    "red": RED,
    "purple": PURPLE,
    "green": GREEN,
    "orange": ORANGE,
}

THEME_NAMES = ("dark", "light")


def rgb(colour: str) -> tuple[int, int, int]:
    raw = colour.lstrip("#")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _luminance(colour: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb(colour)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two colours."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@dataclass(frozen=True)
class ThemeColors:
    """The colours one theme uses, by role."""

    name: str
    dark: bool
    background: str
    surface: str  # input box, lists, bars
    panel: str  # header, selected rows
    border: str
    text: str
    muted: str  # hints, timestamps
    faint: str  # very quiet structure
    user: str  # what the user writes
    grandpa: str  # what Grandpa replies
    brand: str  # logo, focus border
    info: str  # links, Grandpa's label
    thinking: str  # spinner, warnings
    action: str  # tools being run
    voice: str  # microphone, speaking
    success: str
    error: str
    extra: tuple[str, ...] = field(default=())

    def allowed_foregrounds(self) -> tuple[str, ...]:
        """Colours text may be drawn in, all readable on ``background``."""
        return (
            self.text,
            self.muted,
            self.user,
            self.grandpa,
            self.brand,
            self.info,
            self.thinking,
            self.action,
            self.voice,
            self.success,
            self.error,
            *self.extra,
        )

    def allowed_backgrounds(self) -> tuple[str, ...]:
        return (self.background, self.surface, self.panel)

    def fit(self, colour: str, *, background: bool = False) -> str:
        """The allowed colour nearest to ``colour`` (hue first, then lightness)."""
        options = (
            self.allowed_backgrounds() if background else self.allowed_foregrounds()
        )
        return _nearest(colour.lower(), options)


def _hls(colour: str) -> tuple[float, float, float]:
    r, g, b = rgb(colour)
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)


@lru_cache(maxsize=4096)
def _nearest(colour: str, options: tuple[str, ...]) -> str:
    h, light, s = _hls(colour)
    best, best_score = options[0], float("inf")
    for option in options:
        oh, ol, os_ = _hls(option)
        if s < 0.15 or os_ < 0.15:
            # Greys: compare lightness and how grey they are; hue means nothing.
            score = abs(light - ol) * 2 + abs(s - os_) * 3
        else:
            hue = min(abs(h - oh), 1 - abs(h - oh)) * 2  # 0..1
            score = hue * 4 + abs(light - ol) + abs(s - os_) * 0.5
        if score < best_score:
            best, best_score = option, score
    return best


DARK = ThemeColors(
    name="dark",
    dark=True,
    background=shade(LIGHT_GRAY, 95),  # #0b0c0c
    surface=shade(LIGHT_GRAY, 90),  # #171717
    panel=shade(LIGHT_GRAY, 84),  # #252525
    border=shade(LIGHT_GRAY, 70),  # #454546
    text=LIGHT_GRAY,
    muted=shade(LIGHT_GRAY, 40),  # #898b8d
    faint=shade(LIGHT_GRAY, 58),
    user=USER_PURPLE,
    grandpa=GRANDPA_YELLOW,
    brand=YELLOW,
    info=tint(BLUE, 25),
    thinking=YELLOW,
    action=tint(PURPLE, 5),
    voice=ORANGE,
    success=GREEN,
    error=RED,
    extra=(tint(GREEN, 30), tint(ORANGE, 30), tint(RED, 25), tint(BLUE, 45)),
)

LIGHT = ThemeColors(
    name="light",
    dark=False,
    background=tint(LIGHT_GRAY, 75),  # #f9f9fa
    surface=tint(LIGHT_GRAY, 45),  # #f0f1f3
    panel=LIGHT_GRAY,
    border=shade(LIGHT_GRAY, 25),
    text=shade(LIGHT_GRAY, 88),  # #1b1c1c
    muted=shade(LIGHT_GRAY, 55),  # #67686a
    faint=shade(LIGHT_GRAY, 40),
    user=shade(PURPLE, 25),  # #7e40b9
    grandpa=shade(YELLOW, 55),  # #735e0e
    brand=shade(YELLOW, 50),
    info=shade(BLUE, 30),
    thinking=shade(ORANGE, 45),
    action=shade(PURPLE, 25),
    voice=shade(ORANGE, 40),
    success=shade(GREEN, 40),
    error=shade(RED, 25),
    extra=(shade(GREEN, 55), shade(BLUE, 50), shade(RED, 40)),
)

THEMES = {"dark": DARK, "light": LIGHT}


def textual_theme(colors: ThemeColors):
    """The Textual theme, so built-in widgets use the same colours."""
    from textual.theme import Theme

    return Theme(
        name=f"grandpa-{colors.name}",
        primary=colors.brand,
        secondary=colors.user,
        accent=colors.grandpa,
        warning=colors.thinking,
        error=colors.error,
        success=colors.success,
        foreground=colors.text,
        background=colors.background,
        surface=colors.surface,
        panel=colors.panel,
        dark=colors.dark,
        variables={
            "border": colors.border,
            "border-blurred": colors.border,
            "scrollbar": colors.panel,
            "scrollbar-hover": colors.border,
            "scrollbar-active": colors.muted,
            "scrollbar-background": colors.background,
            "scrollbar-corner-color": colors.background,
            "block-cursor-background": colors.brand,
            "block-cursor-foreground": colors.background,
            "block-cursor-blurred-background": colors.panel,
            "block-cursor-blurred-foreground": colors.text,
            "block-hover-background": colors.panel,
            "footer-key-foreground": colors.brand,
            "input-selection-background": f"{colors.user} 35%",
            "input-cursor-background": colors.text,
            "input-cursor-foreground": colors.background,
            "text-muted": colors.muted,
            "link-color": colors.info,
            "link-color-hover": colors.info,
        },
    )


# --- saved choice -------------------------------------------------------------


def settings_path() -> Path | None:
    try:
        from grandpa.runtime_paths import grandpa_home

        return grandpa_home() / "tui_settings.json"
    except Exception:  # noqa: BLE001
        return None


def load_settings(path: Path | None = None) -> dict:
    path = path if path is not None else settings_path()
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(values: dict, path: Path | None = None) -> None:
    path = path if path is not None else settings_path()
    if path is None:
        return
    try:
        current = load_settings(path)
        current.update(values)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except OSError:
        pass


def saved_theme_name(path: Path | None = None) -> str:
    name = load_settings(path).get("theme", "dark")
    return name if name in THEMES else "dark"


__all__ = [
    "BASES",
    "DARK",
    "GRANDPA_YELLOW",
    "LIGHT",
    "THEMES",
    "THEME_NAMES",
    "ThemeColors",
    "USER_PURPLE",
    "contrast",
    "load_settings",
    "save_settings",
    "saved_theme_name",
    "textual_theme",
]
