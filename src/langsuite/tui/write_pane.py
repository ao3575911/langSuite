"""Write pane: verified Rosetta snippets and a code verifier (SPEC §6e, M4)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from rich.console import Group, RenderableType
from rich.markup import escape
from rich.syntax import Syntax
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from langsuite.core.errors import LangsuiteError
from langsuite.core.workspace import open_kb
from langsuite.tui.sections import Section
from langsuite.verify import evidence as vev
from langsuite.verify import rosetta
from langsuite.verify.sandbox import Status, VerifyResult, docker_available, run_code
from langsuite.verify.toolchains import BY_LANG, toolchain_for

Checker = Callable[[rosetta.Task, str], vev.SolutionCheck]
Runner = Callable[[str, str, str | None], VerifyResult]
_MARK = {
    Status.PASS: ("✓ verified", "green"),
    Status.FAIL: ("✗ fail", "red"),
    Status.TIMEOUT: ("✗ timeout", "yellow"),
    Status.MEMORY: ("✗ memory cap", "yellow"),
    Status.REFUSED: ("✗ refused", "red"),
    Status.ERROR: ("✗ error", "red"),
}


def _badge(res: VerifyResult) -> Text:
    label, colour = _MARK[res.status]
    return Text(label, style=f"bold {colour}")


def _default_runner(lang: str, code: str, expected: str | None) -> VerifyResult:
    return run_code(toolchain_for(lang), code, expected=expected)


class WritePane(Vertical):
    """`langsuite snippet` and `langsuite verify` in one pane."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "extract", "Save finding"),
        Binding("ctrl+r", "run_code", "Verify code", show=False),
    ]

    def __init__(
        self,
        section: Section,
        home: Path | None = None,
        checker: Checker | None = None,
        runner: Runner | None = None,
        docker: bool | None = None,
    ) -> None:
        super().__init__(id=f"pane-{section.id}", classes="pane writepane")
        self.section = section
        self.home = home
        self.tasks: dict[str, rosetta.Task] = {}
        self.checker = checker
        self.runner = runner or _default_runner
        self.docker = docker
        self.current: tuple[str, str] | None = None  # (task title, lang) for extract
        self.last_run: tuple[str, str, str | None] | None = None

    def compose(self) -> ComposeResult:
        with TabbedContent(id="write-tabs", initial="tab-snippet"):
            with TabPane("Snippet", id="tab-snippet"):
                with Horizontal(id="write-inputs"):
                    yield Input(placeholder="Task, e.g. fizzbuzz", id="write-task")
                    yield Input(placeholder="Languages, e.g. python,rust", id="write-langs")
                yield Static("Loading Rosetta pack…", id="write-status")
                with Horizontal(id="write-body"):
                    yield DataTable(id="write-tasks", cursor_type="row", zebra_stripes=True)
                    with VerticalScroll(id="write-results"):
                        yield Static("", id="write-output")
            with TabPane("Verify", id="tab-verify"):
                with Horizontal(id="verify-inputs"):
                    yield Input(placeholder="Language, e.g. python", id="verify-lang")
                    yield Input(placeholder="Expected output (optional)", id="verify-expect")
                    yield Button("Verify", id="verify-run", variant="primary")
                yield TextArea('print("Hello world!")\n', id="verify-code", show_line_numbers=True)
                yield Static("Ctrl+R runs the code in the sandbox.", id="verify-status")
        yield Static(
            "Enter runs · Ctrl+S saves a finding · Rosetta Code, attributed per task",
            id="write-help",
        )

    def on_mount(self) -> None:
        table = self.query_one("#write-tasks", DataTable)
        table.add_column("Task", width=24, key="task")
        table.add_column("Langs", width=5, key="n")
        self._load()

    @work(thread=True, exclusive=True, group="write-load")
    def _load(self) -> None:
        try:
            tasks = rosetta.load_tasks(self.home)
        except LangsuiteError as err:
            self.app.call_from_thread(self._status, err.message, True)
            return
        docker = self.docker if self.docker is not None else docker_available()
        self.app.call_from_thread(self._ready, tasks, docker)

    def _ready(self, tasks: dict[str, rosetta.Task], docker: bool) -> None:
        self.tasks = tasks
        self.docker = docker
        table = self.query_one("#write-tasks", DataTable)
        table.clear()
        for slug, t in sorted(tasks.items()):
            table.add_row(t.title[:24], str(len(t.solutions)), key=slug)
        sandbox = "Docker sandbox ready" if docker else "Docker not available: snippets unverified"
        if not tasks:
            self._status("No Rosetta pack. Run `langsuite snippet --fetch`.", True)
            return
        self._status(f"{len(tasks)} tasks · {sandbox}. Pick a task, add languages, Enter.")

    def _status(self, text: str, error: bool = False, target: str = "#write-status") -> None:
        status = self.query_one(target, Static)
        status.update(text)
        status.set_class(error, "-error")

    @on(DataTable.RowSelected, "#write-tasks")
    def _picked(self, event: DataTable.RowSelected) -> None:
        slug = str(event.row_key.value)
        self.query_one("#write-task", Input).value = self.tasks[slug].title
        self.query_one("#write-langs", Input).focus()

    @on(Input.Submitted, "#write-task")
    @on(Input.Submitted, "#write-langs")
    def _submitted(self, _event: Input.Submitted) -> None:
        self.show_snippets(
            self.query_one("#write-task", Input).value,
            self.query_one("#write-langs", Input).value,
        )

    def show_snippets(self, task_q: str, langs_raw: str) -> None:
        try:
            task = rosetta.find_task(self.tasks, task_q)
        except LangsuiteError as err:
            self._status(escape(err.message + (f" {err.hint}" if err.hint else "")), True)
            return
        langs = [x.strip() for x in langs_raw.split(",") if x.strip()] or ["python"]
        self._status(f"Verifying {task.title} in {', '.join(langs)}…")
        self._run_snippets(task, langs)

    @work(thread=True, exclusive=True, group="write-run")
    def _run_snippets(self, task: rosetta.Task, raw_langs: list[str]) -> None:
        parts: list[RenderableType] = []
        first: tuple[str, str] | None = None
        verified = 0
        with open_kb(self.home) as kb:
            ids = []
            for raw in raw_langs:
                try:
                    ids.append(kb.resolve(raw).id)
                except LangsuiteError:
                    parts.append(Text(f"Unknown language `{raw}`.", style="yellow"))
        for lid in ids:
            sol = task.solutions.get(lid)
            if sol is None:
                parts.append(Text(f"No {lid} solution for “{task.title}”.", style="yellow"))
                continue
            first = first or (task.title, lid)
            check: vev.SolutionCheck | None = None
            if lid in BY_LANG and self.docker:
                checker = self.checker or (lambda t, x: vev.check_solution(t, x, home=self.home))
                check = checker(task, lid)
            head = Text.assemble((f"{task.title} · ", "bold"), (lid, "bold magenta"), " ")
            if check:
                head.append_text(_badge(check.result))
                verified += int(check.verified)
            elif lid not in BY_LANG:
                head.append("unverified · no toolchain", style="dim")
            else:
                head.append("unverified · Docker not available", style="yellow")
            code = check.code if check else sol.code
            parts += [
                head,
                Syntax(code.rstrip("\n"), lid, theme="ansi_dark", word_wrap=True),
                Text(task.attribution, style="italic cyan"),
                Text(""),
            ]
        self.current = first
        n = len([x for x in ids if x in task.solutions])
        summary = f"{task.title}: {verified} of {n} verified · Ctrl+S saves the first as a finding"
        self.app.call_from_thread(self._show, Group(*parts), summary)

    def _show(self, body: RenderableType, summary: str) -> None:
        self.query_one("#write-output", Static).update(body)
        self._status(summary)

    # ----- verify tab -------------------------------------------------------------
    @on(Button.Pressed, "#verify-run")
    def _pressed(self) -> None:
        self.action_run_code()

    def action_run_code(self) -> None:
        self.query_one("#write-tabs", TabbedContent).active = "tab-verify"
        raw = self.query_one("#verify-lang", Input).value.strip() or "python"
        code = self.query_one("#verify-code", TextArea).text
        expect = self.query_one("#verify-expect", Input).value or None
        if not self.docker:
            self._status("Docker is not available; cannot verify.", True, "#verify-status")
            return
        self._status(f"Running {raw} in the sandbox…", target="#verify-status")
        self._verify(raw, code, expect)

    @work(thread=True, exclusive=True, group="write-verify")
    def _verify(self, raw: str, code: str, expect: str | None) -> None:
        try:
            with open_kb(self.home) as kb:
                lid = kb.resolve(raw).id
            res = self.runner(lid, code, expect)
        except LangsuiteError as err:
            self.app.call_from_thread(self._status, escape(err.message), True, "#verify-status")
            return
        self.last_run = (lid, code, expect)
        out = res.stdout.rstrip("\n")[-800:]
        text = Text.assemble(_badge(res), f" {res.toolchain} · {res.reason} · {res.evidence_id}")
        if out:
            text.append("\n" + out, style="dim")
        self.app.call_from_thread(self._verified, text, res.ok)

    def _verified(self, text: Text, ok: bool) -> None:
        status = self.query_one("#verify-status", Static)
        status.update(text)
        status.set_class(not ok, "-error")

    def action_extract(self) -> None:
        from langsuite.tui.workspace_pane import save_finding_in_background

        tabs = self.query_one("#write-tabs", TabbedContent)
        if tabs.active == "tab-verify" and self.last_run:
            lid, code, expect = self.last_run
            from langsuite.verify.sandbox import code_hash

            args = {"lang": lid, "code": code, "code_sha256": code_hash(code), "expected": expect}
            save_finding_in_background(self, "verify", args)
            return
        if self.current is None:
            self.notify("Show a snippet first.", timeout=2)
            return
        task, lang = self.current
        save_finding_in_background(self, "snippet", {"task": task, "lang": lang})
