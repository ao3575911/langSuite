"""Telegram bot (SPEC §6a, §10 M5e): core logic, PTB adapter (mocked), CLI and pane."""

from __future__ import annotations

import asyncio
import io
import logging
import random
from contextlib import redirect_stdout
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from langsuite.bot import core
from langsuite.bot import telegram as tg
from langsuite.bot.core import Bot, Chat, RateLimiter, md_escape, md_pre
from langsuite.cli.aliases import COMMANDS
from langsuite.cli.app import app, main
from langsuite.cli.implemented import COMMAND_FUNCS, GROUP_APPS

ME = Chat(1, 42, "Ada")
ALICE = Chat(-100, 7, "Alice", group=True, telegram_admin=True)
BOB = Chat(-100, 8, "Bob", group=True)


def _bot(**kw: Any) -> Bot:
    return Bot(limiter=RateLimiter(1000, 1000), **kw)


class FakeRunner:
    def __init__(self, out: str = "ok") -> None:
        self.calls: list[tuple[list[str], str]] = []
        self.out = out

    def __call__(self, args: list[str], ws: str, author: Any) -> tuple[int, str]:
        self.calls.append((args, ws))
        return 0, self.out


# ----- parity and escaping -----------------------------------------------------------


def test_parity_every_built_command_reachable() -> None:
    built = (set(COMMAND_FUNCS) | set(GROUP_APPS)) - {"bot"}
    covered = {c.name for c in core.BOT_COMMANDS} | set(core.NOT_IN_BOT)
    assert built <= covered, built - covered
    aliases = {c.name: c.alias for c in COMMANDS}
    for c in core.BOT_COMMANDS:
        assert aliases[c.name] == c.alias  # same shorthands as the CLI (SPEC §7)


def _valid_md2(text: str) -> bool:
    """Every reserved character outside code blocks is escaped."""
    i, in_pre = 0, False
    while i < len(text):
        if text.startswith("```", i):
            in_pre, i = not in_pre, i + 3
            continue
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if in_pre and ch == "`":
            return False
        if not in_pre and ch in core._MD_SPECIAL:
            return False
        i += 1
    return not in_pre


def test_markdown_escaping_fuzz() -> None:
    rng = random.Random(7)  # noqa: S311 - seeded fuzz input, not crypto
    alphabet = "abc _*[]()~`>#+-=|{}.!\\\n😀é"
    for _ in range(500):
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        assert _valid_md2(md_escape(s)), s
        assert _valid_md2(md_pre(s)), s
        reply = core._reply(s, header=s)
        assert _valid_md2(reply.text), s


def test_parse_strips_bot_name_and_keeps_code() -> None:
    assert core.parse("/Q@langsuite_bot a 'b c'\nprint(1)") == ("q", ["a", "b c"], "print(1)")
    assert _bot().handle("hello", ME) is None  # privacy mode: commands only
    assert "could not read" in _bot().handle('/q "unclosed', ME).plain  # type: ignore[union-attr]
    assert "unknown command" in _bot().handle("/nope", ME).plain  # type: ignore[union-attr]
    assert "/similar (/s)" in _bot().handle("/help", ME).plain  # type: ignore[union-attr]


# ----- real CLI path -------------------------------------------------------------------


def test_query_matches_cli(kb_home: Any) -> None:
    reply = _bot().handle("/q kind=pl top=3", ME)
    assert reply is not None and reply.ok
    out = io.StringIO()
    with redirect_stdout(out), pytest.raises(SystemExit):
        main(["--plain", "q", "kind=pl top=3"])
    body = reply.plain.split("\n", 1)[1]
    assert body.split() == out.getvalue().split()  # same result, phone-width wrapping aside
    assert reply.text.startswith("tg\\-u42") and "```" in reply.text


