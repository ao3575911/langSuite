"""Official docs: ingest with ETag/hash, quote verbatim, and track dead links (SPEC M5f).

Pages are split into sections at headings that carry an `id`, so every quote has a
link with an anchor. A page whose ETag (or, without one, content hash) is unchanged
is skipped. A page that keeps failing is flagged, then archived after
`ARCHIVE_AFTER_DAYS` with at least `FAIL_LIMIT` failures, and stays readable.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from importlib import resources
from pathlib import Path
from typing import Any, ClassVar

import yaml

from langsuite.core.errors import NoResultError
from langsuite.core.paths import data_home

FAIL_LIMIT = 3
ARCHIVE_AFTER_DAYS = 14
SHORT_EXCERPT = 200  # UNKNOWN licence: short excerpt plus link only
LONG_EXCERPT = 1200
METHOD = "docs/1"


@dataclass
class Fetch:
    status: int  # 200, 304, or an error status (0 for network errors)
    etag: str | None = None
    body: str = ""


Fetcher = Callable[[str, str | None], Fetch]


def http_fetch(url: str, etag: str | None) -> Fetch:  # pragma: no cover - network
    from langsuite.ingest.fetch import USER_AGENT

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    if etag:
        req.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - https only, below
            body = resp.read(4_000_000).decode("utf-8", "replace")
            return Fetch(resp.status, resp.headers.get("ETag"), body)
    except urllib.error.HTTPError as err:
        return Fetch(err.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return Fetch(0)


def sources() -> dict[str, Any]:
    text = resources.files("langsuite.core.data").joinpath("docs_sources.yaml").read_text("utf-8")
    data: dict[str, Any] = yaml.safe_load(text)
    return data


class _Sections(HTMLParser):
    SKIP: ClassVar[set[str]] = {"script", "style", "nav", "header", "footer", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict[str, str]] = [{"anchor": "", "title": "", "text": ""}]
        self._skip = 0
        self._heading: str | None = None
        self._pending_id = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        elif re.fullmatch(r"h[1-4]", tag):
            self._heading = ""
            self._pending_id = a.get("id") or ""
        elif tag == "a" and self._heading is not None and not self._pending_id:
            self._pending_id = a.get("id") or a.get("name") or ""
        elif tag == "section" and a.get("id"):
            self._pending_id = a.get("id") or ""
        elif tag in ("p", "li", "pre", "br", "div", "dd", "dt"):
            self.sections[-1]["text"] += "\n"

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif re.fullmatch(r"h[1-4]", tag) and self._heading is not None:
            title = " ".join(self._heading.replace("¶", "").split())
            self.sections.append({"anchor": self._pending_id, "title": title, "text": ""})
            self._heading = None
            self._pending_id = ""

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._heading is not None:
            self._heading += data
        else:
            self.sections[-1]["text"] += data


def sections(html: str) -> list[dict[str, str]]:
    p = _Sections()
    p.feed(html)
    out = []
    for s in p.sections:
        text = re.sub(r"[ \t]+", " ", s["text"])
        text = re.sub(r"\s*\n\s*", "\n", text).strip()
        if text or s["title"]:
            out.append({**s, "text": text})
    return out


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def store_path(lang: str, home: Path | None = None) -> Path:
    return (home or data_home()) / "docs" / f"{lang}.json"


def load(lang: str, home: Path | None = None) -> dict[str, Any]:
    path = store_path(lang, home)
    if not path.is_file():
        return {"lang": lang, "pages": {}}
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _save(lang: str, data: dict[str, Any], home: Path | None) -> None:
    path = store_path(lang, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def ingest(
    lang: str,
    *,
    fetch: Fetcher = http_fetch,
    home: Path | None = None,
    now: datetime | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Fetch LANG's pages; re-ingest only those that changed. Returns url lists per outcome."""
    cfg = cfg if cfg is not None else sources()
    if lang not in cfg:
        raise NoResultError(
            f"No official docs registered for `{lang}`.",
            hint=f"Registered: {', '.join(sorted(cfg))}.",
        )
    entry = cfg[lang]
    now = now or _now()
    data = load(lang, home)
    data.update(
        version=str(entry.get("version", "")),
        licence=entry.get("licence", "UNKNOWN"),
        licence_url=entry.get("licence_url", ""),
    )
    report: dict[str, list[str]] = {"changed": [], "unchanged": [], "failed": [], "archived": []}
    for url in entry.get("pages", []):
        if not str(url).startswith("https://"):
            continue
        page = data["pages"].setdefault(url, {"fails": 0})
        got = fetch(url, page.get("etag"))
        if got.status == 304:
            page.update(fails=0, first_fail=None, last_ok=_iso(now))
            report["unchanged"].append(url)
            continue
        if got.status != 200:
            page["fails"] = int(page.get("fails", 0)) + 1
            page["first_fail"] = page.get("first_fail") or _iso(now)
            first = datetime.fromisoformat(page["first_fail"].replace("Z", "+00:00"))
            if page["fails"] >= FAIL_LIMIT and now - first >= timedelta(days=ARCHIVE_AFTER_DAYS):
                page["archived"] = True
                report["archived"].append(url)
            else:
                report["failed"].append(url)
            page["last_status"] = got.status
            continue
        digest = hashlib.sha256(got.body.encode("utf-8")).hexdigest()
        page.update(
            fails=0,
            first_fail=None,
            last_ok=_iso(now),
            etag=got.etag,
            archived=False,
            last_status=200,
        )
        if page.get("sha256") == digest:
            report["unchanged"].append(url)
            continue
        page.update(sha256=digest, fetched_at=_iso(now), sections=sections(got.body))
        report["changed"].append(url)
    _save(lang, data, home)
    return report


