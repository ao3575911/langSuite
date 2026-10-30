"""Read-side knowledge base: languages, features, assertions with provenance (SPEC §3).

The snapshot is a DuckDB file plus a JSON manifest. Reading is safe while a build
runs: builds swap the file in atomically.
"""

from __future__ import annotations

import difflib
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


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    kind: str
    source: str
    source_url: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def no_base_error() -> DataError:
    return DataError(
        "No knowledge base yet.",
        hint="Run `langsuite base build` (about 15 MB download, under a minute).",
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

    def __init__(self, home: Path | None = None) -> None:
        import duckdb

        self._trait_matrix: TraitMatrix | None = None
        folder = base_dir(home)
        db = folder / DB_NAME
        if not db.is_file():
            raise no_base_error()
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
        return [Assertion(*r) for r in rows]

    def feature_counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        for fid, value, n in self._rows(
            "SELECT feature_id, value, count(DISTINCT lang_id) FROM assertions "
            "WHERE value IN ('yes', 'no') GROUP BY ALL"
        ):
            counts.setdefault(fid, {})[value] = n
        return counts

    def languages_with(self, feature_id: str, value: str = "yes") -> list[Language]:
        ids = {
            r[0]
            for r in self._rows(
                "SELECT DISTINCT lang_id FROM assertions WHERE feature_id = ? AND value = ?",
                [feature_id, value],
            )
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
        return [e for e in rows if e.dst == lang_id], [e for e in rows if e.src == lang_id]

    # ----- similarity inputs (M2) ---------------------------------------------

    def trait_pairs(self) -> list[tuple[str, str]]:
        """(language, trait) for every trait a source asserts the language has."""
        rows = self._rows(
            "SELECT DISTINCT a.lang_id, a.feature_id FROM assertions a "
            "JOIN features f ON f.id = a.feature_id "
            "WHERE f.kind = 'trait' AND a.value = 'yes' ORDER BY 1, 2"
        )
        return [(str(r[0]), str(r[1])) for r in rows]

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
        return out

    def trait_values(self) -> dict[str, dict[str, str]]:
        """language → trait → "yes" | "no" (absent = unknown)."""
        return self._trait_values

    def trait_matrix(self) -> TraitMatrix:
        if self._trait_matrix is None:
            from langsuite.core.similarity import TraitMatrix

            self._trait_matrix = TraitMatrix.from_kb(self)
        return self._trait_matrix
