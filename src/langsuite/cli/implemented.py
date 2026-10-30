"""Commands that are built. Everything else in the registry is a milestone stub."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import typer

from langsuite.cli.ui_cmd import ui

COMMAND_FUNCS: dict[str, Callable[..., Any]] = {"ui": ui}
GROUP_APPS: dict[str, typer.Typer] = {}