def test_workspaces_roles_and_authors(kb_home: Any) -> None:
    bot = _bot()
    assert bot.handle("/q kind=pl top=2", BOB).ok  # type: ignore[union-attr]
    denied = bot.handle("/x Group pick", BOB)
    assert denied is not None and denied.plain.startswith("Not allowed")
    assert bot.handle("/role contributor", BOB).plain.startswith("Not allowed")  # type: ignore[union-attr]
    promote = Chat(-100, 7, "Alice", group=True, telegram_admin=True, reply_to=(8, "Bob"))
    assert bot.handle("/role contributor", promote).plain == "Bob is now contributor."  # type: ignore[union-attr]
    assert "Your role: contributor" in bot.handle("/role", BOB).plain  # type: ignore[union-attr]
    saved = bot.handle("/x Group pick", BOB)
    assert saved is not None and "Saved f1" in saved.plain
    shown = bot.handle("/f show f1", ALICE)
    assert shown is not None and "author: Bob (telegram)" in shown.plain
    mine = bot.handle("/f ls", ME)
    assert mine is not None and "Group pick" not in mine.plain  # personal workspace is separate
    assert bot.handle("/role 8 viewer", ALICE).plain == "8 is now viewer."  # type: ignore[union-attr]
    assert bot.handle("/role 8 boss", ALICE).plain.startswith("error")  # type: ignore[union-attr]
    assert bot.handle("/role x", ALICE).plain.startswith("error")  # type: ignore[union-attr]
    assert "private chat" in bot.handle("/role", ME).plain  # type: ignore[union-attr]
    assert bot.handle("/n add check it", BOB).plain.startswith("Not allowed")  # type: ignore[union-attr]
    assert "Added n1" in bot.handle("/n add check it", ME).plain  # type: ignore[union-attr]
    q = bot.handle("/q kind=pl --save mine", BOB)
    assert q is not None and q.plain.startswith("Not allowed")


def test_blocked_options_and_subcommands() -> None:
    bot = _bot(runner=FakeRunner())
    assert "not available" in bot.handle("/f export -o /etc/x", ME).plain  # type: ignore[union-attr]
    assert "not available" in bot.handle("/sn --fetch", ME).plain  # type: ignore[union-attr]
    assert "not available" in bot.handle("/b status --debug", ME).plain  # type: ignore[union-attr]
    bot.handle("/b pin", ME)  # pin is not offered: it goes to `base status`, which rejects it
    assert bot.runner.calls[-1][0][:2] == ["base", "status"]  # type: ignore[attr-defined]


def test_user_code_refused_until_admin_enables(tmp_path: Any) -> None:
    runner = FakeRunner("✓ verified")
    bot = _bot(runner=runner, home=tmp_path)
    off = bot.handle("/v python\nprint(1)", ME)
    assert off is not None and "not run" in off.plain and not runner.calls
    assert bot.handle("/settings coderuns on", BOB).plain.startswith("Not allowed")  # type: ignore[union-attr]
    on = bot.handle("/settings coderuns on", ALICE)
    assert on is not None and "code runs: on" in on.plain
    assert "error" in bot.handle("/v python", ALICE).plain  # type: ignore[union-attr]
    ran = bot.handle("/v python --expect 1\nprint(1)", BOB)
    assert ran is not None and "✓ verified" in ran.plain
    args, ws = runner.calls[-1]
    assert args[0] == "verify" and args[2:] == ["--lang", "python", "--expect", "1"]
    assert ws == "tg-g100" and not list((tmp_path / "bot" / "code").iterdir())
    bot.handle("/sn fizzbuzz --lang python", ME)
    assert runner.calls[-1][0][-1] == "--no-verify"  # private chat has code runs off
    assert "Code runs are off" in bot.handle("/sn fizzbuzz --verify", ME).plain  # type: ignore[union-attr]
    assert "try /settings" in bot.handle("/settings nope", ME).plain  # type: ignore[union-attr]


