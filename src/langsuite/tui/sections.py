"""App sections (left nav) and how every CLI command maps onto them (SPEC §6e)."""

from __future__ import annotations

from dataclasses import dataclass

from langsuite.cli.aliases import COMMANDS, Command


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    key: str
    milestone: str
    blurb: str


SECTIONS: tuple[Section, ...] = (
    Section("dashboard", "Dashboard", "1", "M5b", "Clusters of similar languages, with labels."),
    Section("explore", "Explore", "2", "M1", "Search languages and features, with evidence."),
    Section("query", "Query", "3", "M2", "Filter languages by features."),
    Section("analyse", "Analyse", "4", "M5c", "Rank, compare and diff languages."),
    Section("workspace", "Workspace", "5", "M3", "Findings, notes and saved queries."),
    Section("write", "Write", "6", "M4", "Verified snippets and guides."),
    Section("account", "Account", "7", "M5g", "Handle, usage, badges and settings."),
)

_PANEL_TO_SECTION = {
    "Explore": "explore",
    "Query": "query",
    "Analyse": "analyse",
    "Workspace": "workspace",
    "Write": "write",
    "Account": "account",
    "System": "account",
}
_OVERRIDES = {"dashboard": "dashboard", "cluster": "dashboard", "mode": "", "ui": ""}


def section_for(cmd: Command) -> str:
    """Section a command opens; '' means an in-place action (mode, ui)."""
    return _OVERRIDES.get(cmd.name, _PANEL_TO_SECTION[cmd.panel])


ALIAS_INDEX: dict[str, Command] = {c.alias: c for c in COMMANDS}


def leader_candidates(buffer: str) -> list[Command]:
    return [c for c in COMMANDS if c.alias.startswith(buffer)]
