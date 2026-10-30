"""Section panes. Unbuilt sections show a clear "planned" state."""

from __future__ import annotations

from collections.abc import Callable

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from langsuite.cli.aliases import COMMANDS
from langsuite.tui.sections import Section, section_for


class StubPane(VerticalScroll):
    def __init__(self, section: Section) -> None:
        super().__init__(id=f"pane-{section.id}", classes="pane")
        self.section = section

    def compose(self) -> ComposeResult:
        s = self.section
        yield Static(s.title, classes="pane-title")
        yield Static(s.blurb, classes="pane-blurb")
        yield Static(f"Planned for milestone {s.milestone}.", classes="pane-status")
        cmds = [c for c in COMMANDS if section_for(c) == s.id]
        if cmds:
            lines = "\n".join(f"  g {c.alias:<4} {c.name:<10} {c.help}" for c in cmds)
            yield Static(f"Shorthands\n{lines}", classes="pane-cmds", markup=False)


PaneFactory = Callable[[Section], Widget]
PANE_FACTORIES: dict[str, PaneFactory] = {}
BUILT_SECTIONS: set[str] = set()


def make_pane(section: Section) -> Widget:
    factory = PANE_FACTORIES.get(section.id)
    return factory(section) if factory else StubPane(section)


def _register_built() -> None:
    from langsuite.tui.bot_pane import BotPane
    from langsuite.tui.command_pane import AnalysePane, DashboardPane
    from langsuite.tui.explore import ExplorePane
    from langsuite.tui.query_pane import QueryPane
    from langsuite.tui.workspace_pane import WorkspacePane
    from langsuite.tui.write_pane import WritePane

    PANE_FACTORIES["explore"] = ExplorePane
    PANE_FACTORIES["query"] = QueryPane
    PANE_FACTORIES["workspace"] = WorkspacePane
    PANE_FACTORIES["write"] = WritePane
    PANE_FACTORIES["account"] = BotPane
    PANE_FACTORIES["dashboard"] = DashboardPane
    PANE_FACTORIES["analyse"] = AnalysePane
    BUILT_SECTIONS.update(
        {"dashboard", "analyse", "explore", "query", "workspace", "write", "account"}
    )


_register_built()