def status(lang: str, home: Path | None = None) -> list[dict[str, Any]]:
    rows = []
    for url, p in sorted(load(lang, home)["pages"].items()):
        state = "archived" if p.get("archived") else "failing" if p.get("fails") else "ok"
        if "sections" not in p and state == "ok":
            state = "not fetched"
        rows.append(
            {
                "url": url,
                "state": state,
                "fails": p.get("fails", 0),
                "last_ok": p.get("last_ok"),
                "readable": "sections" in p,
            }
        )
    return rows


def _terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) > 1]


@dataclass
class Quote:
    lang: str
    url: str
    title: str
    version: str
    licence: str
    licence_url: str
    text: str
    truncated: bool
    archived: bool
    fetched_at: str

    def to_json(self) -> dict[str, Any]:
        return {**self.__dict__, "method": METHOD, "verbatim": True}


def search(
    query: str, lang: str | None = None, home: Path | None = None, limit: int = 5
) -> list[Quote]:
    """Best-matching sections; each quote is a verbatim slice of the stored page text."""
    terms = set(_terms(query))
    if not terms:
        return []
    langs = [lang] if lang else sorted(sources())
    scored: list[tuple[float, Quote]] = []
    for name in langs:
        data = load(name, home)
        unknown = data.get("licence", "UNKNOWN") == "UNKNOWN"
        cap = SHORT_EXCERPT if unknown else LONG_EXCERPT
        for url, page in data["pages"].items():
            for s in page.get("sections", []):
                words = _terms(s["title"] + " " + s["text"])
                if not words:
                    continue
                hits = sum(words.count(t) for t in terms)
                cover = sum(1 for t in terms if t in words)
                if not cover:
                    continue
                score = cover * 10 + hits / (1 + len(words) / 200)
                text = _excerpt(s["text"], terms, cap)
                link = f"{url}#{s['anchor']}" if s["anchor"] else url
                scored.append(
                    (
                        score,
                        Quote(
                            name,
                            link,
                            s["title"],
                            data.get("version", ""),
                            data.get("licence", "UNKNOWN"),
                            data.get("licence_url", ""),
                            text,
                            len(text) < len(s["text"]),
                            bool(page.get("archived")),
                            page.get("fetched_at", ""),
                        ),
                    )
                )
    scored.sort(key=lambda x: (-x[0], x[1].url))
    return [q for _, q in scored[:limit]]


def _excerpt(text: str, terms: set[str], cap: int) -> str:
    """A verbatim window of TEXT around the first paragraph that mentions a term."""
    paras = text.split("\n")
    start = 0
    for i, p in enumerate(paras):
        if any(t in _terms(p) for t in terms):
            start = i
            break
    out = "\n".join(paras[start:])
    if len(out) <= cap:
        return out
    cut = out[:cap]
    stop = max(cut.rfind(". "), cut.rfind("\n"))
    return cut[: stop + 1].rstrip() if stop > cap // 3 else cut.rstrip()
