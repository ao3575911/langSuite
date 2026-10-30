"""Account section (M5g): account, badges, streak and settings, plus the Telegram bot tab."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import TabbedContent, TabPane

from langsuite.tui.bot_pane import BotPane
from langsuite.tui.command_pane import AccountCommands
from langsuite.tui.sections import Section


class AccountPane(Vertical):
    def __init__(self, section: Section) -> None:
        super().__init__(id=f"pane-{section.id}", classes="pane")
        self.section = section

    def compose(self) -> ComposeResult:
        with TabbedContent(id="account-tabs"):
            with TabPane("Account", id="tab-account"):
                yield AccountCommands(self.section, pane_id="account-cmds")
            with TabPane("Telegram bot", id="tab-bot"):
                yield BotPane(self.section, pane_id="bot-pane")
