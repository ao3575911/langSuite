"""Workspace pane: findings with verify, notes, saved queries, own data (SPEC §6e, M3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from rich.markup import escape
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Input, Static, TabbedContent, TabPane

from langsuite.cli.workspace_cmds import finding_markdown
from langsuite.core.errors import LangsuiteError
from langsuite.core.workspace import Finding, Workspace
from langsuite.tui.sections import Section


class WorkspacePane(Vertical):
    """Everything saved in the active workspace. `v` re-runs a finding bit-for-bit."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("v", "verify", "Verify"),
        Binding("r", "reload", "Reload"),
        Binding("delete", "remove", "Remove"),
    ]

    def __init__(self, section: Section, home: Path | None = None) -> None:
        super().__init__(id=f"pane-{section.id}", classes="pane workspacepane")
        self.section = section
        self.home = home
        self.findings: list[Finding] = []
        self.selected: Finding | None = None

    def compose(self) -> ComposeResult:
        yield Static("Loading workspace…", id="ws-status")
        with Horizontal(id="ws-body"):
            yield DataTable(id="ws-findings", cursor_type="row", zebra_stripes=True)
            with TabbedContent(id="ws-tabs"):
                with TabPane("Finding", id="tab-finding"):
                    yield VerticalScroll(Static(id="ws-detail", markup=False))
                with TabPane("Notes", id="tab-notes"):
                    yield Input(
                        placeholder="Add a note on this finding, Enter to save", id="ws-note"
                    )
                    yield VerticalScroll(Static(id="ws-notes"))
                with TabPane("Saved queries", id="tab-saved"):
                    yield DataTable(id="ws-queries", cursor_type="row")
                with TabPane("Own data", id="tab-own"):
                    yield VerticalScroll(Static(id="ws-own"))
        yield Static(
            "Ctrl+S in Explore or Query saves a finding · v verify · Del remove · "
            "Enter on a saved query runs it",
            id="ws-help",
            markup=False,
        )

    def on_mount(self) -> None:
        table = self.query_one("#ws-findings", DataTable)
        table.add_column("Id", width=4, key="id")
        table.add_column("Title", width=34, key="title")
        table.add_column("Kind", width=7, key="kind")
        queries = self.query_one("#ws-queries", DataTable)
        queries.add_column("Name", width=18, key="name")
        queries.add_column("Query", width=48, key="text")
        self.reload()

    def _ws(self) -> Workspace:
        return Workspace.open(self.home)

    def _status(self, text: str, error: bool = False) -> None:
        status = self.query_one("#ws-status", Static)
        status.update(text)
        status.set_class(error, "-error")

    def action_reload(self) -> None:
        self.reload()

    def reload(self, select: str | None = None) -> None:
        try:
            ws = self._ws()
            self.findings = ws.findings()
            notes = ws.notes()
            saved = ws.saved_queries()
            overlay = ws.overlay
            pinned = ws.pinned
        except LangsuiteError as err:
            self._status(escape(err.message), True)
            return
        table = self.query_one("#ws-findings", DataTable)
        table.clear()
        for f in self.findings:
            table.add_row(f.id, f.title[:34], f.kind, key=f.id)
        pin = f"pinned {pinned}" if pinned else "follows current base"
        self._status(
            f"Workspace [b]{escape(ws.slug)}[/] · {len(self.findings)} findings · "
            f"{len(notes)} notes · {len(saved)} saved queries · {pin}"
        )
        queries = self.query_one("#ws-queries", DataTable)
        queries.clear()
        for name, text in saved.items():
            queries.add_row(name, text[:48], key=name)
        own = self.query_one("#ws-own", Static)
        if overlay:
            lines = [f"{lang.name} ({lang.id})" for lang in overlay.languages]
            lines.append(f"{len(overlay.assertions)} own assertions, {len(overlay.edges)} edges")
            own.update(escape("\n".join(lines)))
        else:
            own.update("No own data. Add languages with `langsuite workspace import FILE`.")
        if not self.findings:
            self.selected = None
            self.query_one("#ws-detail", Static).update(
                "No findings yet.\nRun a query or open a language, then press Ctrl+S."
            )
            self._show_notes()
            return
        target = select or (self.selected.id if self.selected else None)
        index = next((i for i, f in enumerate(self.findings) if f.id == target), 0)
        table.move_cursor(row=index)
        self._show(self.findings[index])

    def _show(self, f: Finding, verdict: str = "") -> None:
        self.selected = f
        notes = [n.text for n in self._ws().notes(on=f.id)]
        self.query_one("#ws-detail", Static).update(finding_markdown(f, notes) + verdict)
        self._show_notes()

    def _show_notes(self) -> None:
        f = self.selected
        notes = self._ws().notes(on=f.id) if f else self._ws().notes()
        text = "\n".join(f"{n.id}  {n.text}" for n in notes) or "No notes yet."
        self.query_one("#ws-notes", Static).update(escape(text))

    @on(DataTable.RowHighlighted, "#ws-findings")
    def _highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = event.row_key.value
        found = next((f for f in self.findings if f.id == key), None)
        if found is not None and found is not self.selected:
            self._show(found)

    @on(Input.Submitted, "#ws-note")
    def _note(self, event: Input.Submitted) -> None:
        if not event.value.strip():
            return
        try:
            self._ws().add_note(event.value, on=self.selected.id if self.selected else None)
        except LangsuiteError as err:
            self.notify(err.message, severity="warning")
            return
        event.input.value = ""
        self.reload()

    @on(DataTable.RowSelected, "#ws-queries")
    def _run_saved(self, event: DataTable.RowSelected) -> None:
        name = str(event.row_key.value)
        text = self._ws().saved_queries().get(name, "")
        self.app.call_later(self._open_query, text)

    def _open_query(self, text: str) -> None:
        app: Any = self.app
        app.action_show("query")
        box = app.query_one("#query-input", Input)
        box.value = text
        box.focus()

    def action_verify(self) -> None:
        if self.selected is not None:
            self._status(f"Re-running {self.selected.id} on {self.selected.snapshot_id}…")
            self._verify(self.selected.id)

    @work(thread=True, exclusive=True, group="ws-verify")
    def _verify(self, fid: str) -> None:
        try:
            check = self._ws().verify(fid)
        except LangsuiteError as err:
            self.app.call_from_thread(self._status, escape(err.message), True)
            return
        verdict = (
            f"\n✓ Reproducible on {check.snapshot_id}: sha256 matches bit-for-bit."
            if check.ok
            else f"\n✗ Changed: expected {check.expected[:12]}, got {check.actual[:12]}."
        )
        self.app.call_from_thread(self._verified, check.finding, verdict, check.ok)

    def _verified(self, f: Finding, verdict: str, ok: bool) -> None:
        self._show(f, verdict)
        self._status(f"{f.id}: {'reproducible' if ok else 'CHANGED'}", not ok)

    def action_remove(self) -> None:
        if self.selected is None:
            return
        gone = self._ws().remove_finding(self.selected.id)
        self.selected = None
        self.notify(f"Removed {gone.id}", timeout=2)
        self.reload()


def save_finding_in_background(widget: Any, kind: str, args: dict[str, Any]) -> None:
    """Save a finding off the UI thread, then refresh the Workspace pane."""
    home = getattr(widget, "home", None)
    app = widget.app

    def job() -> None:
        try:
            f = Workspace.open(home).save_finding(kind, args)
        except LangsuiteError as err:
            app.call_from_thread(app.notify, err.message, severity="warning")
            return
        app.call_from_thread(_saved, app, f)

    widget.run_worker(job, thread=True, group="extract", exclusive=True)


def _saved(app: Any, f: Finding) -> None:
    app.notify(f"Saved {f.id}: {f.title}", timeout=3)
    for pane in app.query(WorkspacePane):
        pane.reload(select=f.id)
