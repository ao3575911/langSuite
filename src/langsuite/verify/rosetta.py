"""Rosetta Code pack: fetch, parse, load (SPEC §2, §10 M4).

Rosetta solutions are share-alike, so they live in a separate data pack and never
inside the MIT package. Every served solution carries its attribution line.
The pack is searched in `LANGSUITE_PACKS`, then `<home>/packs/rosetta`, then
the repo's `data-packs/rosetta` when running from a checkout.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langsuite import __version__
from langsuite.core.errors import DataError, NoResultError
from langsuite.core.paths import data_home

PACK = "rosetta"
# The licence name and URL are data: they come from the pack file or the wiki's own
# siteinfo, so no licence text ships inside the MIT wheel (scripts/check_wheel_licences.py).
API = "https://rosettacode.org/w/api.php"
WIKI = "https://rosettacode.org/wiki/"
USER_AGENT = f"langsuite/{__version__} (+https://github.com/ao3575911/langsuite)"

# Tasks whose correct output is fixed, so verification can check it (our own oracle text).
ORACLES: dict[str, str] = {
    "Hello world/Text": "Hello world!",
    "Hello world/Newline omission": "Goodbye, World!",
    "FizzBuzz": "\n".join(
        "FizzBuzz" if i % 15 == 0 else "Fizz" if i % 3 == 0 else "Buzz" if i % 5 == 0 else str(i)
        for i in range(1, 101)
    ),
    "Loops/For": "\n".join("*" * i for i in range(1, 6)),
    "Loops/Downward for": "\n".join(str(i) for i in range(10, -1, -1)),
}
DEFAULT_TASKS: tuple[str, ...] = (*ORACLES, "Factorial", "Fibonacci sequence")

# Rosetta header → KB id, where a plain lowercase/slug of the header is not the id.
HEADER_IDS: dict[str, str] = {
    "C++": "cpp",
    "C#": "csharp",
    "F#": "fsharp",
    "Common Lisp": "common-lisp",
    "JavaScript": "javascript",
    "TypeScript": "typescript",
    "UNIX Shell": "bash",
    "Objective-C": "objective-c",
    "Visual Basic .NET": "visual-basic-dotnet",
}

_HEADER = re.compile(r"^==\s*\{\{\s*header\s*\|\s*([^}|]+?)\s*(?:\|[^}]*)?\}\}.*?==\s*$", re.M)
_CODE = re.compile(r"<(syntaxhighlight|lang)\b([^>]*)>(.*?)</\1\s*>", re.S | re.I)


MAX_VARIANTS = 5


@dataclass(frozen=True)
class Solution:
    """All code blocks of one language section; `variants[0]` is the first shown on the page."""

    lang: str
    header: str
    variants: tuple[str, ...]

    @property
    def code(self) -> str:
        return self.variants[0]

    def to_json(self) -> dict[str, Any]:
        return {"lang": self.lang, "header": self.header, "variants": list(self.variants)}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Solution:
        return cls(d["lang"], d["header"], tuple(d["variants"]))


@dataclass
class Task:
    title: str
    revid: int
    retrieved_at: str
    solutions: dict[str, Solution] = field(default_factory=dict)
    licence: str = ""
    licence_url: str = ""

    @property
    def slug(self) -> str:
        return slugify(self.title)

    @property
    def url(self) -> str:
        return WIKI + urllib.parse.quote(self.title.replace(" ", "_"))

    @property
    def permalink(self) -> str:
        return f"{self.url}?oldid={self.revid}"

    @property
    def expected(self) -> str | None:
        return ORACLES.get(self.title)

    @property
    def attribution(self) -> str:
        return (
            f"Rosetta Code, “{self.title}” (rev {self.revid}), by Rosetta Code contributors, "
            f"{self.permalink} · {self.licence or 'see pack licence'}"
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "task": self.title,
            "revid": self.revid,
            "url": self.permalink,
            "retrieved_at": self.retrieved_at,
            "licence": self.licence,
            "licence_url": self.licence_url,
            "attribution": self.attribution,
            "expected": self.expected,
            "solutions": {k: v.to_json() for k, v in sorted(self.solutions.items())},
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Task:
        sols = {k: Solution.from_json(v) for k, v in d["solutions"].items()}
        return cls(
            d["task"],
            int(d["revid"]),
            d["retrieved_at"],
            sols,
            str(d.get("licence", "")),
            str(d.get("licence_url", "")),
        )


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def header_to_id(header: str, resolve: Callable[[str], str | None] | None = None) -> str:
    if header in HEADER_IDS:
        return HEADER_IDS[header]
    if resolve is not None:
        found = resolve(header)
        if found:
            return found
    return slugify(header)


def parse_wikitext(
    text: str, resolve: Callable[[str], str | None] | None = None
) -> dict[str, Solution]:
    """First code block under each `=={{header|Lang}}==` section."""
    heads = list(_HEADER.finditer(text))
    out: dict[str, Solution] = {}
    for i, h in enumerate(heads):
        body = text[h.end() : heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        blocks = [html.unescape(m.group(3)).strip("\n") + "\n" for m in _CODE.finditer(body)]
        blocks = [b for b in blocks if b.strip()][:MAX_VARIANTS]
        if not blocks:
            continue
        header = h.group(1).strip()
        lang = header_to_id(header, resolve)
        if lang not in out:
            out[lang] = Solution(lang, header, tuple(blocks))
    return out


def pack_dirs(home: Path | None = None) -> list[Path]:
    dirs: list[Path] = []
    env = os.environ.get("LANGSUITE_PACKS")
    if env:
        dirs.append(Path(env).expanduser() / PACK)
    dirs.append((home or data_home()) / "packs" / PACK)
    repo = Path(__file__).resolve().parents[3] / "data-packs" / PACK
    dirs.append(repo)
    return dirs


def user_pack_dir(home: Path | None = None) -> Path:
    env = os.environ.get("LANGSUITE_PACKS")
    if env:
        return Path(env).expanduser() / PACK
    return (home or data_home()) / "packs" / PACK


def load_tasks(home: Path | None = None) -> dict[str, Task]:
    """All tasks across pack dirs; earlier dirs win per task."""
    tasks: dict[str, Task] = {}
    for d in pack_dirs(home):
        tdir = d / "tasks"
        if not tdir.is_dir():
            continue
        for f in sorted(tdir.glob("*.json")):
            try:
                task = Task.from_json(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise DataError(f"Rosetta pack file {f.name} is unreadable: {exc}") from exc
            tasks.setdefault(task.slug, task)
    return tasks


def find_task(tasks: dict[str, Task], query: str) -> Task:
    q = slugify(query)
    if q in tasks:
        return tasks[q]
    hits = [t for s, t in tasks.items() if q and q in s]
    if len(hits) == 1:
        return hits[0]
    if not tasks:
        raise NoResultError(
            "No Rosetta pack found.",
            hint="Fetch one: `langsuite snippet --fetch` (saves tasks to your data dir).",
        )
    names = ", ".join(sorted(t.title for t in (hits or tasks.values()))[:8])
    raise NoResultError(f"No single Rosetta task matches `{query}`.", hint=f"Try one of: {names}.")


def _get(params: dict[str, str]) -> dict[str, Any]:
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
                data: dict[str, Any] = json.loads(r.read())
                return data
        except (OSError, ValueError) as exc:
            last = exc
            time.sleep(2**attempt)
    raise DataError(f"Rosetta Code fetch failed: {last}", hint="Check your network and retry.")


def fetch_task(title: str, resolve: Callable[[str], str | None] | None = None) -> Task:
    data = _get(
        {
            "action": "query",
            "titles": title,
            "meta": "siteinfo",
            "siprop": "rightsinfo",
            "prop": "revisions",
            "rvprop": "content|ids",
            "rvslots": "main",
            "format": "json",
            "formatversion": "2",
        }
    )
    pages = data.get("query", {}).get("pages", [])
    if not pages or "missing" in pages[0]:
        raise NoResultError(f"Rosetta Code has no task `{title}`.")
    page = pages[0]
    rev = page["revisions"][0]
    text = rev["slots"]["main"]["content"]
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rights = data.get("query", {}).get("rightsinfo", {})
    return Task(
        page["title"],
        int(rev["revid"]),
        now,
        parse_wikitext(text, resolve),
        str(rights.get("text", "")),
        str(rights.get("url", "")),
    )


def save_task(task: Task, dest: Path, langs: Iterable[str] | None = None) -> Path:
    if langs is not None:
        keep = set(langs)
        task = Task(
            task.title,
            task.revid,
            task.retrieved_at,
            {k: v for k, v in task.solutions.items() if k in keep},
            task.licence,
            task.licence_url,
        )
    tdir = dest / "tasks"
    tdir.mkdir(parents=True, exist_ok=True)
    out = tdir / f"{task.slug}.json"
    tmp = tdir / f".{uuid.uuid4().hex}.tmp"
    tmp.write_text(json.dumps(task.to_json(), indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    tmp.replace(out)
    return out
