"""Textual app shell (SPEC §6e, M0b): Pilot flows, bindings and snapshots."""

from __future__ import annotations

import time
from typing import Any

import pytest
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.widgets import ContentSwitcher, DataTable, Input, TabbedContent

from langsuite.cli.aliases import COMMANDS
from langsuite.tui.app import LangsuiteApp
from langsuite.tui.explore import ExplorePane
from langsuite.tui.leader import LeaderScreen
from langsuite.tui.query_pane import QueryPane
from langsuite.tui.sections import SECTIONS, section_for
from langsuite.tui.widgets import HeaderBar

THEMES = ["langsuite", "langsuite-high-contrast", "plain"]
SIZES = [(80, 24), (120, 40)]


def _current(app: LangsuiteApp) -> str | None:
    return app.query_one("#main", ContentSwitcher).current


async def test_header_shows_handle_and_mode() -> None:
    app = LangsuiteApp(mode="concise", handle="$langsuite/lazyfox/haskell-notes")
    async with app.run_test():
        header = app.query_one(HeaderBar)
        assert header.handle == "$langsuite/lazyfox/haskell-notes"
        assert header.mode == "concise"


async def test_pillar_keys_switch_panes() -> None:
    app = LangsuiteApp()
    async with app.run_test() as pilot:
        for s in SECTIONS:
            await pilot.press(s.key)
            assert _current(app) == f"pane-{s.id}"


@pytest.mark.parametrize("cmd", COMMANDS, ids=lambda c: c.name)
async def test_every_alias_runs_via_leader(cmd: Any) -> None:
    app = LangsuiteApp()
    async with app.run_test() as pilot:
        await pilot.press("g", *cmd.alias)
        if isinstance(app.screen, LeaderScreen):
            await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, LeaderScreen)
        target = section_for(cmd)
        if target:
            assert _current(app) == f"pane-{target}"
        if cmd.name == "mode":
            assert app.mode_name == "concise"


async def test_leader_unknown_escape_and_timeout() -> None:
    app = LangsuiteApp()
    async with app.run_test() as pilot:
        await pilot.press("g", "z")
        assert not isinstance(app.screen, LeaderScreen)
        await pilot.press("g", "escape")
        assert not isinstance(app.screen, LeaderScreen)
        await pilot.press("4", "g", "s")
        assert isinstance(app.screen, LeaderScreen)
        await pilot.pause(1.0)  # timeout fires exact alias `s` (similar)
        assert _current(app) == "pane-explore"


async def test_palette_runs_command() -> None:
    app = LangsuiteApp()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause(0.2)
        await pilot.press(*"rank")
        await pilot.pause(0.5)
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert _current(app) == "pane-analyse"


async def test_mode_cycle_key_and_click() -> None:
    app = LangsuiteApp()
    async with app.run_test() as pilot:
        await pilot.press("f2")
        assert app.query_one(HeaderBar).mode == "concise"
        await pilot.click("#mode")
        assert app.mode_name == "thorough"


async def test_theme_cycle_and_plain_toggle() -> None:
    app = LangsuiteApp()
    async with app.run_test() as pilot:
        await pilot.press("f3")
        assert app.theme == "langsuite-light"
        app.toggle_plain()
        assert app.has_class("-plain")
        app.toggle_plain()
        assert app.theme == "langsuite"


def test_bindings_do_not_collide_and_cover_aliases() -> None:
    keys = [b.key for b in LangsuiteApp.BINDINGS if isinstance(b, Binding)]
    assert len(keys) == len(set(keys))
    assert {s.key for s in SECTIONS} == {str(i) for i in range(1, 8)}
    assert all(section_for(c) in {s.id for s in SECTIONS} | {""} for c in COMMANDS)


async def test_startup_fast() -> None:
    t0 = time.perf_counter()
    app = LangsuiteApp()
    async with app.run_test(size=(80, 24)):
        elapsed = time.perf_counter() - t0
    assert elapsed < 1.5, elapsed  # spec target 600 ms interactive; CI headroom


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("section", SECTIONS, ids=lambda s: s.id)
def test_snapshot(snap_compare: Any, section: Any, theme: str, size: tuple[int, int]) -> None:
    app = LangsuiteApp(plain=theme == "plain")

    async def setup(pilot: Any) -> None:
        if theme != "plain":
            pilot.app.theme = theme
        await pilot.press(section.key)
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()

    assert snap_compare(app, terminal_size=size, run_before=setup)


# ----- Explore pane (M1) ---------------------------------------------------------


async def _explore_ready(pilot: Any) -> None:
    await pilot.press("2")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def test_explore_without_base_explains() -> None:
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await _explore_ready(pilot)
        status = str(app.query_one("#explore-status").render())
        assert "No knowledge base yet" in status
        assert "langsuite base build" in status


