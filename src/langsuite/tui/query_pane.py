"""Query pane: DSL input validated as you type, sortable results (SPEC §6e, M2)."""

from __future__ import annotations

from pathlib import Path

from rich.markup import escape
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import DataTable, Input, Static

from langsuite.core.errors import LangsuiteError
from langsuite.core.kb import KnowledgeBase
from langsuite.core.query import QueryError, QueryResult, run
from langsuite.tui.sections import Section

DEBOUNCE_S = 0.15
ROW_LIMIT = 500
EXAMPLES = (
    "homoiconicity year<1990 sort=year",
    "(macros or pattern-matching) and static-typing top=20",
    "eval=lazy",
    "garbage-collection=no kind=pl sort=-year",
)
COLUMNS = (("id", 22), ("name", 26), ("kind", 10), ("year", 4), ("traits", 6))


class QueryPane(Vertical):
    """Filter languages with the same DSL as `langsuite query`."""

    def __init__(self, section: Section, home: Path | None = None) -> None:
        super().__init__(id=f"pane-{section.id}", classes="pane querypane")
        self.section = section
        self.home = home
        self.kb: KnowledgeBase | None = None
        self.result: QueryResult | None = None
        self._timer: Timer | None = None
        self._sort: tuple[str, bool] | None = None  # set by clicking a column header

    def compose(self) -> ComposeResult:
        yield Input(placeholder='Query, e.g. "homoiconicity year<1990 sort=year"', id="query-input")
        yield Static("Loading knowledge base…", id="query-status")
        yield DataTable(id="query-table", cursor_type="row", zebra_stripes=True)
        yield Static(
            "Examples: " + "  ·  ".join(EXAMPLES) + "\nClick a column to sort.",
            id="query-help",
            markup=False,
        )

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for name, width in COLUMNS:
            table.add_column(name.title(), width=width, key=name)
        self._load()

    @work(thread=True, exclusive=True, group="kb-query")
    def _load(self) -> None:
        try:
            kb = KnowledgeBase(self.home)
            _ = kb.languages
            kb.trait_matrix()
            kb.trait_values()
        except LangsuiteError as err:
            msg = err.message + (f"\n{err.hint}" if err.hint else "")
            self.app.call_from_thread(self._status, msg, True)
            return
        self.app.call_from_thread(self._ready, kb)

    def _ready(self, kb: KnowledgeBase) -> None:
        self.kb = kb
        self.execute(self.query_one(Input).value)

    def on_unmount(self) -> None:
        if self.kb is not None:
            self.kb.close()

    def _status(self, text: str, error: bool = False) -> None:
        status = self.query_one("#query-status", Static)
        status.update(text)
        status.set_class(error, "-error")

    @on(Input.Changed, "#query-input")
    def _changed(self, event: Input.Changed) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._sort = None
        self._timer = self.set_timer(DEBOUNCE_S, lambda: self.execute(event.value))

    @on(Input.Submitted, "#query-input")
    def _submitted(self, event: Input.Submitted) -> None:
        if self._timer is not None:
            self._timer.stop()
        self.execute(event.value)
        self.query_one(DataTable).focus()

    def _with_sort(self, text: str) -> str:
        if self._sort is None:
            return text
        field, desc = self._sort
        return f"{text} sort={'-' if desc else ''}{field}"

    def execute(self, text: str) -> None:
        if self.kb is None:
            return
        try:
            result = run(self.kb, self._with_sort(text))
        except QueryError as err:
            col = err.position
            self._status(
                f"✗ {escape(err.message)}  [dim](at column {col + 1})[/]"
                + (f"\n{escape(err.hint.splitlines()[0])}" if err.hint else ""),
                True,
            )
            self.query_one("#query-input").set_class(True, "-invalid")
            return
        except LangsuiteError as err:
            self._status(escape(err.message), True)
            self.query_one("#query-input").set_class(True, "-invalid")
            return
        self.query_one("#query-input").set_class(False, "-invalid")
        self.result = result
        table = self.query_one(DataTable)
        table.clear()
        for row in result.rows[:ROW_LIMIT]:
            lang = row.language
            table.add_row(
                lang.id[:22],
                lang.name[:26],
                lang.kind[:10],
                str(lang.appeared) if lang.appeared is not None else "",
                str(row.traits),
                key=lang.id,
            )
        more = f", first {ROW_LIMIT} shown" if len(result.rows) > ROW_LIMIT else ""
        arrow = "↓" if result.descending else "↑"
        self._status(
            f"✓ {result.total} match{'es' if result.total != 1 else ''}{more} · "
            f"{escape(result.normalised)} · sort {result.sort} {arrow} · {result.snapshot_id}"
        )

    @on(DataTable.HeaderSelected, "#query-table")
    def _header(self, event: DataTable.HeaderSelected) -> None:
        field = str(event.column_key.value)
        if self._sort is not None and self._sort[0] == field:
            self._sort = (field, not self._sort[1])
        else:
            self._sort = (field, field == "traits")
        self.execute(self.query_one(Input).value)
