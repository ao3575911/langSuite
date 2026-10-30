"""`langsuite bot`: run the Telegram bot, or try a command locally (SPEC §6a, M5e)."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from langsuite.bot import telegram as tg
from langsuite.bot.core import BOT_COMMANDS, BOT_ONLY, Bot, Chat, ChatState, Role, save_state
from langsuite.cli.kb_cmds import _console, _emit, _json

bot_app = typer.Typer(help="Telegram bot.", no_args_is_help=True)


@bot_app.command("run")
def bot_run(ctx: typer.Context) -> None:
    """Run the bot with long polling. Token from LANGSUITE_TELEGRAM_TOKEN.

    Example: LANGSUITE_TELEGRAM_TOKEN=... langsuite bot run
    """
    token = tg.token_from_env()
    _console(ctx).print("[lw.muted]Polling Telegram; Ctrl+C stops.[/]")
    tg.run_polling(token)  # pragma: no cover - needs a live token


@bot_app.command("try")
def bot_try(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help="A bot message, e.g. '/q macros top=3'.")],
    group: Annotated[bool, typer.Option("--group", help="As a group chat.")] = False,
    role: Annotated[Role | None, typer.Option("--role", help="Your role in the group.")] = None,
    user: Annotated[int, typer.Option("--user", help="Telegram user id.")] = 1,
    chat: Annotated[int, typer.Option("--chat", help="Telegram chat id.")] = -1,
    markdown: Annotated[bool, typer.Option("--markdown", help="Show raw MarkdownV2.")] = False,
) -> None:
    """Answer a bot message locally, exactly as the bot would; no token needed.

    Example: langsuite bot try "/s scheme --k 3" --group --role viewer
    """
    chat_id = chat if group else user
    if group and role is not None:
        save_state(chat_id, ChatState({str(user): role.value}))
    reply = Bot().handle(text.replace("\\n", "\n"), Chat(chat_id, user, "you", group))
    if reply is None:
        raise typer.Exit(0)
    if _json(ctx):
        doc = reply.document[0] if reply.document else None
        _emit("bot-reply", {"text": reply.text, "plain": reply.plain, "document": doc})
        return
    _console(ctx).print(escape(reply.text if markdown else reply.plain))
    if not reply.ok:
        raise typer.Exit(1)


@bot_app.command("commands")
def bot_commands(ctx: typer.Context) -> None:
    """Bot commands, their CLI equivalents and who may use them."""
    rows = [
        {"command": f"/{c.name}", "alias": f"/{c.alias}", "help": c.help,
         "write": sorted(k for k, r in c.subs.items() if r is Role.CONTRIBUTOR),
         "code": c.needs_code}
        for c in BOT_COMMANDS
    ]  # fmt: skip
    rows += [{"command": f"/{k}", "alias": "", "help": v, "write": [], "code": False}
             for k, v in BOT_ONLY.items()]  # fmt: skip
    if _json(ctx):
        _emit("bot-commands", {"commands": rows, "token": tg.token_status()})
        return
    con = _console(ctx)
    table = Table(box=None, header_style="lw.title", pad_edge=False)
    for col in ("command", "alias", "what"):
        table.add_column(col)
    for r in rows:
        table.add_row(str(r["command"]), str(r["alias"]), escape(str(r["help"])))
    con.print(table)
    con.print(f"[lw.muted]{tg.TOKEN_ENV}: {tg.token_status()}[/]")