async def test_explore_live_search_and_detail(kb_home: Any) -> None:
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await _explore_ready(pilot)
        assert "base-" in str(app.query_one("#base").render())
        search = app.query_one("#explore-search")
        search.focus()
        await pilot.press(*"hask")
        await pilot.pause(0.3)
        table = app.query_one("#explore-table", DataTable)
        assert table.row_count >= 1
        assert table.coordinate_to_cell_key(Coordinate(0, 0)).row_key.value == "haskell"
        features = str(app.query_one("#detail-features").render())
        assert "Haskell" in features and "Type inference" in features
        assert "miranda" in str(app.query_one("#detail-lineage").render())
        assert "pldb.io/concepts/haskell" in str(app.query_one("#detail-evidence").render())
        await pilot.press("enter")
        assert app.focused is table
        await pilot.press("down")
        await pilot.pause()


async def test_explore_no_match(kb_home: Any) -> None:
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await _explore_ready(pilot)
        app.query_one("#explore-search").focus()
        await pilot.press(*"zzzz")
        await pilot.pause(0.3)
        assert "No match" in str(app.query_one("#explore-status").render())


async def test_leader_lang_focuses_search(kb_home: Any) -> None:
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("g", "l", "enter")
        await pilot.pause()
        assert app.focused is app.query_one("#explore-search")


@pytest.mark.parametrize("theme", ["langsuite", "langsuite-high-contrast"])
def test_explore_snapshot(snap_compare: Any, kb_home: Any, theme: str) -> None:
    app = LangsuiteApp()

    async def setup(pilot: Any) -> None:
        pilot.app.theme = theme
        await _explore_ready(pilot)
        search = pilot.app.query_one("#explore-search")
        search.cursor_blink = False  # blinking cursor makes frames non-deterministic
        search.focus()
        await pilot.press(*"haskell")
        # Wait out the debounce and any search/detail workers so slow CI
        # runners render the same settled frame as fast ones.
        for _ in range(3):
            await pilot.pause(0.3)
            await pilot.app.workers.wait_for_complete()
        await pilot.pause()

    assert snap_compare(app, terminal_size=(120, 40), run_before=setup)


# ----- Query pane and Similar tab (M2) -------------------------------------------


async def _query_ready(pilot: Any) -> None:
    await pilot.press("3")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def _type_query(pilot: Any, text: str) -> None:
    box = pilot.app.query_one("#query-input")
    box.cursor_blink = False
    box.focus()
    box.value = ""
    await pilot.press(*text)
    for _ in range(2):
        await pilot.pause(0.3)
        await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def test_query_pane_runs_dsl(kb_home: Any) -> None:
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await _query_ready(pilot)
        await _type_query(pilot, "homoiconicity sort=year")
        table = app.query_one("#query-table", DataTable)
        assert [table.get_cell_at(Coordinate(r, 0)) for r in range(table.row_count)] == [
            "lisp",
            "scheme",
            "racket",
        ]
        assert "3 matches" in str(app.query_one("#query-status").render())


async def test_query_pane_validates_as_you_type(kb_home: Any) -> None:
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await _query_ready(pilot)
        await _type_query(pilot, "(macros")
        status = str(app.query_one("#query-status").render())
        assert "Missing" in status and "column 1" in status
        assert app.query_one("#query-input").has_class("-invalid")
        await pilot.press(")")
        await pilot.pause(0.4)
        assert not app.query_one("#query-input").has_class("-invalid")


async def test_query_pane_planned_field_and_header_sort(kb_home: Any) -> None:
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await _query_ready(pilot)
        await _type_query(pilot, "score>=70")
        assert "M5c" in str(app.query_one("#query-status").render())
        await _type_query(pilot, "kind=pl")
        pane = app.query_one(QueryPane)
        table = app.query_one("#query-table", DataTable)
        table.post_message(
            DataTable.HeaderSelected(table, table.ordered_columns[3].key, 3, label=None)  # type: ignore[arg-type]
        )
        await pilot.pause(0.2)
        assert table.get_cell_at(Coordinate(0, 0)) == "lisp"
        table.post_message(
            DataTable.HeaderSelected(table, table.ordered_columns[3].key, 3, label=None)  # type: ignore[arg-type]
        )
        await pilot.pause(0.2)
        assert pane.result is not None and pane.result.descending


async def test_query_pane_without_base_explains() -> None:
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await _query_ready(pilot)
        assert "base build" in str(app.query_one("#query-status").render())


async def test_leader_q_focuses_query_and_s_opens_similar(kb_home: Any) -> None:
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("g", "q")
        await pilot.pause()
        assert app.focused is app.query_one("#query-input")
        app.set_focus(None)
        await pilot.press("g", "s", "enter")
        await pilot.pause()
        assert app.query_one("#explore-tabs", TabbedContent).active == "tab-similar"


