"""App themes: default dark, light, high-contrast (WCAG AA), and plain (terminal colours)."""

from __future__ import annotations

from textual.theme import Theme

LANGSUITE = Theme(
    name="langsuite",
    primary="#7aa2f7",
    secondary="#bb9af7",
    accent="#7dcfff",
    foreground="#c0caf5",
    background="#16161e",
    surface="#1f2335",
    panel="#24283b",
    success="#9ece6a",
    warning="#e0af68",
    error="#f7768e",
    dark=True,
)
LANGSUITE_LIGHT = Theme(
    name="langsuite-light",
    primary="#2e5cb8",
    secondary="#7847bd",
    accent="#006c86",
    foreground="#1a1b26",
    background="#f5f6fa",
    surface="#e9ebf2",
    panel="#dde1ec",
    success="#2f7d32",
    warning="#8a5a00",
    error="#b3261e",
    dark=False,
)
# Pure black/white/yellow: text contrast 21:1 and 19.6:1, above WCAG AA 4.5:1.
LANGSUITE_HIGH_CONTRAST = Theme(
    name="langsuite-high-contrast",
    primary="#ffff00",
    secondary="#00ffff",
    accent="#ffff00",
    foreground="#ffffff",
    background="#000000",
    surface="#000000",
    panel="#000000",
    success="#00ff00",
    warning="#ffff00",
    error="#ff6060",
    dark=True,
)
THEMES: tuple[Theme, ...] = (LANGSUITE, LANGSUITE_LIGHT, LANGSUITE_HIGH_CONTRAST)
PLAIN_THEME = "ansi-dark"
