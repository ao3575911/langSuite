"""Telegram bot logic, free of Telegram itself (SPEC §6a, §10 M5e).

`handle(text, chat)` turns one command message into a `Reply`. Every reply comes from
the same CLI code path (`--plain`), so `/q` gives exactly what `langsuite q` prints.
Each chat has its own workspace (`tg-u<id>` for a private chat, `tg-g<id>` for a group),
roles (admin, contributor, viewer) and settings; user code never runs unless an admin
turned code runs on for that chat.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import re
import shlex
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from langsuite.bot.onboarding import DEFAULT_WS, Registry, internal_workspace
from langsuite.core.paths import data_home

log = logging.getLogger("langsuite.bot")

MAX_MESSAGE = 3800  # Telegram allows 4096; leave room for the header and escapes
WIDTH = 64  # monospace columns that read well on a phone
USER_PER_MIN = 20
GROUP_PER_MIN = 60

# MarkdownV2 reserved characters (https://core.telegram.org/bots/api#markdownv2-style).
_MD_SPECIAL = set("_*[]()~`>#+-=|{}.!\\")


def md_escape(text: str) -> str:
    """Escape plain text for MarkdownV2."""
    return "".join("\\" + ch if ch in _MD_SPECIAL else ch for ch in text)


def md_pre(text: str) -> str:
    """A MarkdownV2 code block: inside `pre` only ` and \\ need escaping."""
    body = text.replace("\\", "\\\\").replace("`", "\\`")
    return f"```\n{body}\n```"


class Role(StrEnum):
    VIEWER = "viewer"
    CONTRIBUTOR = "contributor"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return [Role.VIEWER, Role.CONTRIBUTOR, Role.ADMIN].index(self)


@dataclass(frozen=True)
class Chat:
    """Who sent a command, and where."""

    chat_id: int
    user_id: int
    user_name: str
    group: bool = False
    telegram_admin: bool = False  # Telegram group admins are langsuite admins by default
    reply_to: tuple[int, str] | None = None  # (user id, name) of a replied-to message
    username: str = ""  # Telegram @username, used to suggest handles
    title: str = ""  # group title, used to suggest group handles

    @property
    def owner_key(self) -> str:
        return f"g{abs(self.chat_id)}" if self.group else f"u{self.user_id}"

    @property
    def workspace(self) -> str:
        return f"tg-g{abs(self.chat_id)}" if self.group else f"tg-u{self.user_id}"


@dataclass
class Reply:
    text: str  # MarkdownV2
    document: tuple[str, bytes] | None = None  # (filename, content) when too long
    plain: str = ""  # the same reply without markup, for logs, tests and the app
    failed: bool = False  # the command ran and exited non-zero
    buttons: list[tuple[str, str]] = field(default_factory=list)  # (label, command to run)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.plain.startswith(("error:", "Sorry", "Not allowed"))


# ----- command table ---------------------------------------------------------------


@dataclass(frozen=True)
class BotCommand:
    name: str  # CLI command it runs
    alias: str
    help: str
    # subcommand -> minimum role; "" is the bare command
    subs: dict[str, Role] = field(default_factory=dict)
    default_sub: str = ""
    needs_code: bool = False  # runs user code: refused unless an admin enabled code runs


READ = Role.VIEWER
WRITE = Role.CONTRIBUTOR

BOT_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand("lang", "l", "list or show languages: /l show haskell",
               {"list": READ, "show": READ, "ls": READ, "sh": READ}, "show"),
    BotCommand("feature", "ft", "list or show features: /ft show macros",
               {"list": READ, "show": READ, "ls": READ, "sh": READ}, "list"),
    BotCommand("query", "q", "filter languages: /q homoiconicity year<1990", {"": READ}),
    BotCommand("similar", "s", "most similar languages: /s scheme", {"": READ}),
    BotCommand("snippet", "sn", "Rosetta snippet: /sn fizzbuzz --lang python", {"": READ}),
    BotCommand("verify", "v", "run code: /v python, then the code on the next lines",
               {"": READ}, needs_code=True),
    BotCommand("finding", "f", "findings: /f ls, /f show f1, /f save similar scheme",
               {"list": READ, "ls": READ, "show": READ, "sh": READ, "export": READ,
                "verify": READ, "save": WRITE, "remove": WRITE, "rm": WRITE}, "list"),
    BotCommand("extract", "x", "save the last result as a finding: /x My title", {"": WRITE}),
    BotCommand("note", "n", "notes: /n add text, /n ls",
               {"list": READ, "ls": READ, "add": WRITE, "remove": WRITE, "rm": WRITE}, "list"),
    BotCommand("base", "b", "knowledge base: /b status",
               {"status": READ, "snapshots": READ, "changelog": READ}, "status"),
    BotCommand("docs", "dc", "quote official docs: /dc rust ownership, /dc quote python loops",
               {"search": READ, "quote": READ, "ingest": Role.ADMIN}, "search"),
    BotCommand("inclusion", "inc", "why a language is in, and its docs links: /inc rust",
               {"": READ, "check": Role.ADMIN}),
    BotCommand("ask", "a", "cited answer, or none: /a does haskell have type inference",
               {"": READ}),
    BotCommand("guide", "g", "start with a language: /g scheme", {"": READ}),
    BotCommand("badges", "bg", "badges earned in this chat's workspace", {"": READ}),
    BotCommand("streak", "st", "days in a row this workspace was used", {"": READ}),
    BotCommand("cluster", "c", "language families: /c --langs scheme,racket,ml --k 2",
               {"": READ}),
    BotCommand("dashboard", "db", "clusters, labels and evidence: /db --top 60",
               {"": READ, "rename": WRITE}, ""),
    BotCommand("influence", "i", "influence graph: /i lisp -d 1", {"": READ}),
    BotCommand("rank", "r", "scores and grades: /r --filter grade>=B", {"": READ}),
    BotCommand("compare", "cp", "two languages side by side: /cp haskell ocaml",
               {"": READ}),
    BotCommand("diff", "df", "one task across languages: /df fizzbuzz --lang python,ruby",
               {"": READ}),
    BotCommand("like", "lk", "do X the Y way: /lk fizzbuzz --as haskell --in python",
               {"": READ}),
)  # fmt: skip
BY_NAME: dict[str, BotCommand] = {}
for _c in BOT_COMMANDS:
    BY_NAME[_c.name] = BY_NAME[_c.alias] = _c

# Built CLI commands the bot does not offer, and why (checked by the parity test).
NOT_IN_BOT: dict[str, str] = {
    "ui": "the app needs a terminal or browser",
    "workspace": "each chat has exactly one workspace; /settings shows it",
    "mode": "each chat keeps its own: /mode concise",
    "mcp": "an MCP server talks stdio to local agents, not to chats",
    "webhook": "the signing secret would show in the chat; set up with the CLI",
    "account": "use /handle, /link and /private here",
    "login": "device sign-in happens on the machine running the CLI",
    "logout": "the token lives on the CLI machine; chats never hold it",
    "usage": "plan usage is per CLI install; run `langsuite usage`",
    "settings": "here /settings is per chat; the CLI one sets this machine's preferences",
}
BOT_ONLY = {
    "start": "set up: pick a handle and a workspace",
    "handle": "claim or change your handle: /handle ada_l",
    "space": "create or switch workspace: /space notes",
    "help": "commands",
    "link": "link this chat to your CLI account: /link CODE (from `langsuite account link`)",
    "private": "hide your handle from non-members: /private on",
    "role": "admins: reply to someone with /role contributor",
    "settings": "chat settings: /settings coderuns on|off (admins)",
    "mode": "reply length: /mode concise|default|thorough",
    "digest": "scheduled results: /digest weekly mon 09:00 macros top=5",
}

# Options that would touch files, the network or the debug path; never from a chat.
_BLOCKED = ("-o", "--out", "--output", "--from", "--fetch", "--debug", "--home", "--saved-file")
_BLOCKED_SNIPPET_NOCODE = ("--verify",)


# ----- per-chat state ----------------------------------------------------------------


def bot_dir(home: Path | None = None) -> Path:
    return (home or data_home()) / "bot"


@dataclass
class ChatState:
    roles: dict[str, str] = field(default_factory=dict)
    code_runs: bool = False
    mode: str | None = None
    digest: dict[str, Any] | None = None


def _state_path(chat_id: int, home: Path | None) -> Path:
    return bot_dir(home) / "chats" / f"{chat_id}.json"


def load_state(chat_id: int, home: Path | None = None) -> ChatState:
    path = _state_path(chat_id, home)
    if not path.is_file():
        return ChatState()
    data = json.loads(path.read_text(encoding="utf-8"))
    return ChatState(
        dict(data.get("roles", {})),
        bool(data.get("code_runs", False)),
        data.get("mode"),
        data.get("digest"),
    )


def save_state(chat_id: int, state: ChatState, home: Path | None = None) -> None:
    path = _state_path(chat_id, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{uuid.uuid4().hex}.tmp")
    data = {"roles": state.roles, "code_runs": state.code_runs, "mode": state.mode,
            "digest": state.digest}  # fmt: skip
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DIGEST_TZ = "Australia/Perth"


def parse_digest(args: list[str], tz: str = DIGEST_TZ) -> dict[str, Any]:
    """`daily 09:00 <query>` or `weekly mon 09:00 <query>`."""
    if not args or args[0] not in ("daily", "weekly"):
        raise ValueError("start with daily or weekly, e.g. /digest weekly mon 09:00 macros")
    every, rest = args[0], args[1:]
    day = None
    if every == "weekly":
        if not rest or rest[0][:3].lower() not in DAYS:
            raise ValueError("weekly needs a day: mon, tue, wed, thu, fri, sat or sun")
        day, rest = rest[0][:3].lower(), rest[1:]
    if not rest or not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", rest[0]):
        raise ValueError("give a time as HH:MM, e.g. 09:00")
    hhmm, query = rest[0], " ".join(rest[1:]).strip()
    if not query:
        raise ValueError("add the query to run, e.g. macros top=5")
    out: dict[str, Any] = {"every": every, "time": hhmm.zfill(5), "tz": tz, "query": query}
    if day:
        out["day"] = day
    return out


def last_slot(d: dict[str, Any], now: datetime) -> datetime:
    """The most recent scheduled time at or before `now`, in the digest's timezone."""
    local = now.astimezone(ZoneInfo(d.get("tz", DIGEST_TZ)))
    hh, mm = (int(x) for x in d["time"].split(":"))
    slot = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if d["every"] == "weekly":
        slot -= timedelta(days=(local.weekday() - DAYS.index(d["day"])) % 7)
    while slot > local:
        slot -= timedelta(days=7 if d["every"] == "weekly" else 1)
    return slot


def role_of(chat: Chat, state: ChatState) -> Role:
    if not chat.group:
        return Role.ADMIN  # your own private chat
    if str(chat.user_id) in state.roles:
        return Role(state.roles[str(chat.user_id)])
    return Role.ADMIN if chat.telegram_admin else Role.VIEWER


# ----- rate limits -------------------------------------------------------------------


class RateLimiter:
    """Token buckets: per user and per group, refilled continuously."""

    def __init__(
        self,
        user_per_min: int = USER_PER_MIN,
        group_per_min: int = GROUP_PER_MIN,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rates = {"u": user_per_min, "g": group_per_min}
        self.clock = clock
        self.buckets: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def _take(self, key: str, rate: int) -> bool:
        now = self.clock()
        tokens, last = self.buckets.get(key, (float(rate), now))
        tokens = min(float(rate), tokens + (now - last) * rate / 60.0)
        if tokens < 1.0:
            self.buckets[key] = (tokens, now)
            return False
        self.buckets[key] = (tokens - 1.0, now)
        return True

    def allow(self, chat: Chat) -> bool:
        with self.lock:
            if chat.group and not self._take(f"g{chat.chat_id}", self.rates["g"]):
                return False
            return self._take(f"u{chat.user_id}", self.rates["u"])


# ----- running CLI commands ------------------------------------------------------------

_RUN_LOCK = threading.Lock()


def run_cli(
    args: list[str], workspace: str, author: dict[str, Any] | None = None
) -> tuple[int, str]:
    """Run `langsuite --plain ARGS` in-process for one workspace; return (exit, text)."""
    from langsuite.cli.app import main
    from langsuite.core.workspace import CURRENT_AUTHOR, Workspace

    out = io.StringIO()
    with _RUN_LOCK:
        saved = {k: os.environ.get(k) for k in ("LANGSUITE_WORKSPACE", "COLUMNS", "NO_COLOR")}
        os.environ.update(LANGSUITE_WORKSPACE=workspace, COLUMNS=str(WIDTH), NO_COLOR="1")
        token = CURRENT_AUTHOR.set(author)
        code = 0
        try:
            ws = Workspace(None, workspace)
            if not ws.exists():
                ws.init()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                try:
                    main(["--plain", *args])
                except SystemExit as stop:
                    code = (
                        stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
                    )
        finally:
            CURRENT_AUTHOR.reset(token)
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return code, out.getvalue().rstrip()


Runner = Callable[[list[str], str, dict[str, Any] | None], tuple[int, str]]


# ----- the handler -------------------------------------------------------------------


def _reply(body: str, header: str = "", code_block: bool = True) -> Reply:
    plain = f"{header}\n{body}".strip() if header else body
    if len(plain) > MAX_MESSAGE:
        note = "Long result: sent as a file."
        text = (md_escape(header) + "\n" if header else "") + md_escape(note)
        return Reply(text, ("langsuite.txt", plain.encode()), plain)
    parts = [md_escape(header)] if header else []
    parts.append(md_pre(body) if code_block else md_escape(body))
    return Reply("\n".join(parts), None, plain)


def _text_reply(body: str) -> Reply:
    return _reply(body, code_block=False)


def help_text() -> str:
    lines = ["langsuite: programming languages, with evidence.", ""]
    for c in BOT_COMMANDS:
        lines.append(f"/{c.name} (/{c.alias}): {c.help}")
    lines += ["", *(f"/{k}: {v}" for k, v in BOT_ONLY.items())]
    lines += ["", "Each chat has its own workspace. Same results as the langsuite CLI."]
    return "\n".join(lines)


def parse(text: str) -> tuple[str, list[str], str]:
    """'/q@langsuite_bot a b\\ncode' -> ('q', ['a', 'b'], 'code')."""
    first, _, rest = text.strip().partition("\n")
    head, _, argline = first.partition(" ")
    name = head.lstrip("/").split("@", 1)[0].lower()
    return name, shlex.split(argline), rest


def _shape(name: str, sub: str, args: list[str]) -> list[str]:
    """Chat-friendly arguments: free text does not need quotes."""
    if not args or any(a.startswith("-") for a in args):
        return args
    if name == "query" or (name == "note" and sub == "add"):
        return [" ".join(args)]
    if name == "extract" and not re.fullmatch(r"f\d+|last", args[0]):
        return ["--title", " ".join(args)]
    return args


class Bot:
    def __init__(
        self,
        home: Path | None = None,
        runner: Runner | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.home = home
        self.runner = runner or run_cli
        self.limiter = limiter or RateLimiter()

    @property
    def registry(self) -> Registry:
        return Registry(bot_dir(self.home) / "handles.json")

    def workspace(self, chat: Chat) -> str:
        return internal_workspace(chat.workspace, self.registry.get(chat.owner_key).workspace)

    def where(self, chat: Chat) -> str:
        owner = self.registry.get(chat.owner_key)
        return owner.display or self.workspace(chat)

    def handle(self, text: str, chat: Chat) -> Reply | None:
        if not text.startswith("/"):
            return None  # privacy mode: commands only
        if not self.limiter.allow(chat):
            return _text_reply("Sorry, that is a lot of requests. Please wait a minute and retry.")
        try:
            name, args, rest = parse(text)
        except ValueError as err:
            return _text_reply(f"error: could not read that command ({err}).")
        state = load_state(chat.chat_id, self.home)
        role = role_of(chat, state)
        if name == "help":
            return _reply(help_text(), code_block=False)
        if name in ("link", "private"):
            return self._account(name, args, chat, role)
        if name in ("start", "handle", "space"):
            return self._onboard(name, args, chat, role)
        if name == "role":
            return self._role(chat, state, role, args)
        if name == "settings":
            return self._settings(chat, state, role, args)
        if name == "mode":
            return self._mode(chat, state, role, args)
        if name == "digest":
            return self._digest(chat, state, role, args, rest)
        cmd = BY_NAME.get(name)
        if cmd is None:
            return _text_reply(f"error: unknown command /{name}. Try /help.")
        return self._run(cmd, args, rest, chat, state, role)

    # -- onboarding

    def _onboard(self, name: str, args: list[str], chat: Chat, role: Role) -> Reply:
        reg = self.registry
        key = chat.owner_key
        owner = reg.get(key)
        whose = "this group's" if chat.group else "your"
        if chat.group and role is not Role.ADMIN and (name != "start" or owner.handle is None):
            if name == "start":
                return _text_reply("This group is not set up yet. A group admin can run /start.")
            return _text_reply("Not allowed: only group admins can change the group's handle "
                               "or workspace.")  # fmt: skip
        if name == "start" and owner.handle:
            return _reply(f"Welcome back. You are in {owner.display}.\n\n{help_text()}",
                          code_block=False)  # fmt: skip
        if name == "start" or (name == "handle" and not args):
            seeds = [chat.title] if chat.group else [chat.username, chat.user_name]
            picks = reg.suggest(key, seeds)
            msg = (f"Welcome to langsuite. Pick {whose} handle (tap one), or type "
                   "/handle yourname to choose your own.")  # fmt: skip
            reply = _text_reply(msg + "\n\nSuggestions: " + ", ".join(picks))
            reply.buttons = [(p, f"/handle {p}") for p in picks]
            return reply
        if name == "handle":
            want = args[0].lstrip("@$").lower()
            why = reg.claim(key, want)
            if why:
                return _text_reply(f"Sorry, {want} is not available: {why}.")
            if owner.handle and owner.handle != want:
                note = f"Handle changed from {owner.handle} to {want}."
                return _text_reply(f"{note} You are in {reg.get(key).display}.")
            reply = _text_reply(f"Handle {want} is yours. Now pick {whose} first workspace "
                                "(tap one), or type /space name.")  # fmt: skip
            reply.buttons = [(w, f"/space {w}") for w in (DEFAULT_WS, "research", "notes")]
            return reply
        # space
        if owner.handle is None:
            return _text_reply("Pick a handle first: /start.")
        if not args:
            spaces = ", ".join(owner.workspaces) or DEFAULT_WS
            return _text_reply(f"You are in {owner.display}. Workspaces: {spaces}.")
        want = args[0].lower()
        why = reg.use(key, want)
        if why:
            return _text_reply(f"Sorry, {want} is not a valid workspace name: {why}.")
        code, out = self.runner(["workspace", "show"], self.workspace(chat), None)
        if code != 0:
            return _text_reply(f"error: could not create the workspace ({out[:200]}).")
        new = want not in owner.workspaces
        verb = "Created and switched to" if new else "Switched to"
        return _text_reply(f"{verb} {reg.get(key).display}. Try /q homoiconicity or /help.")

    def _account(self, name: str, args: list[str], chat: Chat, role: Role) -> Reply:
        if chat.group and role is not Role.ADMIN:
            return _text_reply("Not allowed: only group admins can change the group's account.")
        reg, key = self.registry, chat.owner_key
        if name == "private":
            if not args or args[0] not in ("on", "off"):
                state = "on" if reg.get(key).private else "off"
                return _text_reply(f"Private is {state}. Use /private on or /private off.")
            reg.set_private(key, args[0] == "on")
            return _text_reply(f"Private: {args[0]}.")
        if not args:
            return _text_reply("Run `langsuite account link` on your computer, then send "
                               "/link CODE here.")  # fmt: skip
        why = reg.redeem(args[0], key)
        if why:
            return _text_reply(f"Could not link: {why}.")
        owner = reg.get(key)
        return _text_reply(
            "Linked. This chat now uses your account: "
            + (owner.display or "no handle yet; /handle name")
            + "."
        )

    # -- admin commands

    def _role(self, chat: Chat, state: ChatState, role: Role, args: list[str]) -> Reply:
        if not chat.group:
            return _text_reply("Roles apply in groups. In a private chat you are the admin.")
        if not args:
            mine = f"Your role: {role.value}."
            listed = [f"{uid}: {r}" for uid, r in sorted(state.roles.items())]
            return _reply("\n".join([mine, *listed]), code_block=False)
        if role is not Role.ADMIN:
            return _text_reply("Not allowed: only admins can change roles.")
        if chat.reply_to is not None:
            target, who = chat.reply_to
            want = args[0]
        elif len(args) == 2 and args[0].lstrip("-").isdigit():
            target, who, want = int(args[0]), args[0], args[1]
        else:
            return _text_reply("error: reply to a member's message with /role contributor.")
        try:
            new = Role(want.lower())
        except ValueError:
            return _text_reply("error: role is admin, contributor or viewer.")
        state.roles[str(target)] = new.value
        save_state(chat.chat_id, state, self.home)
        return _text_reply(f"{who} is now {new.value}.")

    def _settings(self, chat: Chat, state: ChatState, role: Role, args: list[str]) -> Reply:
        if len(args) == 2 and args[0] == "coderuns" and args[1] in ("on", "off"):
            if role is not Role.ADMIN:
                return _text_reply("Not allowed: only admins can change settings.")
            state.code_runs = args[1] == "on"
            save_state(chat.chat_id, state, self.home)
        elif args:
            return _text_reply("error: try /settings coderuns on|off.")
        runs = "on" if state.code_runs else "off"
        return _reply(
            f"workspace: {self.where(chat)}\nyour role: {role.value}\ncode runs: {runs}",
            code_block=False,
        )

    def _mode(self, chat: Chat, state: ChatState, role: Role, args: list[str]) -> Reply:
        if args:
            if args[0] not in ("concise", "default", "thorough"):
                return _text_reply("error: try /mode concise, /mode default or /mode thorough.")
            if role is not Role.ADMIN:
                return _text_reply("Not allowed: only admins can change the chat's mode.")
            state.mode = None if args[0] == "default" else args[0]
            save_state(chat.chat_id, state, self.home)
        return _text_reply(f"mode: {state.mode or 'default'} (replies in this chat)")

    def _digest(
        self, chat: Chat, state: ChatState, role: Role, args: list[str], rest: str
    ) -> Reply:
        if not args:
            d = state.digest
            if not d:
                return _text_reply("No digest. Try /digest weekly mon 09:00 macros top=5")
            when = f"{d['every']} {d.get('day', '')} {d['time']}".replace("  ", " ")
            return _text_reply(f"digest: {when} ({d['tz']}): /q {d['query']}")
        if role.rank < WRITE.rank:
            return _text_reply("Not allowed: contributors can set digests.")
        if args[0] == "off":
            state.digest = None
            save_state(chat.chat_id, state, self.home)
            return _text_reply("Digest off.")
        try:
            digest = parse_digest(args)
        except ValueError as err:
            return _text_reply(f"error: {err}")
        state.digest = digest
        save_state(chat.chat_id, state, self.home)
        when = f"{digest['every']} {digest.get('day', '')} {digest['time']}".replace("  ", " ")
        return _text_reply(f"Digest set: {when} ({digest['tz']}), runs /q {digest['query']}")

    def due_digests(self, now: datetime) -> list[tuple[int, Reply]]:
        """Run every digest whose slot has passed since it last ran; marks them run."""
        out: list[tuple[int, Reply]] = []
        folder = bot_dir(self.home) / "chats"
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            chat_id = int(path.stem)
            state = load_state(chat_id, self.home)
            d = state.digest
            if not d:
                continue
            slot = last_slot(d, now)
            if d.get("last") and d["last"] >= slot.isoformat():
                continue
            chat = Chat(chat_id, 0, "digest", chat_id < 0)
            code, text = self.runner(["query", *shlex.split(d["query"])], self.workspace(chat),
                                     {"id": 0, "name": "digest", "via": "telegram"})  # fmt: skip
            d["last"] = slot.isoformat()
            save_state(chat_id, state, self.home)
            self._digest_event(chat, d)
            header = f"{self.where(chat)} · digest · /q {d['query']}"
            out.append((chat_id, _reply(text or f"exit {code}", header)))
        return out

    def _digest_event(self, chat: Chat, d: dict[str, Any]) -> None:
        from langsuite.core.workspace import Workspace

        try:
            Workspace(None, self.workspace(chat)).event("digest.ready", {"query": d["query"]})
        except OSError:
            log.warning("digest event not recorded for chat %s", chat.chat_id)

    def inline(self, text: str, user_id: int) -> list[tuple[str, str]]:
        """Inline mode: `@langsuite_bot similar haskell` → (title, plain text) cards."""
        text = text.strip()
        if not text:
            return []
        words = text.split()
        name = words[0].lstrip("/").lower()
        cmd = BY_NAME.get(name)
        if cmd is None or cmd.subs.get("", Role.ADMIN) is not READ or cmd.needs_code:
            cmd, words = BY_NAME["ask"], ["ask", *words]
        if any(w.split("=", 1)[0] in _BLOCKED for w in words):
            return []
        chat = Chat(user_id, user_id, "inline")
        code, out = self.runner([cmd.name, *words[1:]], self.workspace(chat), None)
        if code != 0 or not out.strip():
            return []
        return [(f"/{cmd.alias} {' '.join(words[1:])}"[:64], out[:3500])]

    # -- CLI commands

    def _run(
        self, cmd: BotCommand, args: list[str], rest: str, chat: Chat, state: ChatState, role: Role
    ) -> Reply:
        sub = ""
        if cmd.subs.keys() - {""}:
            sub = args[0] if args and args[0] in cmd.subs else cmd.default_sub
            if args and args[0] in cmd.subs:
                args = args[1:]
        if sub not in cmd.subs:
            return _text_reply(f"error: /{cmd.name} has no `{sub}` here.")
        need = cmd.subs[sub]
        if role.rank < need.rank:
            return _text_reply(f"Not allowed: {need.value}s can do that; you are a {role.value}.")
        bad = [a for a in args if a.split("=", 1)[0] in _BLOCKED]
        if bad:
            return _text_reply(f"error: {bad[0]} is not available in chats.")
        args = _shape(cmd.name, sub, args)
        cli = [cmd.name, *([sub] if sub else []), *args]
        if state.mode:
            cli = ["--mode", state.mode, *cli]
        if cmd.name == "query" and "--save" in args and role.rank < WRITE.rank:
            return _text_reply("Not allowed: contributors can save queries.")
        if cmd.name == "snippet":
            if any(a in _BLOCKED_SNIPPET_NOCODE for a in args) and not state.code_runs:
                return _text_reply("Code runs are off in this chat. An admin can turn them on.")
            if not state.code_runs:
                cli.append("--no-verify")
        if cmd.needs_code:
            if not state.code_runs:
                return _text_reply(
                    "Code runs are off in this chat, so your code was not run. "
                    "An admin can enable them with /settings coderuns on."
                )
            if not rest.strip():
                return _text_reply("error: put the code on the lines after /verify <lang>.")
            if args and not args[0].startswith("-"):
                args = ["--lang", args[0], *args[1:]]
            cli = ["verify", "<code>", *args]
        author = {"id": chat.user_id, "name": chat.user_name, "chat": chat.chat_id,
                  "via": "telegram"}  # fmt: skip
        if cmd.needs_code:
            code, out = self._run_code(cli, rest, chat, author)
        else:
            code, out = self.runner(cli, self.workspace(chat), author)
        shown = cli[2:] if cli[0] == "--mode" else cli
        header = f"{self.where(chat)} · /{cmd.alias} {' '.join(shown[1:])}".strip()
        reply = _reply(out or ("done" if code == 0 else f"exit {code}"), header)
        reply.failed = code != 0
        return reply

    def _run_code(
        self, cli: list[str], code_text: str, chat: Chat, author: dict[str, Any]
    ) -> tuple[int, str]:
        tmp = bot_dir(self.home) / "code"
        tmp.mkdir(parents=True, exist_ok=True)
        path = tmp / f"{uuid.uuid4().hex}.src"
        path.write_text(code_text, encoding="utf-8")
        try:
            return self.runner(["verify", str(path), *cli[2:]], self.workspace(chat), author)
        finally:
            path.unlink(missing_ok=True)
