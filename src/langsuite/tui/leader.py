"""Leader-key overlay: `g` then a CLI alias runs that command (SPEC §6e)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.events import Key
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Static

from langsuite.tui.sections import ALIAS_INDEX, leader_candidates

LEADER_TIMEOUT = 0.8


class LeaderScreen(ModalScreen[str | None]):
    """Collects alias keys; resolves on unique match, enter, or timeout on an exact alias."""

    DEFAULT_CSS = """
    LeaderScreen { align: center bottom; background: $background 0%; }
    #leader-bar { width: 100%; height: 3; padding: 0 1; background: $panel;
                  border-top: solid $secondary; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.buffer = ""
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static(self._text(), id="leader-bar", markup=False)

    def _text(self) -> str:
        opts = "  ".join(f"{c.alias}={c.name}" for c in leader_candidates(self.buffer))
        return f"g {self.buffer}_   {opts}"[:400]

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def finish(self) -> None:
        self._stop_timer()
        self.dismiss(self.buffer or None)

    def feed(self, char: str) -> None:
        self._stop_timer()
        self.buffer += char.lower()
        cands = leader_candidates(self.buffer)
        if not cands or (len(cands) == 1 and cands[0].alias == self.buffer):
            self.finish()
            return
        self.query_one("#leader-bar", Static).update(self._text())
        if self.buffer in ALIAS_INDEX:
            self._timer = self.set_timer(LEADER_TIMEOUT, self.finish)

    def on_key(self, event: Key) -> None:
        event.stop()
        event.prevent_default()
        if event.key in ("escape", "ctrl+c"):
            self._stop_timer()
            self.dismiss(None)
        elif event.key == "enter":
            self.finish()
        elif event.character and event.character.isalpha():
            self.feed(event.character)
