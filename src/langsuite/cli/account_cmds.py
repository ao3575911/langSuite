"""account, badges, streak, settings (SPEC §7, M5g): handles, linking, gamification."""

from __future__ import annotations

import getpass
import json
import uuid
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape

from langsuite.bot.onboarding import Registry
from langsuite.cli.kb_cmds import _console, _emit, _json
from langsuite.core import gamify, settings
from langsuite.core.errors import NoResultError, UsageError
from langsuite.core.paths import data_home
from langsuite.core.workspace import Workspace, active_slug

account_app = typer.Typer(help="Your handle, linking and privacy.", invoke_without_command=True)
settings_app = typer.Typer(help="Preferences such as gamification.", invoke_without_command=True)


def registry(home: Path | None = None) -> Registry:
    return Registry((home or data_home()) / "bot" / "handles.json")


def local_key(home: Path | None = None) -> str:
    """This machine's account key (`c<hex>`), made on first use."""
    path = (home or data_home()) / "account.json"
    try:
        return str(json.loads(path.read_text(encoding="utf-8"))["key"])
    except (OSError, ValueError, KeyError):
        path.parent.mkdir(parents=True, exist_ok=True)
        key = "c" + uuid.uuid4().hex[:12]
        path.write_text(json.dumps({"key": key}) + "\n", encoding="utf-8")
        return key


def display(home: Path | None = None) -> str:
    """`$langsuite/<handle>/<workspace>` (guest until a handle is claimed)."""
    owner = registry(home).get(local_key(home))
    return f"$langsuite/{owner.handle or 'guest'}/{active_slug(home)}"


def _owner_json(home: Path | None = None) -> dict[str, Any]:
    owner = registry(home).get(local_key(home))
    return {
        "key": owner.key,
        "handle": owner.handle,
        "display": display(home),
        "private": owner.private,
        "linked": list(owner.linked),
        "gamification": settings.load()["gamification"],
    }


def _say(ctx: typer.Context, kind: str, data: dict[str, Any], text: str) -> None:
    if _json(ctx):
        _emit(kind, data)
    else:
        _console(ctx).print(text)


@account_app.callback()
def account(ctx: typer.Context) -> None:
    """Show your handle and where you are.

    Example: langsuite account
    """
    if ctx.invoked_subcommand:
        return
    d = _owner_json()
    linked = ", ".join(d["linked"]) or "none"
    _say(
        ctx,
        "account",
        d,
        f"[b]{escape(d['display'])}[/]\nhandle: {d['handle'] or '(none: account claim NAME)'}"
        f"\nprivate: {'yes' if d['private'] else 'no'}\nlinked chats: {linked}",
    )


@account_app.command("suggest")
def account_suggest(
    ctx: typer.Context,
    name: Annotated[str, typer.Option(help="Your name.")] = "",
    languages: Annotated[str, typer.Option(help="Favourite languages, comma-separated.")] = "",
) -> None:
    """Three available handles from your name and favourite languages.

    Example: langsuite account suggest --name "Ada Lovelace" --languages ocaml,lisp
    """
    profile = {
        "username": getpass.getuser() if not name else "",
        "name": name,
        "languages": [x.strip() for x in languages.split(",") if x.strip()],
    }
    picks = registry().nominate(local_key(), profile)
    _say(ctx, "suggestions", {"suggestions": picks}, "\n".join(picks))


def _claim(ctx: typer.Context, handle: str, kind: str) -> None:
    reg, key = registry(), local_key()
    before = reg.get(key).handle
    if kind == "claim" and before:
        raise UsageError(f"You already have `{before}`.", hint="Use `langsuite account rename`.")
    if kind == "rename" and not before:
        raise UsageError("No handle yet.", hint="Use `langsuite account claim NAME`.")
    want = handle.lstrip("$@")
    why = reg.claim(key, want)
    if why:
        raise UsageError(f"`{want}` is not available: {why}.")
    note = f" `{before}` redirects here for 180 days." if before and before != want else ""
    _say(ctx, "account", _owner_json(), f"Handle is now {want}.{note} You are in {display()}.")


@account_app.command("claim")
def account_claim(ctx: typer.Context, handle: Annotated[str, typer.Argument()]) -> None:
    """Claim your first handle.

    Example: langsuite account claim ada_l
    """
    _claim(ctx, handle, "claim")


@account_app.command("rename")
def account_rename(ctx: typer.Context, handle: Annotated[str, typer.Argument()]) -> None:
    """Rename (once per 30 days; the old name redirects and is held for 180 days).

    Example: langsuite account rename ada_lovelace
    """
    _claim(ctx, handle, "rename")


