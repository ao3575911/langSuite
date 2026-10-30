"""Dashboard and Analyse panes (M5b, M5c): run the CLI command in-process, show its output.

The output is the CLI's own plain rendering, so the pane and the CLI never disagree.
"""

from __future__ import annotations

import shlex

from rich.markup import escape
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Static

from langsuite.cli.inproc import run_plain
from langsuite.tui.sections import Section


class CommandPane(Vertical):
    TITLE = ""
    PRESETS: tuple[tuple[str, str], ...] = ()
    START = ""

    def __init__(self, section: Section, pane_id: str | None = None) -> None:
        super().__init__(id=pane_id or f"pane-{section.id}", classes="pane cmdpane")
        self.section = section
        self.last_code = 0

    def compose(self) -> ComposeResult:
        sid = self.section.id
        yield Static(self.TITLE, classes="pane-title")
        yield Static(self.section.blurb, classes="pane-blurb")
        with Horizontal(classes="cmd-presets"):
            for n, (label, _) in enumerate(self.PRESETS):
                yield Button(label, id=f"{sid}-preset-{n}", compact=True)
        yield Input(value=self.START, placeholder=self.START, id=f"{sid}-input")
        with VerticalScroll(classes="cmd-scroll"):
            yield Static("Press Enter to run.", id=f"{sid}-output", markup=True)

    @on(Button.Pressed)
    def _preset(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if "-preset-" in bid:
            cmd = self.PRESETS[int(bid.rsplit("-", 1)[1])][1]
            self.query_one(f"#{self.section.id}-input", Input).value = cmd
            self.run_command(cmd)

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        self.run_command(event.value)

    def run_command(self, text: str) -> None:
        self.query_one(f"#{self.section.id}-output", Static).update("…")
        self._run(text)

    @work(thread=True, exclusive=True, group="cmdpane")
    def _run(self, text: str) -> None:
        try:
            args = shlex.split(text)
        except ValueError as err:
            self.app.call_from_thread(self._show, text, 1, f"error: {err}")
            return
        if args and args[0] == "langsuite":
            args = args[1:]
        code, out = run_plain(args)
        self.app.call_from_thread(self._show, text, code, out)

    def _show(self, text: str, code: int, out: str) -> None:
        self.last_code = code
        box = self.query_one(f"#{self.section.id}-output", Static)
        box.update(f"[b]$ langsuite {escape(text)}[/b]\n\n{escape(out)}")
        box.set_class(code != 0, "-error")


class DashboardPane(CommandPane):
    TITLE = "Dashboard"
    START = "dashboard --top 60 --bootstrap 30"
    PRESETS = (
        ("Top 60", "dashboard --top 60 --bootstrap 30"),
        (
            "ML vs Lisp",
            "dashboard --langs haskell,ml,ocaml,standard-ml,scheme,racket,clojure --k 2",
        ),
        ("Influence: Lisp", "influence lisp --depth 1"),
    )


class AnalysePane(CommandPane):
    TITLE = "Analyse"
    START = "rank --top 10"
    PRESETS = (
        ("Rank", "rank --top 10"),
        ("Functional, B+", 'rank --filter "grade>=B paradigm=functional"'),
        ("Compare", "compare haskell ocaml"),
        ("Diff", "diff fizzbuzz --lang python,ruby"),
        ("Like", "like fizzbuzz --as haskell --in python"),
    )


class DocsPane(CommandPane):
    TITLE = "Docs and inclusion"
    START = 'docs search "list comprehension"'
    PRESETS = (
        ("Search", 'docs search "list comprehension"'),
        ("Quote", "docs quote python"),
        ("Inclusion", "inclusion haskell"),
        ("Archived", "inclusion list --status archived"),
    )


class AccountCommands(CommandPane):
    TITLE = "Account"
    START = "account"
    PRESETS = (
        ("Account", "account"),
        ("Badges", "badges"),
        ("Streak", "streak"),
        ("Settings", "settings"),
        ("Link code", "account link"),
    )
