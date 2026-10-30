"""Onboarding: handles and workspaces for Telegram users and groups (an M5g slice).

A user (or, in a group, an admin) claims a handle; the chat then works in
`$langsuite/<handle>/<workspace>`. Handles are lowercase ASCII, unique ignoring
case and look-alike digits, and never a reserved word.
"""

from __future__ import annotations

import json
import re
import threading
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
_LOOKALIKE = str.maketrans("013457", "oleast")
DEFAULT_WS = "main"
_LOCK = threading.Lock()


def skeleton(handle: str) -> str:
    """The form used for uniqueness: case, look-alike digits and underscores folded."""
    return handle.lower().translate(_LOOKALIKE).replace("_", "")


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

    def get(self, key: str) -> Owner:
        rec = self._load()["owners"].get(key, {})
        return Owner(key, rec.get("handle"), rec.get("workspace", DEFAULT_WS),
                     tuple(rec.get("workspaces", ())))  # fmt: skip

    def problem(self, handle: str, key: str = "") -> str | None:
        """Why HANDLE cannot be claimed by KEY, or None."""
        if not HANDLE_RE.fullmatch(handle):
            return "use 3-20 characters: a-z, 0-9 and _, starting with a letter"
        if handle in RESERVED or skeleton(handle) in {skeleton(r) for r in RESERVED}:
            return "that name is reserved"
        for other, rec in self._load()["owners"].items():
            if other != key and rec.get("handle") and skeleton(rec["handle"]) == skeleton(handle):
                return "that handle (or one that looks like it) is taken"
        return None

    def suggest(self, key: str, seeds: list[str], n: int = 3) -> list[str]:
        out: list[str] = []
        bases = [slugify(s) for s in seeds if s and s.strip()] or ["langfan"]
        suffix = key.lstrip("ug")[-3:]
        candidates = [b for b in bases]
        for b in bases:
            candidates += [f"{b[:16]}_dev", f"{b[:16]}_{suffix}", f"{b[:15]}_lang"]
        for c in candidates:
            if c not in out and self.problem(c, key) is None:
                out.append(c)
            if len(out) == n:
                break
        return out

    def claim(self, key: str, handle: str) -> str | None:
        with _LOCK:
            why = self.problem(handle, key)
            if why:
                return why
            data = self._load()
            rec = data["owners"].setdefault(key, {})
            rec["handle"] = handle
            rec.setdefault("workspace", DEFAULT_WS)
            rec["workspaces"] = sorted(set(rec.get("workspaces", [])) | {rec["workspace"]})
            self._save(data)
        return None

    def use(self, key: str, workspace: str) -> str | None:
        if not WS_RE.fullmatch(workspace):
            return "use 1-24 characters: a-z, 0-9 and -, starting with a letter"
        with _LOCK:
            data = self._load()
            rec = data["owners"].setdefault(key, {})
            rec["workspace"] = workspace
            rec["workspaces"] = sorted(set(rec.get("workspaces", [])) | {workspace})
            self._save(data)
        return None


def internal_workspace(base: str, workspace: str) -> str:
    """CLI workspace name: 'tg-u42' for main, 'tg-u42-notes' otherwise."""
    return base if workspace == DEFAULT_WS else f"{base}-{workspace}"
