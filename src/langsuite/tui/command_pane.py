"""Dashboard and Analyse panes (M5b, M5c): run the CLI command in-process, show its output.

The output is the CLI's own plain rendering, so the pane and the CLI never disagree.
"""

from __future__ import annotations

import contextlib
import io
import os
import shlex

from rich.markup import escape
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Static

from langsuite.tui.sections import Section


def run_plain(args: list[str], width: int = 100) -> tuple[int, str]:
    from langsuite.cli.app import main

    out = io.StringIO()
    saved = {k: os.environ.get(k) for k in ("COLUMNS", "NO_COLOR")}
    os.environ.update(COLUMNS=str(width), NO_COLOR="1")
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                main(["--plain", *args])
            except SystemExit as stop:
                code = stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return code, out.getvalue().rstrip()


class CommandPane(Vertical):
    TITLE = ""
    PRESETS: tuple[tuple[str, str], ...] = ()
    START = ""

    def __init__(self, section: Section) -> None:
        super().__init__(id=f"pane-{section.id}", classes="pane cmdpane")
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