def test_rate_limit_is_polite_and_refills() -> None:
    now = [0.0]
    bot = Bot(runner=FakeRunner(), limiter=RateLimiter(2, 3, clock=lambda: now[0]))
    assert bot.handle("/b", ME).ok and bot.handle("/b", ME).ok  # type: ignore[union-attr]
    slow = bot.handle("/b", ME)
    assert slow is not None and slow.plain.startswith("Sorry") and not slow.ok
    now[0] += 30  # one token back per 30 s at 2/min
    assert bot.handle("/b", ME).ok  # type: ignore[union-attr]
    for uid in (1, 2, 3):
        assert bot.handle("/b", Chat(-5, uid, "x", group=True)).ok  # type: ignore[union-attr]
    assert not bot.handle("/b", Chat(-5, 4, "x", group=True)).ok  # type: ignore[union-attr]


def test_long_output_becomes_a_file() -> None:
    reply = _bot(runner=FakeRunner("x" * 5000)).handle("/b", ME)
    assert reply is not None and reply.document is not None
    assert reply.document[0] == "langsuite.txt" and len(reply.document[1]) > 5000
    assert "```" not in reply.text


# ----- Telegram adapter (mocked; no token, no network) --------------------------------


def test_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from langsuite.core.errors import AuthError

    with pytest.raises(AuthError):
        tg.token_from_env()
    assert tg.token_status() == "not set"
    monkeypatch.setenv(tg.TOKEN_ENV, "123:abc")
    assert tg.token_from_env() == "123:abc" and tg.token_status() == "set"


def test_build_application_offline() -> None:
    from telegram.ext import Application

    application = tg.build_application("123456:TEST-not-a-real-token", _bot(runner=FakeRunner()))
    assert isinstance(application, Application)
    assert len(application.handlers[0]) == 3  # commands, buttons, inline queries
    assert application.job_queue is not None
    assert [j.name for j in application.job_queue.jobs()] == ["digests"]
    names = [n for n, _ in tg.menu()]
    assert "similar" in names and "role" in names and all(len(h) <= 60 for _, h in tg.menu())


def test_redact_filter() -> None:
    record = logging.LogRecord("httpx", 20, "", 0, "GET https://x/bot%s/getMe", ("SECRET",), None)
    tg._Redact("SECRET").filter(record)
    assert "SECRET" not in record.getMessage() and "<token>" in record.getMessage()


class FakeMessage:
    def __init__(self, text: str, reply_from: Any = None) -> None:
        self.text = text
        self.reply_to_message = SimpleNamespace(from_user=reply_from) if reply_from else None
        self.sent: list[tuple[str, Any]] = []

    async def reply_text(self, text: str, parse_mode: Any = None, reply_markup: Any = None) -> None:
        self.sent.append(("text", (text, parse_mode)))
        self.markup = reply_markup

    async def reply_document(self, doc: Any) -> None:
        self.sent.append(("doc", doc))


class FakeTgBot:
    def __init__(self, status: str) -> None:
        self.status = status

    async def get_chat_member(self, chat_id: int, user_id: int) -> Any:
        if self.status == "boom":
            raise RuntimeError("network")
        return SimpleNamespace(status=self.status)


def _update(text: str, chat_type: str = "private", reply_from: Any = None) -> Any:
    return SimpleNamespace(
        effective_message=FakeMessage(text, reply_from),
        effective_user=SimpleNamespace(id=42, full_name="Ada"),
        effective_chat=SimpleNamespace(id=-100 if chat_type != "private" else 42, type=chat_type),
    )


def test_handler_replies_in_markdown_v2() -> None:
    runner = FakeRunner("x" * 5000)
    handler = tg.make_handler(_bot(runner=runner))
    upd = _update("/b status")
    asyncio.run(handler(upd, SimpleNamespace(bot=FakeTgBot("member"))))
    kinds = [k for k, _ in upd.effective_message.sent]
    assert kinds == ["text", "doc"]
    assert str(upd.effective_message.sent[0][1][1]) == "MarkdownV2"
    quiet = _update("hello")
    asyncio.run(handler(quiet, SimpleNamespace(bot=FakeTgBot("member"))))
    assert quiet.effective_message.sent == []


