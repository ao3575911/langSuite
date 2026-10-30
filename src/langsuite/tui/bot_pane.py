"""Account section, M5e part: the Telegram bot's status and a local chat simulator.

Handles, badges and usage arrive with M5g/M5i; this pane is honest about that.
"""

from __future__ import annotations

from rich.markup import escape
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Checkbox, DataTable, Input, Static

from langsuite.bot import telegram as tg
from langsuite.bot.core import BOT_COMMANDS, BOT_ONLY, Bot, Chat, Reply
from langsuite.tui.sections import Section


class BotPane(Vertical):
    """Try any bot command here; replies are exactly what Telegram would show."""

    def __init__(self, section: Section, bot: Bot | None = None) -> None:
        super().__init__(id=f"pane-{section.id}", classes="pane botpane")
        self.section = section
        self.bot = bot or Bot()
        self.last: Reply | None = None

    def compose(self) -> ComposeResult:
        yield Static("Telegram bot", classes="pane-title")
        yield Static(
            f"{tg.TOKEN_ENV}: {tg.token_status()} · run with `langsuite bot run` · "
            "handles, badges and usage: planned (M5g, M5i)",
            id="bot-status",
            markup=False,
        )
        with Horizontal(id="bot-body"):
            yield DataTable(id="bot-commands", cursor_type="row", zebra_stripes=True)
            with Vertical(id="bot-chat"):
                with Horizontal(id="bot-inputs"):
                    yield Input(placeholder="/s scheme --k 3", id="bot-input")
                    yield Checkbox("group, as viewer", id="bot-group")
                with VerticalScroll(id="bot-replies"):
                    yield Static("Type a bot command and press Enter.", id="bot-output")

    def on_mount(self) -> None:
        table = self.query_one("#bot-commands", DataTable)
        table.add_column("Command", key="cmd")
        table.add_column("Alias", key="alias")
        for c in BOT_COMMANDS:
            table.add_row(f"/{c.name}", f"/{c.alias}", key=c.name)
        for k in BOT_ONLY:
            table.add_row(f"/{k}", "", key=k)

    @on(DataTable.RowSelected, "#bot-commands")
    def _picked(self, event: DataTable.RowSelected) -> None:
        box = self.query_one("#bot-input", Input)
        box.value = f"/{event.row_key.value} "
        box.focus()

    @on(Input.Submitted, "#bot-input")
    def _submitted(self, event: Input.Submitted) -> None:
        self.send(event.value)

    def send(self, text: str) -> None:
        group = self.query_one("#bot-group", Checkbox).value
        chat = Chat(-1 if group else 1, 1, "you", group)
        self.query_one("#bot-output", Static).update("…")
        self._answer(text.strip(), chat)

    @work(thread=True, exclusive=True, group="bot-send")
    def _answer(self, text: str, chat: Chat) -> None:
        reply = self.bot.handle(text, chat)
        self.app.call_from_thread(self._show, text, reply)

    def _show(self, text: str, reply: Reply | None) -> None:
        self.last = reply
        out = self.query_one("#bot-output", Static)
        if reply is None:
            out.update("Not a command: the bot only answers /commands (privacy mode).")
            return
        extra = escape(f"\n[file: {reply.document[0]}]") if reply.document else ""
        out.update(f"[b]> {escape(text)}[/b]\n\n{escape(reply.plain)}{extra}")
        out.set_class(not reply.ok, "-error")
