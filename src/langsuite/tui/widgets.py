"""Header bar with handle, mode and base snapshot age."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class ModeChip(Static):
    """Shows the mode; click to cycle (same as F2)."""

    class Cycle(Message):
        pass

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(self.Cycle())


class HeaderBar(Horizontal):
    handle: reactive[str] = reactive("$langsuite/guest/default")
    mode: reactive[str] = reactive("default")
    base: reactive[str] = reactive("base: none")

    def compose(self) -> ComposeResult:
        yield Static(self.handle, id="handle", markup=False)
        yield ModeChip(f"mode: {self.mode}", id="mode", markup=False)
        yield Static(self.base, id="base", markup=False)

    def watch_handle(self, value: str) -> None:
        if self.is_mounted:
            self.query_one("#handle", Static).update(value)

    def watch_mode(self, value: str) -> None:
        if self.is_mounted:
            self.query_one("#mode", Static).update(f"mode: {value}")

    def watch_base(self, value: str) -> None:
        if self.is_mounted:
            self.query_one("#base", Static).update(value)
