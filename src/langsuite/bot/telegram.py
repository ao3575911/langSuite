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

DESCRIPTION = (
    "langsuite: a research knowledge base of programming languages, with evidence. "
    "Query 5,000+ languages, compare features, find similar languages, read verified "
    "Rosetta Code snippets, and save findings to your own workspace. Tap Start to pick "
    "a handle; add me to a group and an admin runs /start to set the group up."
)
SHORT_DESCRIPTION = "Programming languages, with evidence: query, compare, cite."
log = logging.getLogger("langsuite.bot")
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


async def chat_from_update(update: Any, bot: Any, text: str = "") -> Chat | None:
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if msg is None or user is None or chat is None:
        return None
    if not msg.text and not text:
        return None
    group = chat.type in ("group", "supergroup")
    reply_to = None
    if msg.reply_to_message is not None and msg.reply_to_message.from_user is not None:
        target = msg.reply_to_message.from_user
        reply_to = (target.id, target.full_name)
    admin = await _is_admin(bot, chat.id, user.id) if group else False
    username = getattr(user, "username", None) or ""
    title = getattr(chat, "title", None) or ""
    return Chat(chat.id, user.id, user.full_name, group, admin, reply_to, username, title)


async def send_reply(msg: Any, reply: Reply) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile
    from telegram.constants import ParseMode

    markup = None
    if reply.buttons:
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(label, callback_data=cmd[:64])] for label, cmd in reply.buttons]
        )
    await msg.reply_text(reply.text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=markup)
    if reply.document is not None:
        name, data = reply.document
        await msg.reply_document(InputFile(data, filename=name))


def make_handler(core: Bot) -> Any:
    async def on_command(update: Any, context: Any) -> None:
        chat = await chat_from_update(update, context.bot)
        if chat is None:
            return
        text = update.effective_message.text
        log.info("chat %s user %s: %s", chat.chat_id, chat.user_id, text.split(None, 1)[0][:32])
        reply = await asyncio.to_thread(core.handle, text, chat)
        if reply is not None:
            await send_reply(update.effective_message, reply)

    return on_command


def make_button_handler(core: Bot) -> Any:
    """A tapped suggestion button runs its command as the person who tapped it."""

    async def on_button(update: Any, context: Any) -> None:
        query = update.callback_query
        if query is None or not query.data:
            return
        await query.answer()
        chat = await chat_from_update(update, context.bot, text=query.data)
        if chat is None or query.message is None:
            return
        reply = await asyncio.to_thread(core.handle, query.data, chat)
        if reply is not None:
            await send_reply(query.message, reply)

    return on_button


def make_inline_handler(core: Bot) -> Any:
    """Inline mode: `@langsuite_bot similar haskell` in any chat (enable with /setinline)."""

    async def on_inline(update: Any, context: Any) -> None:
        from telegram import InlineQueryResultArticle, InputTextMessageContent

        query = update.inline_query
        if query is None:
            return
        cards = await asyncio.to_thread(core.inline, query.query, query.from_user.id)
        results = [
            InlineQueryResultArticle(
                id=str(n),
                title=title,
                description=body.splitlines()[0][:100] if body else "",
                input_message_content=InputTextMessageContent(f"{title}\n\n{body}"[:4000]),
            )
            for n, (title, body) in enumerate(cards)
        ]
        await query.answer(results, cache_time=60, is_personal=True)

    return on_inline


async def digest_job(context: Any) -> None:  # pragma: no cover - needs a live bot
    """JobQueue callback: send digests whose time has come (runs once a minute)."""
    from datetime import UTC, datetime

    core: Bot = context.job.data
    try:
        for chat_id, reply in await asyncio.to_thread(core.due_digests, datetime.now(UTC)):
            await context.bot.send_message(chat_id, reply.plain[:4000])
    except Exception:
        log.exception("digest run failed")


def build_application(token: str, core: Bot | None = None) -> Any:
    """The PTB Application; building it makes no network calls."""
    from telegram import BotCommand as TgCommand
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        InlineQueryHandler,
        MessageHandler,
        filters,
    )

    async def post_init(app: Any) -> None:
        await app.bot.set_my_commands([TgCommand(n, h) for n, h in menu()])
        await app.bot.set_my_description(DESCRIPTION)
        await app.bot.set_my_short_description(SHORT_DESCRIPTION)
        me = await app.bot.get_me()
        logging.getLogger("langsuite.bot").warning("langsuite bot started as @%s", me.username)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)  # one line a minute otherwise
    logging.getLogger("httpx").addFilter(_Redact(token))
    core_ = core or Bot()
    app = Application.builder().token(token).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.COMMAND, make_handler(core_)))
    app.add_handler(CallbackQueryHandler(make_button_handler(core_)))
    app.add_handler(InlineQueryHandler(make_inline_handler(core_)))
    assert app.job_queue is not None  # the [job-queue] extra is a dependency
    app.job_queue.run_repeating(digest_job, interval=60, first=15, data=core_, name="digests")
    return app


def run_polling(token: str) -> None:  # pragma: no cover - needs a live token
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        level=logging.INFO)  # fmt: skip
    logging.getLogger().addFilter(_Redact(token))
    build_application(token).run_polling(
        allowed_updates=["message", "callback_query", "inline_query"]
    )
