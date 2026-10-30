"""The langsuite Textual app shell (SPEC §6e, milestone M0b)."""

from __future__ import annotations

from collections.abc import Iterable
from functools import partial
from typing import ClassVar

from textual import on
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding, BindingType
from textual.command import Hit, Hits, Provider
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import ContentSwitcher, Footer, Label, ListItem, ListView, TabbedContent

from langsuite.cli.aliases import COMMANDS, Command
from langsuite.core.kb import read_manifest
from langsuite.core.modes import Mode
from langsuite.tui.leader import LeaderScreen
from langsuite.tui.panes import BUILT_SECTIONS, make_pane
from langsuite.tui.sections import ALIAS_INDEX, SECTIONS, section_for
from langsuite.tui.themes import PLAIN_THEME, THEMES
from langsuite.tui.widgets import HeaderBar, ModeChip

MODES: tuple[str, ...] = tuple(m.value for m in Mode)


def _default_handle() -> str:
    """`$langsuite/guest/<active workspace>` until accounts land (M5g)."""
    from langsuite.core.errors import LangsuiteError
    from langsuite.core.workspace import active_slug

    try:
        return f"$langsuite/guest/{active_slug()}"
    except LangsuiteError:
        return "$langsuite/guest/default"


def base_label() -> str:
    """`base <id> · <age>d`, or `base: none` before the first build."""
    manifest = read_manifest()
    if manifest is None:
        return "base: none"
    stale = " stale" if manifest.stale else ""
    return f"{manifest.snapshot_id} · {manifest.age_days()}d{stale}"


class CommandsProvider(Provider):
    """Every CLI command and alias in the palette; typing an alias ranks it first."""

    def _hit_text(self, cmd: Command) -> str:
        return f"{cmd.alias}  {cmd.name} — {cmd.help}"

    async def search(self, query: str) -> Hits:
        app = self.app
        assert isinstance(app, LangsuiteApp)
        matcher = self.matcher(query)
        for cmd in COMMANDS:
            text = self._hit_text(cmd)
            score = 1.0 if query.strip() == cmd.alias else matcher.match(text)
            if score > 0:
                yield Hit(
                    score, matcher.highlight(text), partial(app.run_command, cmd), help=cmd.panel
                )

    async def discover(self) -> Hits:
        app = self.app
        assert isinstance(app, LangsuiteApp)
        for cmd in COMMANDS:
            yield Hit(0.5, self._hit_text(cmd), partial(app.run_command, cmd))


class LangsuiteApp(App[None]):
    TITLE = "langsuite"
    CSS_PATH = "app.tcss"
    COMMANDS: ClassVar = App.COMMANDS | {CommandsProvider}
    BINDINGS: ClassVar[list[BindingType]] = [
        *[Binding(s.key, f"show('{s.id}')", s.title, show=False) for s in SECTIONS],
        Binding("g", "leader", "Shorthand"),
        Binding("f2", "cycle_mode", "Mode"),
        Binding("f3", "cycle_theme", "Theme"),
        Binding("ctrl+p", "command_palette", "Palette"),
        Binding("question_mark", "show_help_panel", "Help", key_display="?"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(
        self,
        plain: bool = False,
        mode: str = "default",
        handle: str | None = None,
    ) -> None:
        super().__init__()
        self.plain = plain
        self.mode_name = mode if mode in MODES else "default"
        self.handle = handle or _default_handle()
        self._themes = [t.name for t in THEMES]
        for theme in THEMES:
            self.register_theme(theme)
        self.theme = PLAIN_THEME if plain else "langsuite"

    def compose(self) -> ComposeResult:
        header = HeaderBar(id="header")
        header.handle = self.handle
        header.mode = self.mode_name
        header.base = base_label()
        yield header
        with Horizontal(id="body"):
            yield ListView(
                *[ListItem(Label(f"{s.key} {s.title}"), id=f"nav-{s.id}") for s in SECTIONS],
                id="nav",
            )
            with ContentSwitcher(id="main", initial="pane-dashboard"):
                for s in SECTIONS:
                    yield make_pane(s)
        yield Footer()

    def on_mount(self) -> None:
        self.set_class(self.plain, "-plain")

    def get_system_commands(self, screen: Screen[object]) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        for mode in MODES:
            yield SystemCommand(
                f"Mode: {mode}", f"Output mode {mode}", partial(self.set_mode, mode)
            )
        yield SystemCommand(
            "Theme: high contrast",
            "WCAG AA high-contrast theme",
            partial(setattr, self, "theme", "langsuite-high-contrast"),
        )
        yield SystemCommand("Plain mode", "Screen-reader friendly, no borders", self.toggle_plain)

    # navigation
    def action_show(self, section_id: str) -> None:
        self.query_one("#main", ContentSwitcher).current = f"pane-{section_id}"
        self.query_one("#nav", ListView).index = [s.id for s in SECTIONS].index(section_id)

    @on(ListView.Highlighted, "#nav")
    def _nav(self, event: ListView.Highlighted) -> None:
        if event.item is not None and event.item.id:
            self.query_one("#main", ContentSwitcher).current = event.item.id.replace(
                "nav-", "pane-"
            )

    def run_command(self, cmd: Command) -> None:
        if cmd.name == "mode":
            self.action_cycle_mode()
            return
        if cmd.name == "ui":
            self.notify("You are in the app.", timeout=2)
            return
        target = section_for(cmd)
        self.action_show(target)
        if target == "explore":
            self.query_one("#explore-search").focus()
            if cmd.name == "similar":
                self.query_one("#explore-tabs", TabbedContent).active = "tab-similar"
        if target == "query":
            self.query_one("#query-input").focus()
        if target == "workspace":
            self.query_one("#ws-findings").focus()
        if target not in BUILT_SECTIONS:
            from langsuite.cli.implemented import GROUP_APPS

            if cmd.name in GROUP_APPS:
                self.notify(
                    f"`langsuite {cmd.name}` works in the terminal; pane planned ({cmd.milestone})",
                    timeout=3,
                )
            else:
                self.notify(f"{cmd.name}: planned ({cmd.milestone})", timeout=3)

    # leader keys
    def action_leader(self) -> None:
        if isinstance(self.screen, LeaderScreen):
            self.screen.feed("g")
            return

        def done(alias: str | None) -> None:
            if not alias:
                return
            cmd = ALIAS_INDEX.get(alias)
            if cmd:
                self.run_command(cmd)
            else:
                self.notify(f"No shorthand '{alias}'", severity="warning", timeout=2)

        self.push_screen(LeaderScreen(), done)

    # modes and themes
    def set_mode(self, mode: str) -> None:
        self.mode_name = mode
        self.query_one(HeaderBar).mode = mode
        self.notify(f"Mode: {mode}", timeout=2)

    def action_cycle_mode(self) -> None:
        self.set_mode(MODES[(MODES.index(self.mode_name) + 1) % len(MODES)])

    @on(ModeChip.Cycle)
    def _mode_clicked(self) -> None:
        self.action_cycle_mode()

    def action_cycle_theme(self) -> None:
        cur = self.theme if self.theme in self._themes else self._themes[-1]
        self.theme = self._themes[(self._themes.index(cur) + 1) % len(self._themes)]
        self.notify(f"Theme: {self.theme}", timeout=2)

    def toggle_plain(self) -> None:
        self.plain = not self.plain
        self.set_class(self.plain, "-plain")
        self.theme = PLAIN_THEME if self.plain else "langsuite"