async def test_similar_tab_lists_racket_for_scheme(kb_home: Any) -> None:
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await _explore_ready(pilot)
        app.query_one("#explore-search").focus()
        await pilot.press(*"scheme")
        await pilot.pause(0.4)
        text = str(app.query_one("#detail-similar").render())
        assert "Most like Scheme" in text and "Racket" in text and "z " in text


@pytest.mark.parametrize("theme", ["langsuite", "langsuite-high-contrast"])
def test_query_snapshot(snap_compare: Any, kb_home: Any, theme: str) -> None:
    app = LangsuiteApp()

    async def setup(pilot: Any) -> None:
        pilot.app.theme = theme
        await _query_ready(pilot)
        await _type_query(pilot, "kind=pl sort=year")

    assert snap_compare(app, terminal_size=(120, 40), run_before=setup)


def test_similar_tab_snapshot(snap_compare: Any, kb_home: Any) -> None:
    app = LangsuiteApp()

    async def setup(pilot: Any) -> None:
        await _explore_ready(pilot)
        search = pilot.app.query_one("#explore-search")
        search.cursor_blink = False
        search.focus()
        await pilot.press(*"scheme")
        for _ in range(2):
            await pilot.pause(0.3)
            await pilot.app.workers.wait_for_complete()
        pilot.app.query_one("#explore-tabs").active = "tab-similar"
        await pilot.pause(0.2)

    assert snap_compare(app, terminal_size=(120, 40), run_before=setup)


# ----- M3 Workspace pane ---------------------------------------------------------------


async def _settle(pilot: Any) -> None:
    for _ in range(3):
        await pilot.pause(0.3)
        await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def test_extract_from_explore_and_query(kb_home: Any) -> None:
    from langsuite.core.workspace import Workspace

    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await _explore_ready(pilot)
        search = app.query_one("#explore-search")
        search.focus()
        await pilot.press(*"scheme")
        await _settle(pilot)
        await pilot.press("ctrl+s")
        await _settle(pilot)
        app.query_one("#explore-tabs", TabbedContent).active = "tab-similar"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await _settle(pilot)
        await _query_ready(pilot)
        await _type_query(pilot, "homoiconicity")
        await pilot.press("ctrl+s")
        await _settle(pilot)
        found = Workspace.open().findings()
        assert [f.kind for f in found] == ["lang", "similar", "query"]
        assert found[0].args == {"lang": "scheme"}
        await pilot.press("ctrl+s")  # nothing typed problem-free: saves again
        await _settle(pilot)
        app.set_focus(None)
        await pilot.press("5")
        await pilot.pause()
        table = app.query_one("#ws-findings", DataTable)
        assert table.row_count == 4
        status = str(app.query_one("#ws-status").render())
        assert "4 findings" in status


async def test_extract_needs_something(kb_home: Any) -> None:
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("3")
        pane = app.query_one(QueryPane)
        pane.result = None
        pane.action_extract()
        await pilot.press("2")
        explore = app.query_one(ExplorePane)
        explore._shown = None
        explore.action_extract()
        await pilot.pause()
        from langsuite.core.workspace import Workspace

        assert Workspace.open().findings() == []


async def test_workspace_pane_verify_notes_and_saved_query(kb_home: Any) -> None:
    from langsuite.core.workspace import Workspace

    ws = Workspace.open()
    ws.save_finding("lang", {"lang": "haskell"})
    ws.save_finding("similar", {"lang": "scheme", "k": 3, "min_traits": 5, "baseline": True})
    ws.save_query("lisps", "homoiconicity")
    ws.import_data({"languages": [{"id": "quill", "name": "Quill", "traits": {"macros": "yes"}}]})
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("g", "w")
        await pilot.pause(0.6)
        assert app.query_one("#main", ContentSwitcher).current == "pane-workspace"
        table = app.query_one("#ws-findings", DataTable)
        assert table.row_count == 2
        assert "Haskell profile" in str(app.query_one("#ws-detail").render())
        table.focus()
        await pilot.press("down")
        await pilot.pause()
        assert "Most like Scheme" in str(app.query_one("#ws-detail").render())
        await pilot.press("v")
        await _settle(pilot)
        assert "Reproducible on base-" in str(app.query_one("#ws-detail").render())
        assert "Quill" in str(app.query_one("#ws-own").render())
        tabs = app.query_one("#ws-tabs", TabbedContent)
        tabs.active = "tab-notes"
        await pilot.pause()
        note = app.query_one("#ws-note")
        note.focus()
        await pilot.press(*"check hygiene", "enter")
        await pilot.pause()
        assert [n.on for n in ws.notes()] == ["f2"]
        assert "check hygiene" in str(app.query_one("#ws-notes").render())
        await pilot.press("enter")  # empty: ignored
        tabs.active = "tab-saved"
        await pilot.pause()
        queries = app.query_one("#ws-queries", DataTable)
        queries.focus()
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert app.query_one("#main", ContentSwitcher).current == "pane-query"
        assert app.query_one("#query-input", Input).value == "homoiconicity"
        await pilot.press("5")
        table.focus()
        await pilot.press("delete")
        await pilot.pause()
        assert table.row_count == 1
        await pilot.press("r")
        await pilot.pause()


