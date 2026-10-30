"""Explore pane: live language search with a tabbed, cited detail view (SPEC §6e, M1)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from rich.markup import escape
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import DataTable, Input, Static, TabbedContent, TabPane

from langsuite.core.errors import LangsuiteError
from langsuite.core.kb import KnowledgeBase, Language
from langsuite.tui.sections import Section

DEBOUNCE_S = 0.12
ROW_LIMIT = 200
PLANNED_TABS = (("Docs", "M5e"), ("Score", "M5c"), ("Snippets", "M4"))


class ExplorePane(Vertical):
    """Search on the left, details on the right. Loads the base in a worker thread."""

    def __init__(self, section: Section, home: Path | None = None) -> None:
        super().__init__(id=f"pane-{section.id}", classes="pane explore")
        self.section = section
        self.home = home
        self.kb: KnowledgeBase | None = None
        self._timer: Timer | None = None
        self._shown: str | None = None

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search languages: name, alias or .ext", id="explore-search")
        yield Static("Loading knowledge base…", id="explore-status")
        with Horizontal(id="explore-body"):
            yield DataTable(id="explore-table", cursor_type="row", zebra_stripes=True)
            with TabbedContent(id="explore-tabs"):
                with TabPane("Features", id="tab-features"):
                    yield VerticalScroll(Static(id="detail-features"))
                with TabPane("Lineage", id="tab-lineage"):
                    yield VerticalScroll(Static(id="detail-lineage"))
                with TabPane("Evidence", id="tab-evidence"):
                    yield VerticalScroll(Static(id="detail-evidence"))
                for name, milestone in PLANNED_TABS:
                    with TabPane(name, id=f"tab-{name.lower()}"):
                        yield Static(f"Planned for milestone {milestone}.", classes="pane-status")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Name", width=30, key="name")
        table.add_column("Kind", width=12, key="kind")
        table.add_column("Year", width=4, key="year")
        self._load()

    @work(thread=True, exclusive=True, group="kb")
    def _load(self) -> None:
        try:
            kb = KnowledgeBase(self.home)
            _ = kb.languages  # warm the cache off the UI thread
        except LangsuiteError as err:
            msg = err.message + (f"\n{err.hint}" if err.hint else "")
            self.app.call_from_thread(self._set_status, msg, True)
            return
        self.app.call_from_thread(self._ready, kb)

    def _set_status(self, text: str, error: bool = False) -> None:
        status = self.query_one("#explore-status", Static)
        status.update(text)
        status.set_class(error, "-error")

    def _ready(self, kb: KnowledgeBase) -> None:
        self.kb = kb
        self._refresh(self.query_one(Input).value)

    def on_unmount(self) -> None:
        if self.kb is not None:
            self.kb.close()

    @on(Input.Changed, "#explore-search")
    def _changed(self, event: Input.Changed) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(DEBOUNCE_S, lambda: self._refresh(event.value))

    @on(Input.Submitted, "#explore-search")
    def _submitted(self) -> None:
        self.query_one(DataTable).focus()

    def _refresh(self, query: str) -> None:
        if self.kb is None:
            return
        hits = self.kb.search(query, limit=None)
        table = self.query_one(DataTable)
        table.clear()
        for lang in hits[:ROW_LIMIT]:
            year = str(lang.appeared) if lang.appeared is not None else ""
            table.add_row(lang.name[:30], lang.kind[:12], year, key=lang.id)
        more = f" (first {ROW_LIMIT})" if len(hits) > ROW_LIMIT else ""
        total = len(self.kb.languages)
        self._set_status(
            f"{len(hits)} of {total} languages{more} · {self.kb.manifest.snapshot_id}"
            if hits
            else f"No match for “{query}”. Try fewer letters."
        )
        if hits:
            self.show_language(hits[0])

    @on(DataTable.RowHighlighted, "#explore-table")
    def _highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self.kb is None or event.row_key.value is None:
            return
        lang = self.kb.language(str(event.row_key.value))
        if lang is not None:
            self.show_language(lang)

    def show_language(self, lang: Language) -> None:
        if self.kb is None or self._shown == lang.id:
            return
        self._shown = lang.id
        kb = self.kb
        feats = {f.id: f for f in kb.features}
        rows = kb.assertions(lang.id)
        yes: dict[str, list[str]] = defaultdict(list)
        no: list[str] = []
        facts: dict[str, list[str]] = defaultdict(list)
        for a in rows:
            feat = feats.get(a.feature_id)
            if feat is None or feat.kind == "fact":
                if a.value not in facts[a.feature_id]:
                    facts[a.feature_id].append(a.value)
            elif a.value == "yes":
                yes[feat.category].append(feat.label)
            else:
                no.append(feat.label)
        head = [f"[b]{escape(lang.name)}[/b]  [dim]{escape(lang.id)} · {escape(lang.kind)}[/]"]
        for fid in ("appeared", "creators", "website", "extensions", "aliases"):
            if facts.get(fid):
                label = feats[fid].label if fid in feats else fid
                head.append(f"[dim]{label}:[/] {escape(' · '.join(facts[fid]))}")
        body = []
        for cat in sorted(yes):
            body.append(f"[b]{cat}[/b]: " + escape(", ".join(sorted(yes[cat]))))
        if no:
            body.append("[dim]Without: " + escape(", ".join(sorted(no))) + "[/]")
        if not yes and not no:
            body.append("[dim]No feature data in the sources yet.[/]")
        self.query_one("#detail-features", Static).update("\n".join([*head, "", *body]))

        parents, children = kb.edges(lang.id)
        lineage = [
            "[b]Influenced by[/b]: " + (escape(", ".join(e.src for e in parents)) or "—"),
            "[b]Influenced[/b]: " + (escape(", ".join(e.dst for e in children)) or "—"),
        ]
        if parents or children:
            lineage.append("\n[dim]Source: PLDB influencedBy[/]")
        self.query_one("#detail-lineage", Static).update("\n".join(lineage))

        refs: list[str] = []
        ev = []
        for a in rows:
            if a.source_url not in refs:
                refs.append(a.source_url)
            label = feats[a.feature_id].label if a.feature_id in feats else a.feature_id
            ev.append(
                f"{escape(label)}: {escape(a.value)} [dim]\\[{refs.index(a.source_url) + 1}] "
                f"{a.retrieved_at[:10]}[/]"
            )
        ev.append("")
        ev.extend(f"[dim]\\[{n}] {escape(u)}[/]" for n, u in enumerate(refs, 1))
        self.query_one("#detail-evidence", Static).update("\n".join(ev))
