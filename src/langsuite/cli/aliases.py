"""Command registry: name, alias, help panel, one-line help, milestone (SPEC §6c)."""

from __future__ import annotations

from dataclasses import dataclass

EXPLORE = "Explore"
QUERY = "Query"
ANALYSE = "Analyse"
WORKSPACE = "Workspace"
WRITE = "Write"
ACCOUNT = "Account"
SYSTEM = "System"
PANELS: tuple[str, ...] = (EXPLORE, QUERY, ANALYSE, WORKSPACE, WRITE, ACCOUNT, SYSTEM)


@dataclass(frozen=True)
class Command:
    name: str
    alias: str
    panel: str
    help: str
    milestone: str


COMMANDS: tuple[Command, ...] = (
    Command("lang", "l", EXPLORE, "List languages or show one", "M1"),
    Command("feature", "ft", EXPLORE, "List or show language features", "M1"),
    Command("similar", "s", EXPLORE, "Languages most like a language", "M2"),
    Command("cluster", "c", EXPLORE, "Cluster languages into families", "M5"),
    Command("influence", "i", EXPLORE, "Influence graph around a language", "M5"),
    Command("dashboard", "db", EXPLORE, "Cluster dashboard with labels", "M5b"),
    Command("inclusion", "inc", EXPLORE, "Inclusion status and checks", "M5f"),
    Command("query", "q", QUERY, "Filter languages by features", "M2"),
    Command("ask", "a", QUERY, "Ask a cited question", "M5d"),
    Command("docs", "dc", QUERY, "Search or quote official docs", "M5f"),
    Command("rank", "r", ANALYSE, "Rank languages by score", "M5c"),
    Command("compare", "cp", ANALYSE, "Compare two languages", "M5c"),
    Command("diff", "df", ANALYSE, "Diff one task across languages", "M5c"),
    Command("like", "lk", ANALYSE, "Do X the way language Y does", "M5"),
    Command("finding", "f", WORKSPACE, "Save, list, show, export findings", "M3"),
    Command("note", "n", WORKSPACE, "Add or list notes", "M3"),
    Command("extract", "x", WORKSPACE, "Extract a result into a finding", "M3"),
    Command("workspace", "w", WORKSPACE, "Init, import, export, sync", "M3"),
    Command("base", "b", WORKSPACE, "Pull, pin, inspect base snapshots", "M5f"),
    Command("snippet", "sn", WRITE, "Write a verified code snippet", "M4"),
    Command("guide", "g", WRITE, "How to use a language, or when", "M5d"),
    Command("verify", "v", WRITE, "Run code in the sandbox verifier", "M4"),
    Command("account", "ac", ACCOUNT, "Username and account settings", "M5g"),
    Command("login", "li", ACCOUNT, "Sign in to langsuite", "M5i"),
    Command("logout", "lo", ACCOUNT, "Sign out", "M5i"),
    Command("usage", "u", ACCOUNT, "Plan usage and quota", "M5i"),
    Command("badges", "bg", ACCOUNT, "Your badges", "M5g"),
    Command("streak", "st", ACCOUNT, "Your streak", "M5g"),
    Command("settings", "set", SYSTEM, "Preferences such as gamification", "M5g"),
    Command("mode", "m", SYSTEM, "Show or set output mode", "M5h"),
    Command("tui", "t", SYSTEM, "Open the terminal UI", "M6"),
)

SUB_ALIASES: dict[str, str] = {"ls": "list", "sh": "show", "rm": "remove"}


def help_line(cmd: Command) -> str:
    """One help line, alias shown beside the name."""
    return f"{cmd.help} ({cmd.alias})"