def test_chat_from_update_admin_and_reply() -> None:
    target = SimpleNamespace(id=8, full_name="Bob")
    chat = asyncio.run(tg.chat_from_update(_update("/role contributor", "supergroup", target),
                                           FakeTgBot("creator")))  # fmt: skip
    assert chat is not None and chat.group and chat.telegram_admin and chat.reply_to == (8, "Bob")
    member = asyncio.run(tg.chat_from_update(_update("/b", "group"), FakeTgBot("member")))
    assert member is not None and not member.telegram_admin
    failed = asyncio.run(tg.chat_from_update(_update("/b", "group"), FakeTgBot("boom")))
    assert failed is not None and not failed.telegram_admin
    empty = _update("/b")
    empty.effective_message.text = ""
    assert asyncio.run(tg.chat_from_update(empty, FakeTgBot("member"))) is None


# ----- CLI -------------------------------------------------------------------------------


def test_cli_bot_try_commands_and_run(kb_home: Any) -> None:
    r = CliRunner().invoke(app, ["--plain", "bot", "try", "/q kind=pl top=2"])
    assert r.exit_code == 0 and "tg-u1 · /q" in r.output
    r = CliRunner().invoke(app, ["--plain", "bt", "try", "/x hi", "--group", "--role", "viewer"])
    assert r.exit_code == 1 and "Not allowed" in r.output
    r = CliRunner().invoke(app, ["--plain", "bt", "try", "hello"])
    assert r.exit_code == 0 and r.output == ""
    r = CliRunner().invoke(app, ["--json", "bt", "try", "/help", "--markdown"])
    assert '"kind": "bot-reply"' in r.output
    r = CliRunner().invoke(app, ["--plain", "bt", "try", "/help", "--markdown"])
    assert "\\(/s\\)" in r.output
    r = CliRunner().invoke(app, ["--plain", "bt", "commands"])
    assert "/similar" in r.output and "LANGSUITE_TELEGRAM_TOKEN: not set" in r.output
    r = CliRunner().invoke(app, ["--json", "bt", "commands"])
    assert '"token": "not set"' in r.output


def test_cli_bot_run_needs_token(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["--plain", "bot", "run"])
    assert stop.value.code == 4
    assert "LANGSUITE_TELEGRAM_TOKEN" in capsys.readouterr().err


# ----- app pane ----------------------------------------------------------------------------


async def test_bot_pane_simulator(kb_home: Any) -> None:
    from textual.widgets import Checkbox, Input

    from langsuite.tui.app import LangsuiteApp
    from langsuite.tui.bot_pane import BotPane

    app_ = LangsuiteApp()
    async with app_.run_test(size=(120, 40)) as pilot:
        await pilot.press("7")
        await pilot.pause()
        pane = app_.query_one(BotPane)
        assert "not set" in str(app_.query_one("#bot-status").render())
        pane.send("/q kind=pl top=2")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        assert "tg-u1" in str(app_.query_one("#bot-output").render())
        app_.query_one("#bot-group", Checkbox).value = True
        pane.send("/x mine")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        assert app_.query_one("#bot-output").has_class("-error")
        pane.send("hello")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        assert "privacy mode" in str(app_.query_one("#bot-output").render())
        app_.query_one("#bot-commands").focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app_.query_one("#bot-input", Input).value == "/lang "


# ----- onboarding ------------------------------------------------------------------------


