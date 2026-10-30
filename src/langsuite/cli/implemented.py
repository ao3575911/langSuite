"""Commands that are built. Everything else in the registry is a milestone stub."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import typer

from langsuite.cli.account_cmds import account_app, badges, settings_app, streak
from langsuite.cli.analyse_cmds import (
    cluster,
    compare,
    dashboard_app,
    diff,
    influence,
    like,
    rank,
)
from langsuite.cli.ask_cmds import ask, guide
from langsuite.cli.bot_cmds import bot_app
from langsuite.cli.discover_cmds import query, similar
from langsuite.cli.docs_cmds import docs_app, inclusion_app
from langsuite.cli.kb_cmds import base_app, feature_app, lang_app
from langsuite.cli.mcp_server import mcp
from langsuite.cli.saas_cmds import login, logout, usage
from langsuite.cli.system_cmds import mode, webhook_app
from langsuite.cli.ui_cmd import ui
from langsuite.cli.verify_cmds import snippet, verify
from langsuite.cli.workspace_cmds import extract, finding_app, note_app, workspace_app

COMMAND_FUNCS: dict[str, Callable[..., Any]] = {
    "ui": ui,
    "query": query,
    "similar": similar,
    "extract": extract,
    "verify": verify,
    "snippet": snippet,
    "cluster": cluster,
    "influence": influence,
    "like": like,
    "rank": rank,
    "compare": compare,
    "diff": diff,
    "ask": ask,
    "guide": guide,
    "mode": mode,
    "mcp": mcp,
    "badges": badges,
    "streak": streak,
    "login": login,
    "logout": logout,
    "usage": usage,
}
GROUP_APPS: dict[str, typer.Typer] = {
    "lang": lang_app,
    "feature": feature_app,
    "base": base_app,
    "bot": bot_app,
    "dashboard": dashboard_app,
    "finding": finding_app,
    "note": note_app,
    "workspace": workspace_app,
    "webhook": webhook_app,
    "account": account_app,
    "settings": settings_app,
    "docs": docs_app,
    "inclusion": inclusion_app,
}
