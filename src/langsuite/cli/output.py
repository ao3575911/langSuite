"""Rich theme `langsuite` and plain/JSON fallbacks (SPEC §6c). Stub for M0."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from rich.console import Console
from rich.theme import Theme

JSON_SCHEMA_VERSION = 1

THEME = Theme(
    {
        "lw.title": "bold #7aa2f7",
        "lw.accent": "#bb9af7",
        "lw.ok": "#9ece6a",
        "lw.warn": "#e0af68",
        "lw.error": "bold #f7768e",
        "lw.muted": "#787c99",
        "lw.cite": "italic #7dcfff",
        "lw.grade.a": "bold #9ece6a",
        "lw.grade.b": "#73daca",
        "lw.grade.c": "#e0af68",
        "lw.grade.d": "#ff9e64",
        "lw.grade.f": "bold #f7768e",
    },
    inherit=True,
)


def plain_wanted(force_plain: bool = False) -> bool:
    """Plain output when asked, when NO_COLOR is set, or when stdout is not a TTY."""
    return force_plain or "NO_COLOR" in os.environ or not sys.stdout.isatty()


def make_console(plain: bool = False, stderr: bool = False) -> Console:
    if plain:
        return Console(
            theme=THEME,
            no_color=True,
            color_system=None,
            highlight=False,
            emoji=False,
            stderr=stderr,
            force_terminal=False,
        )
    return Console(theme=THEME, stderr=stderr)


def to_json(kind: str, data: Any) -> str:
    """Stable, versioned JSON envelope."""
    return json.dumps(
        {"schema": JSON_SCHEMA_VERSION, "kind": kind, "data": data},
        sort_keys=True,
        ensure_ascii=False,
    )
