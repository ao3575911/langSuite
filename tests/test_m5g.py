"""M5g: handles, renames and holds, linking, privacy, streaks and badges."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from langsuite.bot.core import Bot, Chat
from langsuite.bot.onboarding import DAY, Registry
from langsuite.cli.app import app
from langsuite.core import gamify
from langsuite.core.workspace import Workspace

T0 = 1_800_000_000.0


def _cli(*args: str) -> Any:
    return CliRunner().invoke(app, list(args))


def _reg(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "handles.json")


def test_nominations_from_profile(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    picks = reg.nominate("c1", {"name": "Ada Lovelace", "username": "ada", "languages": ["ocaml"]})
    assert len(picks) == 3 and all(reg.problem(p, "c1") is None for p in picks)
    assert picks[0] == "ada"


def test_collisions_confusables_profanity_reserved(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    assert reg.claim("u1", "lazy") is None
    assert "taken" in (reg.problem("Lazy", "u2") or "")
    assert "taken" in (reg.problem("l4zy", "u2") or "")
    assert "reserved" in (reg.problem("l4ngsuite", "u2") or "")
    assert "look-alike" in (reg.problem("langsuíte", "u2") or "")
    assert "not allowed" in (reg.problem("shithead", "u2") or "")
    assert "reserved" in (reg.problem("admin", "u2") or "")


def test_rename_hold_redirect_and_30_day_limit(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    assert reg.claim("u1", "ada_l", now=T0) is None
    assert reg.claim("u1", "ada_lovelace", now=T0 + DAY) is None
    owner = reg.resolve("ada_l", now=T0 + 2 * DAY)
    assert owner is not None and owner.handle == "ada_lovelace"  # redirect
    assert "on hold" in (reg.problem("ada_l", "u2", now=T0 + 2 * DAY) or "")
    assert "30 days" in (reg.claim("u1", "countess", now=T0 + 10 * DAY) or "")
    assert reg.claim("u1", "countess", now=T0 + 32 * DAY) is None
    assert reg.resolve("ada_l", now=T0 + 182 * DAY) is None  # hold over
    assert reg.claim("u2", "ada_l", now=T0 + 182 * DAY) is None
    assert reg.get("u1").key == "u1"  # same user id after renames


def test_private_handle_hidden_from_non_members(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.claim("u1", "secret_sam")
    reg.set_private("u1", True)
    assert reg.resolve("secret_sam", viewer="u2") is None
    assert reg.resolve("secret_sam", viewer="u1") is not None


def test_link_cli_account_to_telegram(kb_home: Path) -> None:
    assert _cli("account", "claim", "ada_l").exit_code == 0
    code = json.loads(_cli("--json", "account", "link").stdout)["data"]["code"]
    bot = Bot(home=kb_home)
    chat = Chat(7, 42, "Ada", username="ada")
    assert "unknown or expired" in bot.handle("/link NOPE-NOPE-NOPE", chat).plain  # type: ignore[union-attr]
    reply = bot.handle(f"/link {code}", chat)
    assert reply is not None and "$langsuite/ada_l/" in reply.plain
    assert bot.where(chat).startswith("$langsuite/ada_l/")  # Telegram header
    acct = json.loads(_cli("--json", "account").stdout)["data"]
    assert acct["linked"] == ["u42"] and acct["display"] == "$langsuite/ada_l/default"


def test_group_slug_resolves(kb_home: Path) -> None:
    bot = Bot(home=kb_home)
    admin = Chat(-100, 1, "Admin", group=True, telegram_admin=True, title="Lisp Club")
    bot.handle("/start", admin)
    bot.handle("/handle lisp_club", admin)
    out = _cli("--json", "account", "lookup", "lisp_club")
    assert out.exit_code == 0 and json.loads(out.stdout)["data"]["handle"] == "lisp_club"


def test_streak_and_badges_recompute_identically() -> None:
    rows = [{"at": f"2026-10-{d:02d}T02:00:00Z", "kind": "finding.saved"} for d in range(20, 28)]
    rows += [{"at": "2026-10-27T03:00:00Z", "kind": "note.added"}]
    s1 = gamify.streak(rows, today=date(2026, 10, 27))
    assert s1 == gamify.streak(list(reversed(rows)), today=date(2026, 10, 27))
    assert s1["current"] == 8 and s1["best"] == 8
    earned = {b.id for b in gamify.badges(rows) if b.earned}
    assert earned == {"first-finding", "week-streak"}


def test_gamification_off_hides_and_records_nothing(kb_home: Path) -> None:
    ws = Workspace.open()
    ws.add_note("hello")
    log = ws.path / "events.jsonl"
    n = len(log.read_text().splitlines())
    assert _cli("settings", "gamification", "off").exit_code == 0
    ws.add_note("quiet")
    assert len(log.read_text().splitlines()) == n
    out = _cli("--plain", "badges")
    assert "Gamification is off" in out.stdout and "Collector" not in out.stdout
    assert _cli("settings", "gamification", "on").exit_code == 0
    assert "Note taker" in _cli("--plain", "badges").stdout
    assert "Current streak: 1" in _cli("--plain", "streak").stdout