async def test_workspace_pane_reports_verify_failure(kb_home: Any) -> None:
    import json

    from langsuite.core.workspace import Workspace

    ws = Workspace.open()
    f = ws.save_finding("lang", {"lang": "c"})
    path = ws.path / "findings" / f"{f.id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["result_sha256"] = "0" * 64
    path.write_text(json.dumps(raw), encoding="utf-8")
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("5")
        app.query_one("#ws-findings").focus()
        await pilot.press("v")
        await _settle(pilot)
        assert "Changed" in str(app.query_one("#ws-detail").render())
        assert "CHANGED" in str(app.query_one("#ws-status").render())


async def test_workspace_pane_damaged_workspace(kb_home: Any) -> None:
    from langsuite.core.workspace import Workspace

    ws = Workspace.open()
    (ws.path / "queries.json").write_text("{", encoding="utf-8")
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("5")
        await pilot.pause()
        assert "unreadable" in str(app.query_one("#ws-status").render())


@pytest.mark.parametrize("theme", ["langsuite", "langsuite-high-contrast"])
def test_workspace_snapshot(
    snap_compare: Any, kb_home: Any, theme: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from langsuite.core import workspace as wsmod

    monkeypatch.setattr(wsmod, "_now", lambda: "2026-10-30T04:00:00Z")
    ws = wsmod.Workspace.open()
    ws.save_finding("query", {"text": "homoiconicity sort=year", "top": None}, title="Lisps")
    ws.save_finding("similar", {"lang": "scheme", "k": 3, "min_traits": 5, "baseline": True})
    ws.add_note("Racket keeps Scheme's macros", on="f2")
    ws.save_query("lisps", "homoiconicity sort=year")
    app = LangsuiteApp()

    async def setup(pilot: Any) -> None:
        pilot.app.theme = theme
        await pilot.press("5")
        pilot.app.query_one("#ws-findings").focus()
        await pilot.press("down")
        await _settle(pilot)

    assert snap_compare(app, terminal_size=(120, 40), run_before=setup)


def _fake_result(lang: str, ok: bool) -> Any:
    from langsuite.verify.sandbox import Status, VerifyResult

    status = Status.PASS if ok else Status.FAIL
    return VerifyResult(
        status,
        lang,
        "fake",
        "img",
        "sha256:0",
        "0" * 64,
        0,
        "Hello world!\n",
        "",
        5,
        True,
        reason="output matches" if ok else "output differs",
    )


async def test_write_pane_snippet_and_verify(kb_home: Any, monkeypatch: Any) -> None:
    from langsuite.tui import write_pane
    from langsuite.verify import evidence

    def fake_check(task: Any, lang: str, **_: Any) -> Any:
        ok = lang == "python"
        return evidence.SolutionCheck(task, lang, 0 if ok else None, 1, _fake_result(lang, ok))

    monkeypatch.setattr(write_pane, "docker_available", lambda: True)
    monkeypatch.setattr(evidence, "check_solution", fake_check)
    monkeypatch.setattr(
        write_pane, "_default_runner", lambda lang, code, exp: _fake_result(lang, True)
    )
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("6")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        pane = app.query_one(write_pane.WritePane)
        assert "tasks · Docker sandbox ready" in str(app.query_one("#write-status").render())
        pane.show_snippets("fizzbuzz", "python,haskell")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        assert "1 of 2 verified" in str(app.query_one("#write-status").render())
        assert pane.current == ("FizzBuzz", "python")
        pane.action_run_code()
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        status = str(app.query_one("#verify-status").render())
        assert "verified" in status.lower() or "✓" in status
        assert pane.last_run is not None and pane.last_run[0] == "python"


async def test_write_pane_without_docker(kb_home: Any, monkeypatch: Any) -> None:
    from langsuite.tui import write_pane

    monkeypatch.setattr(write_pane, "docker_available", lambda: False)
    app = LangsuiteApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("6")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        assert "snippets unverified" in str(app.query_one("#write-status").render())
        pane = app.query_one(write_pane.WritePane)
        pane.show_snippets("fizzbuzz", "python")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        assert "0 of 1 verified" in str(app.query_one("#write-status").render())
        pane.action_run_code()
        await pilot.pause()
        assert "Docker is not available" in str(app.query_one("#verify-status").render())
        pane.show_snippets("no such task zz", "python")
        await pilot.pause()
        assert app.query_one("#write-status").has_class("-error")
