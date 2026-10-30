"""Textual app shell (SPEC §6e, M0b): Pilot flows, bindings and snapshots."""

from __future__ import annotations

import time
from typing import Any

import pytest
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.widgets import ContentSwitcher, DataTable

from langsuite.cli.aliases import COMMANDS
from langsuite.tui.app import LangsuiteApp
from langsuite.tui.leader import LeaderScreen
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
