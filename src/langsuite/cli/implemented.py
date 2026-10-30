"""Commands that are built. Everything else in the registry is a milestone stub."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import typer

from langsuite.cli.discover_cmds import query, similar
from langsuite.cli.kb_cmds import base_app, feature_app, lang_app
from langsuite.cli.ui_cmd import ui

COMMAND_FUNCS: dict[str, Callable[..., Any]] = {"ui": ui, "query": query, "similar": similar}
GROUP_APPS: dict[str, typer.Typer] = {"lang": lang_app, "feature": feature_app, "base": base_app}
