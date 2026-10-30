"""python-telegram-bot 22.8 adapter: polling, commands menu, admin lookup (SPEC §6a).

The token comes only from `LANGSUITE_TELEGRAM_TOKEN` and is never printed or logged.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from langsuite.bot.core import BOT_COMMANDS, BOT_ONLY, Bot, Chat, Reply
from langsuite.core.errors import AuthError

TOKEN_ENV = "LANGSUITE_TELEGRAM_TOKEN"  # noqa: S105 - the variable name, not a token


def token_from_env() -> str:
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise AuthError(
            f"No Telegram bot token: set {TOKEN_ENV}.",
            hint="Get one from @BotFather; keep it in your environment or a secret file.",
        )
    return token


def token_status() -> str:
    """'set' or 'not set'; never the token."""
    return "set" if os.environ.get(TOKEN_ENV, "").strip() else "not set"


class _Redact(logging.Filter):
    """Belt and braces: strip the token from any log line (it appears in API URLs)."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self.token = token

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if self.token and self.token in msg:
            record.msg, record.args = msg.replace(self.token, "<token>"), None
        return True


def menu() -> list[tuple[str, str]]:
    items = [(c.name, c.help[:60]) for c in BOT_COMMANDS]
    items += [(k, v[:60]) for k, v in BOT_ONLY.items()]
    return items


async def _is_admin(bot: Any, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:  # a failed lookup means "not admin", never a crash
        return False
    return str(getattr(member, "status", "")) in ("administrator", "creator")


async def chat_from_update(update: Any, bot: Any) -> Chat | None:
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if msg is None or user is None or chat is None or not msg.text:
        return None
    group = chat.type in ("group", "supergroup")
    reply_to = None
    if msg.reply_to_message is not None and msg.reply_to_message.from_user is not None:
        target = msg.reply_to_message.from_user
        reply_to = (target.id, target.full_name)
    admin = await _is_admin(bot, chat.id, user.id) if group else False
    return Chat(chat.id, user.id, user.full_name, group, admin, reply_to)


async def send_reply(msg: Any, reply: Reply) -> None:
    from telegram import InputFile
    from telegram.constants import ParseMode

    await msg.reply_text(reply.text, parse_mode=ParseMode.MARKDOWN_V2)
    if reply.document is not None:
        name, data = reply.document
        await msg.reply_document(InputFile(data, filename=name))


def make_handler(core: Bot) -> Any:
    async def on_command(update: Any, context: Any) -> None:
        chat = await chat_from_update(update, context.bot)
        if chat is None:
            return
        reply = await asyncio.to_thread(core.handle, update.effective_message.text, chat)
        if reply is not None:
            await send_reply(update.effective_message, reply)

    return on_command


def build_application(token: str, core: Bot | None = None) -> Any:
    """The PTB Application; building it makes no network calls."""
    from telegram import BotCommand as TgCommand
    from telegram.ext import Application, MessageHandler, filters

    async def post_init(app: Any) -> None:
        await app.bot.set_my_commands([TgCommand(n, h) for n, h in menu()])

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx").addFilter(_Redact(token))
    app = Application.builder().token(token).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.COMMAND, make_handler(core or Bot())))
    return app


def run_polling(token: str) -> None:  # pragma: no cover - needs a live token
    build_application(token).run_polling(allowed_updates=["message"])
