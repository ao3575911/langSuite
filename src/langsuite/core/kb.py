"""Read-side knowledge base: languages, features, assertions with provenance (SPEC §3).

The snapshot is a DuckDB file plus a JSON manifest. Reading is safe while a build
runs: builds swap the file in atomically.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langsuite.core.errors import DataError, NoResultError
from langsuite.core.paths import base_dir

if TYPE_CHECKING:
    from langsuite.core.similarity import TraitMatrix

DB_NAME = "current.duckdb"
MANIFEST_NAME = "manifest.json"
STALE_AFTER_DAYS = 30  # SPEC §2c freshness SLA for PLDB/Linguist

SCHEMA = """
CREATE TABLE languages (
    id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, kind VARCHAR, appeared INTEGER,
    website VARCHAR, creators VARCHAR, rank INTEGER,
    aliases VARCHAR[], extensions VARCHAR[], sources VARCHAR[]
);
CREATE TABLE features (
    id VARCHAR PRIMARY KEY, label VARCHAR NOT NULL, category VARCHAR NOT NULL,
    kind VARCHAR NOT NULL, description VARCHAR, sources VARCHAR[]
);
CREATE TABLE assertions (
    lang_id VARCHAR NOT NULL, feature_id VARCHAR NOT NULL, value VARCHAR NOT NULL,
    source VARCHAR NOT NULL, source_url VARCHAR NOT NULL, excerpt VARCHAR NOT NULL,
    retrieved_at VARCHAR NOT NULL, confidence DOUBLE NOT NULL
);
CREATE TABLE edges (
    src VARCHAR NOT NULL, dst VARCHAR NOT NULL, kind VARCHAR NOT NULL,
    source VARCHAR NOT NULL, source_url VARCHAR NOT NULL
);
CREATE TABLE meta (key VARCHAR PRIMARY KEY, value VARCHAR);
"""


@dataclass(frozen=True)
class SourceInfo:
    key: str
    title: str
    url: str
    licence: str
    licence_url: str
    retrieved_at: str
    sha256: str
    origin: str


@dataclass(frozen=True)
class Manifest:
    snapshot_id: str
    snapshot_hash: str
    built_at: str
    vocab_version: int
    build_version: int
    counts: dict[str, int]
    sources: list[SourceInfo] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Manifest:
        return cls(
            snapshot_id=str(data["snapshot_id"]),
            snapshot_hash=str(data["snapshot_hash"]),
            built_at=str(data["built_at"]),
            vocab_version=int(data["vocab_version"]),
            build_version=int(data["build_version"]),
            counts={str(k): int(v) for k, v in data["counts"].items()},
            sources=[SourceInfo(**s) for s in data.get("sources", [])],
        )

    def age_days(self, now: datetime | None = None) -> int:
        built = datetime.fromisoformat(self.built_at.replace("Z", "+00:00"))
        return max(0, ((now or datetime.now(UTC)) - built).days)

    @property
    def stale(self) -> bool:
        return self.age_days() > STALE_AFTER_DAYS


@dataclass(frozen=True)
class Language:
    id: str
    name: str
    kind: str
    appeared: int | None
    website: str | None
    creators: str | None
    rank: int | None
    aliases: tuple[str, ...]
    extensions: tuple[str, ...]
    sources: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Feature:
    id: str
    label: str
    category: str
    kind: str
    description: str
    sources: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Assertion:
    lang_id: str
    feature_id: str
    value: str
    source: str
    source_url: str
    excerpt: str
    retrieved_at: str
    confidence: float

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def evidence_id(self) -> str:
        """Stable id for citing this assertion from a finding."""
        key = "\x1f".join((self.lang_id, self.feature_id, self.value, self.source, self.source_url))
        return "ev-" + hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    kind: str
    source: str
    source_url: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Overlay:
    """A workspace's own data, layered over the shared base (SPEC §6, §10 M3)."""

    languages: tuple[Language, ...] = ()
    assertions: tuple[Assertion, ...] = ()
    edges: tuple[Edge, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.languages or self.assertions or self.edges)

    def to_json(self) -> dict[str, Any]:
        return {
            "languages": [x.to_json() for x in self.languages],
            "assertions": [x.to_json() for x in self.assertions],
            "edges": [x.to_json() for x in self.edges],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Overlay:
        def lang(d: dict[str, Any]) -> Language:
            for key in ("aliases", "extensions", "sources"):
                d = {**d, key: tuple(d.get(key) or ())}
            return Language(**d)

        return cls(
            languages=tuple(lang(d) for d in data.get("languages", [])),
            assertions=tuple(Assertion(**d) for d in data.get("assertions", [])),
            edges=tuple(Edge(**d) for d in data.get("edges", [])),
        )


def snapshots_dir(home: Path | None = None) -> Path:
    return base_dir(home) / "snapshots"


def kept_snapshots(home: Path | None = None) -> list[Manifest]:
    """Snapshots kept on this machine, newest first."""
    out: list[Manifest] = []
    folder = snapshots_dir(home)
    if not folder.is_dir():
        return out
    for path in folder.iterdir():
        try:
            out.append(
                Manifest.from_json(json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8")))
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(out, key=lambda m: (m.built_at, m.snapshot_id), reverse=True)


def retain_snapshot(home: Path | None, manifest: Manifest) -> None:
    """Keep an immutable copy of the current snapshot so old findings stay reproducible."""
    import os
    import shutil

    folder = snapshots_dir(home) / manifest.snapshot_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / DB_NAME
    if not target.is_file():
        source = base_dir(home) / DB_NAME
        try:
            os.link(source, target)
        except OSError:
            shutil.copyfile(source, target)
    (folder / MANIFEST_NAME).write_text(
        json.dumps(manifest.to_json(), indent=2, sort_keys=True), encoding="utf-8"
    )


def prune_snapshots(home: Path | None, keep: int, pinned: set[str]) -> list[str]:
    """Drop old unpinned snapshots beyond the newest `keep`. Returns the dropped ids."""
    import shutil

    current = read_manifest(home)
    dropped: list[str] = []
    for n, m in enumerate(kept_snapshots(home)):
        sid = m.snapshot_id
        if n < keep or sid in pinned or (current and sid == current.snapshot_id):
            continue
        shutil.rmtree(snapshots_dir(home) / sid, ignore_errors=True)
        dropped.append(sid)
    return dropped


def no_base_error() -> DataError:
    return DataError(
        "No knowledge base yet.",
        hint="Run `langsuite base build` (about 11 MB download, under a minute).",
    )


def read_manifest(home: Path | None = None) -> Manifest | None:
    """Cheap manifest read for status lines; None when there is no usable base."""
    path = base_dir(home) / MANIFEST_NAME
    try:
        return Manifest.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _norm(text: str) -> str:
    return text.strip().lower().lstrip(".")


def _subsequence(needle: str, hay: str) -> bool:
    it = iter(hay)
    return all(ch in it for ch in needle)


class KnowledgeBase:
    """A read-only view of the current snapshot."""

    def __init__(
        self,
        home: Path | None = None,
        *,
        snapshot: str | None = None,
        overlay: Overlay | None = None,
    ) -> None:
        import duckdb

        self._trait_matrix: TraitMatrix | None = None
        self.home = home
        self.overlay = overlay or Overlay()
        folder = base_dir(home)
        db = folder / DB_NAME
        if not db.is_file():
            raise no_base_error()
        if snapshot is not None:
            current = read_manifest(home)
            if current is None or current.snapshot_id != snapshot:
                db = snapshots_dir(home) / snapshot / DB_NAME
                if not db.is_file():
                    raise DataError(
                        f"Snapshot {snapshot} is not kept on this machine.",
                        hint="See `langsuite base snapshots`; pinned snapshots are never pruned.",
                    )
        try:
            self._con = duckdb.connect(str(db), read_only=True)
            row = self._con.execute("SELECT value FROM meta WHERE key = 'manifest'").fetchone()
            if row is None:
                raise DataError("The knowledge base has no manifest.")
            self.manifest = Manifest.from_json(json.loads(row[0]))
        except (duckdb.Error, ValueError, KeyError, TypeError) as err:
            raise DataError(
                f"The knowledge base at {db} is damaged ({type(err).__name__}).",
                hint="Rebuild it with `langsuite base build`.",
            ) from err

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> KnowledgeBase:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _rows(self, sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        return self._con.execute(sql, params or []).fetchall()

    # ----- languages ---------------------------------------------------------

    @cached_property
    def languages(self) -> list[Language]:
        return self._base_languages() + sorted(self.overlay.languages, key=lambda x: x.name)

    def _base_languages(self) -> list[Language]:
        rows = self._rows(
            "SELECT id, name, kind, appeared, website, creators, rank, aliases, extensions, "
            "sources FROM languages ORDER BY rank NULLS LAST, name"
        )
        return [
            Language(
                id=r[0],
                name=r[1],
                kind=r[2],
                appeared=r[3],
                website=r[4],
                creators=r[5],
                rank=r[6],
                aliases=tuple(r[7] or ()),
                extensions=tuple(r[8] or ()),
                sources=tuple(r[9] or ()),
            )
            for r in rows
        ]

    @cached_property
    def _by_id(self) -> dict[str, Language]:
        return {lang.id: lang for lang in self.languages}

    @cached_property
    def _keys(self) -> list[tuple[Language, str, str, tuple[str, ...], tuple[str, ...]]]:
        return [
            (
                lang,
                lang.id.lower(),
                lang.name.lower(),
                tuple(a.lower() for a in lang.aliases),
                tuple(e.lower() for e in lang.extensions),
            )
            for lang in self.languages
        ]

    def language(self, lang_id: str) -> Language | None:
        return self._by_id.get(lang_id)

    def search(self, query: str, limit: int | None = 50) -> list[Language]:
        """Rank by exact id/name/alias/extension, then prefix, word, substring, fuzzy."""
        q = _norm(query)
        if not q:
            return self.languages[:limit] if limit else list(self.languages)
        scored: list[tuple[int, int, Language]] = []
        for pos, (lang, lid, name, aliases, exts) in enumerate(self._keys):
            if q in (lid, name):
                score = 100
            elif q in aliases or q in exts:
                score = 90
            elif name.startswith(q) or lid.startswith(q):
                score = 80
            elif any(w.startswith(q) for w in re.split(r"[\s\-_/]+", name)):
                score = 70
            elif any(a.startswith(q) for a in aliases):
                score = 65
            elif q in name or q in lid:
                score = 50
            elif len(q) > 2 and _subsequence(q, name):
                score = 20
            else:
                continue
            scored.append((-score, pos, lang))
        scored.sort(key=lambda t: (t[0], t[1]))
        hits = [lang for _, _, lang in scored]
        return hits[:limit] if limit else hits

    def suggest(self, query: str, n: int = 3) -> list[str]:
        names = {lang.name.lower(): lang.name for lang in self.languages}
        names.update({lang.id: lang.id for lang in self.languages})
        close = difflib.get_close_matches(_norm(query), list(names), n=n, cutoff=0.6)
        return list(dict.fromkeys(names[c] for c in close))

    def resolve(self, query: str) -> Language:
        """Exact id, name, alias or extension; otherwise a helpful not-found error."""
        q = _norm(query)
        ext_only = query.strip().startswith(".")
        if not ext_only:
            for lang, lid, name, _aliases, _exts in self._keys:
                if q in (lid, name):
                    return lang
        for lang, _lid, _name, aliases, exts in self._keys:
            if q in exts or (not ext_only and q in aliases):
                return lang
        hint = None
        options = self.suggest(query)
        if options:
            hint = "Did you mean " + ", ".join(f"`{o}`" for o in options) + "?"
        else:
            hint = "Search with `langsuite lang list <text>`."
        raise NoResultError(f"No language matches `{query}`.", hint=hint)

    # ----- features and assertions ------------------------------------------

    @cached_property
    def features(self) -> list[Feature]:
        rows = self._rows(
            "SELECT id, label, category, kind, description, sources FROM features "
            "ORDER BY kind DESC, category, id"
        )
        return [
            Feature(
                id=r[0],
                label=r[1],
                category=r[2],
                kind=r[3],
                description=r[4] or "",
                sources=tuple(r[5] or ()),
            )
            for r in rows
        ]

    def resolve_feature(self, query: str) -> Feature:
        q = _norm(query).replace(" ", "-").replace("_", "-")
        compact = q.replace("-", "")
        for feat in self.features:
            if q == feat.id or compact == feat.id.replace("-", ""):
                return feat
            if q == feat.label.lower().replace(" ", "-"):
                return feat
        partial = [f.id for f in self.features if q in f.id]
        if len(partial) == 1:
            return next(f for f in self.features if f.id == partial[0])
        close = partial[:5] or difflib.get_close_matches(
            q, [f.id for f in self.features], n=3, cutoff=0.6
        )
        hint = (
            "Did you mean " + ", ".join(f"`{c}`" for c in close) + "?"
            if close
            else "See `langsuite feature list`."
        )
        raise NoResultError(f"No feature matches `{query}`.", hint=hint)

    def assertions(self, lang_id: str) -> list[Assertion]:
        rows = self._rows(
            "SELECT * FROM assertions WHERE lang_id = ? ORDER BY feature_id, source", [lang_id]
        )
        extra = [a for a in self.overlay.assertions if a.lang_id == lang_id]
        out = [Assertion(*r) for r in rows] + extra
        return sorted(out, key=lambda a: (a.feature_id, a.source)) if extra else out

    def feature_counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        for fid, value, n in self._rows(
            "SELECT feature_id, value, count(DISTINCT lang_id) FROM assertions "
            "WHERE value IN ('yes', 'no') GROUP BY ALL"
        ):
            counts.setdefault(fid, {})[value] = n
        seen = {(a.lang_id, a.feature_id, a.value) for a in self.overlay.assertions}
        for lang, fid, value in sorted(seen):
            if value in ("yes", "no") and not self._base_has(lang, fid, value):
                bucket = counts.setdefault(fid, {})
                bucket[value] = bucket.get(value, 0) + 1
        return counts

    def _base_has(self, lang: str, fid: str, value: str) -> bool:
        return bool(
            self._rows(
                "SELECT 1 FROM assertions WHERE lang_id = ? AND feature_id = ? AND value = ? "
                "LIMIT 1",
                [lang, fid, value],
            )
        )

    def languages_with(self, feature_id: str, value: str = "yes") -> list[Language]:
        ids = {
            r[0]
            for r in self._rows(
                "SELECT DISTINCT lang_id FROM assertions WHERE feature_id = ? AND value = ?",
                [feature_id, value],
            )
        }
        ids |= {
            a.lang_id
            for a in self.overlay.assertions
            if a.feature_id == feature_id and a.value == value
        }
        return [lang for lang in self.languages if lang.id in ids]

    def edges(self, lang_id: str) -> tuple[list[Edge], list[Edge]]:
        """(influenced by, influenced) for a language."""
        rows = [
            Edge(*r)
            for r in self._rows(
                "SELECT * FROM edges WHERE src = ? OR dst = ? ORDER BY src, dst", [lang_id, lang_id]
            )
        ]
        rows += [e for e in self.overlay.edges if lang_id in (e.src, e.dst)]
        return [e for e in rows if e.dst == lang_id], [e for e in rows if e.src == lang_id]

    # ----- similarity inputs (M2) ---------------------------------------------

    def trait_pairs(self) -> list[tuple[str, str]]:
        """(language, trait) for every trait a source asserts the language has."""
        rows = self._rows(
            "SELECT DISTINCT a.lang_id, a.feature_id FROM assertions a "
            "JOIN features f ON f.id = a.feature_id "
            "WHERE f.kind = 'trait' AND a.value = 'yes' ORDER BY 1, 2"
        )
        pairs = {(str(r[0]), str(r[1])) for r in rows}
        traits = self._trait_ids
        pairs |= {
            (a.lang_id, a.feature_id)
            for a in self.overlay.assertions
            if a.value == "yes" and a.feature_id in traits
        }
        return sorted(pairs)

    @cached_property
    def _trait_ids(self) -> frozenset[str]:
        return frozenset(f.id for f in self.features if f.kind == "trait")

    @cached_property
    def _trait_values(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for lang, fid, value in self._rows(
            "SELECT DISTINCT a.lang_id, a.feature_id, a.value FROM assertions a "
            "JOIN features f ON f.id = a.feature_id "
            "WHERE f.kind = 'trait' AND a.value IN ('yes', 'no') ORDER BY 1, 2, 3"
        ):
            feats = out.setdefault(str(lang), {})
            # any source saying "yes" wins; conflicts stay visible in the evidence
            if feats.get(str(fid)) != "yes":
                feats[str(fid)] = str(value)
        for a in self.overlay.assertions:
            if a.feature_id in self._trait_ids and a.value in ("yes", "no"):
                feats = out.setdefault(a.lang_id, {})
                if feats.get(a.feature_id) != "yes":
                    feats[a.feature_id] = a.value
        return dict(sorted(out.items()))

    def trait_values(self) -> dict[str, dict[str, str]]:
        """language → trait → "yes" | "no" (absent = unknown)."""
        return self._trait_values

    def trait_matrix(self) -> TraitMatrix:
        if self._trait_matrix is None:
            from langsuite.core.similarity import TraitMatrix

            self._trait_matrix = TraitMatrix.from_kb(self)
        return self._trait_matrix
