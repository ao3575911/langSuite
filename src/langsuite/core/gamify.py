"""Streaks and badges, recomputed from the workspace event log (SPEC M5g).

Nothing is stored: the same `events.jsonl` always gives the same counts.
With `settings gamification off` no new events are written and nothing is shown.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Perth")


@dataclass(frozen=True)
class Badge:
    id: str
    name: str
    rule: str
    earned: bool
    progress: str

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "rule": self.rule,
                "earned": self.earned, "progress": self.progress}  # fmt: skip


def events(ws_path: Path) -> list[dict[str, Any]]:
    path = ws_path / "events.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _day(at: str) -> date:
    return datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(TZ).date()


def streak(rows: list[dict[str, Any]], today: date | None = None) -> dict[str, Any]:
    """Consecutive active days ending today (or yesterday, so a streak survives until midnight)."""
    days = sorted({_day(r["at"]) for r in rows if "at" in r})
    today = today or datetime.now(TZ).date()
    active = set(days)
    current = 0
    d = today if today in active else today - timedelta(days=1)
    while d in active:
        current += 1
        d -= timedelta(days=1)
    best = run = 0
    prev: date | None = None
    for d in days:
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return {"current": current, "best": best, "active_days": len(days),
            "last": days[-1].isoformat() if days else None}  # fmt: skip


RULES: list[tuple[str, str, str, str, int]] = [
    # id, name, rule, counted kind ("" = streak best), threshold
    ("first-finding", "First finding", "save 1 finding", "finding.saved", 1),
    ("collector", "Collector", "save 10 findings", "finding.saved", 10),
    ("archivist", "Archivist", "save 50 findings", "finding.saved", 50),
    ("note-taker", "Note taker", "add 5 notes", "note.added", 5),
    ("curious", "Curious", "run 25 commands", "command.run", 25),
    ("week-streak", "Week streak", "7 active days in a row", "", 7),
    ("month-streak", "Month streak", "30 active days in a row", "", 30),
]


def badges(rows: list[dict[str, Any]], today: date | None = None) -> list[Badge]:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("kind", "")] = counts.get(r.get("kind", ""), 0) + 1
    best = streak(rows, today)["best"]
    out = []
    for bid, name, rule, kind, need in RULES:
        have = counts.get(kind, 0) if kind else best
        out.append(Badge(bid, name, rule, have >= need, f"{min(have, need)}/{need}"))
    return out