def test_onboarding_private_handle_and_workspace(kb_home: Any) -> None:
    from langsuite.bot.onboarding import Registry, skeleton

    bot = _bot()
    ada = Chat(1, 42, "Ada Lovelace", username="ada_l")
    start = bot.handle("/start", ada)
    assert start is not None and len(start.buttons) == 3
    assert start.buttons[0] == ("ada_l", "/handle ada_l")
    assert bot.handle("/space", ada).plain.startswith("Pick a handle first")  # type: ignore[union-attr]
    for bad, why in [("ab", "3-20"), ("admin", "reserved"), ("l4ngsuite", "reserved"),
                     ("langsuíte", "look-alike")]:  # fmt: skip
        assert why in bot.handle(f"/handle {bad}", ada).plain  # type: ignore[union-attr]
    claimed = bot.handle("/handle ada_l", ada)
    assert claimed is not None and claimed.buttons[0] == ("main", "/space main")
    other = Chat(2, 43, "Eve", username="ADA_L")
    assert "taken" in bot.handle("/handle Ada_1", other).plain  # type: ignore[union-attr]
    assert "ada_l" not in [p for p, _ in bot.handle("/start", other).buttons]  # type: ignore[union-attr]
    made = bot.handle("/space research", ada)
    assert made is not None and "Created and switched to $langsuite/ada_l/research" in made.plain
    q = bot.handle("/q kind=pl top=1", ada)
    assert q is not None and q.plain.startswith("$langsuite/ada_l/research")
    assert bot.workspace(ada) == "tg-u42-research"
    assert "Switched to $langsuite/ada_l/main" in bot.handle("/space main", ada).plain  # type: ignore[union-attr]
    assert "Welcome back" in bot.handle("/start", ada).plain  # type: ignore[union-attr]
    renamed = bot.handle("/handle lovelace", ada)
    assert renamed is not None and "changed from ada_l to lovelace" in renamed.plain
    assert "not a valid" in bot.handle("/space Bad_Name", ada).plain  # type: ignore[union-attr]
    assert skeleton("L0vel4ce") == skeleton("lovelace")
    assert Registry(kb_home / "nope.json").get("u1").display is None


def test_onboarding_group_needs_admin(kb_home: Any) -> None:
    bot = _bot()
    alice = Chat(-100, 7, "Alice", group=True, telegram_admin=True, title="PL Reading Group")
    bob = Chat(-100, 8, "Bob", group=True, title="PL Reading Group")
    assert "admin can run /start" in bot.handle("/start", bob).plain  # type: ignore[union-attr]
    assert bot.handle("/handle bobs", bob).plain.startswith("Not allowed")  # type: ignore[union-attr]
    start = bot.handle("/start", alice)
    assert start is not None and start.buttons[0][0] == "pl_reading_group"
    bot.handle("/handle pl_reading_group", alice)
    done = bot.handle("/space main", alice)
    assert done is not None and "$langsuite/pl_reading_group/main" in done.plain
    assert "Welcome back" in bot.handle("/start", bob).plain  # type: ignore[union-attr]
    assert bot.handle("/space x", bob).plain.startswith("Not allowed")  # type: ignore[union-attr]
    assert "$langsuite/pl_reading_group/main" in bot.handle("/settings", bob).plain  # type: ignore[union-attr]


def test_button_tap_runs_command_as_tapper() -> None:
    runner = FakeRunner()
    handler = tg.make_button_handler(_bot(runner=runner))
    msg = FakeMessage("Pick a handle")
    answered: list[bool] = []

    async def answer() -> None:
        answered.append(True)

    upd = SimpleNamespace(
        callback_query=SimpleNamespace(data="/handle ada_x", message=msg, answer=answer),
        effective_message=msg,
        effective_user=SimpleNamespace(id=42, full_name="Ada", username="ada"),
        effective_chat=SimpleNamespace(id=42, type="private", title=None),
    )
    asyncio.run(handler(upd, SimpleNamespace(bot=FakeTgBot("member"))))
    assert answered and "Handle ada_x is yours" in msg.sent[0][1][0].replace("\\", "")
    assert msg.markup is not None
    empty = SimpleNamespace(callback_query=None)
    asyncio.run(handler(empty, SimpleNamespace(bot=FakeTgBot("member"))))