@account_app.command("private")
def account_private(
    ctx: typer.Context, value: Annotated[str, typer.Argument(help="on|off")]
) -> None:
    """Hide your handle from people outside your account.

    Example: langsuite account private on
    """
    if value not in ("on", "off"):
        raise UsageError("Use `on` or `off`.")
    registry().set_private(local_key(), value == "on")
    _say(ctx, "account", _owner_json(), f"Private: {value}.")


@account_app.command("link")
def account_link(ctx: typer.Context) -> None:
    """A one-time code to link a Telegram chat: send `/link CODE` to the bot (10 minutes).

    Example: langsuite account link
    """
    code = registry().link_code(local_key())
    _say(
        ctx,
        "link",
        {"code": code, "expires_in": 600},
        f"Send this to @langsuite_bot within 10 minutes:\n\n  /link {code}",
    )


@account_app.command("lookup")
def account_lookup(ctx: typer.Context, handle: Annotated[str, typer.Argument()]) -> None:
    """Find a handle (old handles redirect during their hold; private ones stay hidden).

    Example: langsuite account lookup ada_l
    """
    owner = registry().resolve(handle, local_key())
    if owner is None:
        raise NoResultError(f"No visible handle `{handle}`.")
    asked = handle.lstrip("$@")
    data = {
        "handle": owner.handle,
        "requested": asked,
        "redirected": owner.handle != asked,
        "workspace": owner.workspace,
    }
    _say(ctx, "lookup", data, f"$langsuite/{owner.handle}/{owner.workspace}")


def _gamified(ctx: typer.Context) -> bool:
    if settings.load()["gamification"]:
        return True
    _say(
        ctx,
        "gamification",
        {"gamification": False},
        "Gamification is off. Turn it on with `langsuite settings gamification on`.",
    )
    return False


def badges(ctx: typer.Context) -> None:
    """Badges earned in this workspace, recomputed from its event log.

    Example: langsuite badges
    """
    if not _gamified(ctx):
        return
    rows = gamify.badges(gamify.events(Workspace.open().path))
    if _json(ctx):
        _emit("badges", {"badges": [b.to_json() for b in rows]})
        return
    con = _console(ctx)
    for b in rows:
        mark = "★" if b.earned else "·"
        con.print(f"{mark} {b.name:<14} {b.progress:>6}  [lw.muted]{b.rule}[/]")


def streak(ctx: typer.Context) -> None:
    """Days in a row you have used this workspace (Perth time).

    Example: langsuite streak
    """
    if not _gamified(ctx):
        return
    s = gamify.streak(gamify.events(Workspace.open().path))
    _say(
        ctx,
        "streak",
        s,
        f"Current streak: {s['current']} day(s). Best: {s['best']}. "
        f"Active days: {s['active_days']}.",
    )


@settings_app.callback()
def settings_show(ctx: typer.Context) -> None:
    """Show preferences.

    Example: langsuite settings
    """
    if ctx.invoked_subcommand:
        return
    data = settings.load()
    lines = [f"{k}: {v if v is not None else '(default)'}" for k, v in data.items()]
    _say(ctx, "settings", data, "\n".join(lines))


@settings_app.command("gamification")
def settings_gamification(
    ctx: typer.Context, value: Annotated[str, typer.Argument(help="on|off")]
) -> None:
    """Turn streaks and badges on or off. Off records no new events.

    Example: langsuite settings gamification off
    """
    if value not in ("on", "off"):
        raise UsageError("Use `on` or `off`.")
    data = settings.save({"gamification": value == "on"})
    _say(ctx, "settings", data, f"Gamification {value}.")


@settings_app.command("profile")
def settings_profile(
    ctx: typer.Context,
    weights: Annotated[list[str] | None, typer.Argument(help="criterion=weight pairs.")] = None,
    clear: Annotated[bool, typer.Option("--clear", help="Remove the profile.")] = False,
) -> None:
    """Set this workspace's scoring profile; it changes only the custom score.

    Example: langsuite settings profile safety=2 popularity=0.5
    """
    from langsuite.core.analysis import criteria

    known = set(criteria()["criteria"])
    ws = Workspace.open()
    if clear:
        ws._set_meta(profile=None)
        _say(ctx, "settings", {"profile": None}, "Profile cleared.")
        return
    prof: dict[str, float] = dict(ws.meta.get("profile") or {})
    for pair in weights or []:
        key, _, val = pair.partition("=")
        if key not in known:
            raise UsageError(
                f"Unknown criterion `{key}`.", hint="Known: " + ", ".join(sorted(known))
            )
        try:
            prof[key] = float(val)
        except ValueError:
            raise UsageError(f"`{pair}` needs a number, like {key}=1.5.") from None
    if weights:
        ws._set_meta(profile=prof)
    text = ", ".join(f"{k}={v:g}" for k, v in sorted(prof.items())) or "(none)"
    _say(ctx, "settings", {"profile": prof}, f"Scoring profile: {text}")
