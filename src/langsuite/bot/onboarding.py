"""Onboarding: handles and workspaces for Telegram users and groups (an M5g slice).

A user (or, in a group, an admin) claims a handle; the chat then works in
`$langsuite/<handle>/<workspace>`. Handles are lowercase ASCII, unique ignoring
case and look-alike digits, and never a reserved word.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HANDLE_RE = re.compile(r"[a-z][a-z0-9_]{2,19}")
WS_RE = re.compile(r"[a-z][a-z0-9-]{0,23}")
RESERVED = frozenset(
    [
        "admin",
        "administrator",
        "api",
        "bot",
        "help",
        "langsuite",
        "langsuite_bot",
        "me",
        "mod",
        "moderator",
        "null",
        "owner",
        "root",
        "settings",
        "staff",
        "start",
        "support",
        "system",
        "telegram",
        "test",
        "user",
        "workspace",
        "www",
    ]
)
_LOOKALIKE = str.maketrans("0134578", "oleastb")
# Short and conservative; a hosted deployment loads a fuller list (OPEN_QUESTIONS 33).
PROFANE = frozenset(["fuck", "shit", "cunt", "bitch", "nigger", "faggot", "wanker", "twat", "slut"])
HOLD_DAYS = 180
RENAME_EVERY_DAYS = 30
LINK_TTL = 600
DAY = 86400.0
DEFAULT_WS = "main"
_LOCK = threading.Lock()


def skeleton(handle: str) -> str:
    """The form used for uniqueness: case, look-alike digits and underscores folded."""
    return handle.lower().translate(_LOOKALIKE).replace("_", "")


def confusable(handle: str) -> bool:
    """Non-ASCII letters that fold to ASCII ('langsuíte'): look-alikes of another name."""
    return any(ord(c) > 127 for c in handle)


def fold(handle: str) -> str:
    """ASCII fold used to compare a confusable handle against taken and reserved names."""
    flat = unicodedata.normalize("NFKD", handle).encode("ascii", "ignore").decode()
    return skeleton(flat)


def profane(handle: str) -> bool:
    sk = skeleton(handle)
    return any(w in sk for w in PROFANE)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower().encode("ascii", "ignore").decode()).strip("_")
    if not s or not s[0].isalpha():
        s = "lang_" + s
    return s[:20].rstrip("_")


@dataclass
class Owner:
    key: str  # "u<id>" or "g<id>"
    handle: str | None = None
    workspace: str = DEFAULT_WS
    workspaces: tuple[str, ...] = ()
    private: bool = False
    renamed_at: float | None = None
    linked: tuple[str, ...] = ()

    @property
    def display(self) -> str | None:
        return f"$langsuite/{self.handle}/{self.workspace}" if self.handle else None


class Registry:
    """Handles and current workspaces, stored in <home>/bot/handles.json."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"owners": {}}
        data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def _owner_key(self, data: dict[str, Any], key: str) -> str:
        """Linked accounts share one record: follow the alias."""
        return str(data["owners"].get(key, {}).get("alias", key))

    def get(self, key: str) -> Owner:
        data = self._load()
        key = self._owner_key(data, key)
        rec = data["owners"].get(key, {})
        linked = tuple(k for k, r in data["owners"].items() if r.get("alias") == key)
        return Owner(key, rec.get("handle"), rec.get("workspace", DEFAULT_WS),
                     tuple(rec.get("workspaces", ())), bool(rec.get("private")),
                     rec.get("renamed_at"), linked)  # fmt: skip

    def _holds(self, data: dict[str, Any], now: float) -> dict[str, Any]:
        return {k: v for k, v in data.get("holds", {}).items() if v["until"] > now}

    def problem(self, handle: str, key: str = "", now: float | None = None) -> str | None:
        """Why HANDLE cannot be claimed by KEY, or None."""
        now = time.time() if now is None else now
        data = self._load()
        key = self._owner_key(data, key)
        if confusable(handle):
            return "use plain a-z letters; that name has look-alike characters"
        sk = skeleton(handle)
        for other, rec in data["owners"].items():
            if other != key and rec.get("handle") and skeleton(rec["handle"]) == sk:
                return "that handle (or one that looks like it) is taken"
        hold = self._holds(data, now).get(sk)
        if hold and hold["key"] != key:
            return "that handle was renamed recently and is on hold"
        if not HANDLE_RE.fullmatch(handle):
            return "use 3-20 characters: a-z, 0-9 and _, starting with a letter"
        if handle in RESERVED or sk in {skeleton(r) for r in RESERVED}:
            return "that name is reserved"
        if profane(handle):
            return "that name is not allowed"
        return None

    def suggest(self, key: str, seeds: list[str], n: int = 3) -> list[str]:
        out: list[str] = []
        bases = [slugify(s) for s in seeds if s and s.strip()] or ["langfan"]
        suffix = key.lstrip("ugc")[-3:]
        candidates = [b for b in bases]
        for b in bases:
            candidates += [f"{b[:16]}_dev", f"{b[:16]}_{suffix}", f"{b[:15]}_lang"]
        for c in candidates:
            if c not in out and self.problem(c, key) is None:
                out.append(c)
            if len(out) == n:
                break
        return out

    def nominate(self, key: str, profile: dict[str, Any], n: int = 3) -> list[str]:
        """Handle nominations from a profile: name, username, favourite languages."""
        seeds = [str(profile.get(k) or "") for k in ("username", "name")]
        seeds += [f"{profile.get('name', '').split(' ')[0]}_{lang}"
                  for lang in profile.get("languages", [])]  # fmt: skip
        return self.suggest(key, [s for s in seeds if s.strip("_")], n)

    def claim(self, key: str, handle: str, now: float | None = None) -> str | None:
        """Claim a first handle, or rename (30-day limit; old name held 180 days)."""
        now = time.time() if now is None else now
        with _LOCK:
            why = self.problem(handle, key, now)
            if why:
                return why
            data = self._load()
            key = self._owner_key(data, key)
            rec = data["owners"].setdefault(key, {})
            old = rec.get("handle")
            if old and old != handle:
                last = rec.get("renamed_at")
                if last and now - last < RENAME_EVERY_DAYS * DAY:
                    days = int((last + RENAME_EVERY_DAYS * DAY - now) // DAY) + 1
                    return f"you can rename once every {RENAME_EVERY_DAYS} days ({days} to go)"
                data.setdefault("holds", {})[skeleton(old)] = {
                    "handle": old, "key": key, "until": now + HOLD_DAYS * DAY}  # fmt: skip
                rec["renamed_at"] = now
            data.get("holds", {}).pop(skeleton(handle), None)
            rec["handle"] = handle
            rec.setdefault("workspace", DEFAULT_WS)
            rec["workspaces"] = sorted(set(rec.get("workspaces", [])) | {rec["workspace"]})
            self._save(data)
        return None

    def resolve(self, handle: str, viewer: str = "", now: float | None = None) -> Owner | None:
        """Owner for HANDLE (old handles redirect during the hold); private ones only to members."""
        now = time.time() if now is None else now
        data = self._load()
        sk = skeleton(handle.lstrip("$@"))
        key = next((k for k, r in data["owners"].items()
                    if r.get("handle") and skeleton(r["handle"]) == sk), None)  # fmt: skip
        if key is None:
            hold = self._holds(data, now).get(sk)
            key = hold["key"] if hold else None
        if key is None:
            return None
        owner = self.get(key)
        if owner.private and self._owner_key(data, viewer) != owner.key:
            return None
        return owner

    def set_private(self, key: str, private: bool) -> None:
        with _LOCK:
            data = self._load()
            data["owners"].setdefault(self._owner_key(data, key), {})["private"] = private
            self._save(data)

    def link_code(self, key: str, now: float | None = None) -> str:
        """A one-time code; `/link CODE` in Telegram joins that chat user to this account."""
        now = time.time() if now is None else now
        code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
        with _LOCK:
            data = self._load()
            codes = {c: v for c, v in data.get("codes", {}).items() if v["expires"] > now}
            codes[code] = {"key": self._owner_key(data, key), "expires": now + LINK_TTL}
            data["codes"] = codes
            self._save(data)
        return code

    def redeem(self, code: str, key: str, now: float | None = None) -> str | None:
        """Link KEY to the account that issued CODE; returns a problem or None."""
        now = time.time() if now is None else now
        with _LOCK:
            data = self._load()
            rec = data.get("codes", {}).pop(code.strip().upper(), None)
            if rec is None or rec["expires"] <= now:
                return "that code is unknown or expired; run `langsuite account link` again"
            target = rec["key"]
            if target == key:
                return "that code belongs to this account"
            mine = data["owners"].get(key, {})
            if mine.get("handle") and data["owners"].get(target, {}).get("handle"):
                return "both accounts already have handles; link from a fresh chat"
            data["owners"].setdefault(target, {})
            for field in ("handle", "workspace", "workspaces"):
                if field in mine and field not in data["owners"][target]:
                    data["owners"][target][field] = mine[field]
            data["owners"][key] = {"alias": target}
            self._save(data)
        return None

    def use(self, key: str, workspace: str) -> str | None:
        if not WS_RE.fullmatch(workspace):
            return "use 1-24 characters: a-z, 0-9 and -, starting with a letter"
        with _LOCK:
            data = self._load()
            rec = data["owners"].setdefault(self._owner_key(data, key), {})
            rec["workspace"] = workspace
            rec["workspaces"] = sorted(set(rec.get("workspaces", [])) | {workspace})
            self._save(data)
        return None


def internal_workspace(base: str, workspace: str) -> str:
    """CLI workspace name: 'tg-u42' for main, 'tg-u42-notes' otherwise."""
    return base if workspace == DEFAULT_WS else f"{base}-{workspace}"
