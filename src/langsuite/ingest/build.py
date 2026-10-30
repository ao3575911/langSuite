"""Build a knowledge-base snapshot from PLDB + Linguist (SPEC §3, §10 M1).

The build is all-or-nothing: it writes to a temporary file and swaps it in only
when complete, so a failed or interrupted build never damages the current base.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langsuite.core import kb
from langsuite.core.errors import DataError
from langsuite.core.paths import base_dir, cache_dir, data_home
from langsuite.ingest import vocab
from langsuite.ingest.fetch import Fetched, fetch, from_file
from langsuite.ingest.parse import LinguistRecord, PldbRecord, parse_linguist, parse_pldb
from langsuite.ingest.sources import LINGUIST, PLDB, Source

BUILD_VERSION = 1

Progress = Callable[[str], None]


@dataclass
class _Lang:
    id: str
    name: str
    kind: str
    appeared: int | None = None
    website: str | None = None
    creators: str | None = None
    rank: int | None = None
    aliases: set[str] = field(default_factory=set)
    extensions: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)


def _bulk_insert(con: Any, table: str, rows: list[tuple[Any, ...]], folder: Path) -> None:
    """Load rows through a temporary JSON-lines file; far faster than executemany."""
    if not rows:
        return
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    spool = folder / f".{table}.jsonl"
    try:
        with spool.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(dict(zip(cols, row, strict=True)), ensure_ascii=False))
                fh.write("\n")
        types = {r[0]: r[1] for r in con.execute(f"DESCRIBE {table}").fetchall()}
        spec = "{" + ", ".join(f"'{c}': '{t}'" for c, t in types.items()) + "}"
        con.execute(
            f"INSERT INTO {table} SELECT * FROM read_json(?, format='newline_delimited', "  # noqa: S608 - fixed table names
            f"columns={spec})",
            [str(spool)],
        )
    finally:
        spool.unlink(missing_ok=True)


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9+#]+", "-", name.lower()).strip("-")
    return slug or "lang"


def _get(
    source: Source, home: Path, offline: bool, from_dir: Path | None, note: Progress
) -> Fetched:
    if from_dir is not None:
        got = from_file(source, from_dir / source.filename)
    else:
        got = fetch(source, cache_dir(home), offline=offline)
    detail = f" ({got.note})" if got.note else ""
    note(f"{source.title}: {len(got.data) / 2**20:.1f} MB from {got.origin}{detail}")
    return got


def build(
    *,
    home: Path | None = None,
    offline: bool = False,
    from_dir: Path | None = None,
    progress: Progress | None = None,
) -> kb.Manifest:
    home = home or data_home()
    note = progress or (lambda _msg: None)
    strict = from_dir is None
    pldb_raw = _get(PLDB, home, offline, from_dir, note)
    ling_raw = _get(LINGUIST, home, offline, from_dir, note)
    pldb = parse_pldb(pldb_raw.data, **({} if strict else {"min_records": 1}))
    ling = parse_linguist(ling_raw.data, **({} if strict else {"min_records": 1}))
    note(f"parsed {len(pldb)} PLDB and {len(ling)} Linguist records")
    return _write(home, pldb_raw, pldb, ling_raw, ling, note)


def _merge(
    pldb: list[PldbRecord], ling: list[LinguistRecord]
) -> tuple[dict[str, _Lang], dict[str, str]]:
    langs: dict[str, _Lang] = {}
    by_gh: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for r in pldb:
        langs[r.id] = _Lang(
            r.id,
            r.name,
            r.kind,
            r.appeared,
            r.website,
            r.creators,
            r.rank,
            set(r.aliases),
            {e.lstrip(".") for e in r.extensions},
            {"pldb"},
        )
        if r.github_language:
            by_gh.setdefault(r.github_language.lower(), r.id)
        by_name.setdefault(r.name.lower(), r.id)
    linguist_ids: dict[str, str] = {}
    for g in ling:
        key = g.name.lower()
        lid = by_gh.get(key) or by_name.get(key)
        if lid is None:
            lid = _slug(g.name)
            while lid in langs and "linguist" in langs[lid].sources:
                lid += "-1"
            if lid not in langs:
                langs[lid] = _Lang(lid, g.name, g.kind)
        lang = langs[lid]
        lang.sources.add("linguist")
        if g.name != lang.name:
            lang.aliases.add(g.name)
        lang.aliases.update(a for a in g.aliases if a.lower() != lang.name.lower())
        lang.extensions.update(g.extensions)
        linguist_ids[g.name] = lid
    return langs, linguist_ids


def _write(
    home: Path,
    pldb_raw: Fetched,
    pldb: list[PldbRecord],
    ling_raw: Fetched,
    ling: list[LinguistRecord],
    note: Progress,
) -> kb.Manifest:
    import duckdb

    langs, linguist_ids = _merge(pldb, ling)
    assertions: list[tuple[Any, ...]] = []
    features: dict[str, tuple[str, str, str, str, set[str]]] = {}

    def fact(fid: str, src: str) -> None:
        label, desc = vocab.FACTS[fid]
        features.setdefault(fid, (label, "Facts", "fact", desc, set()))[4].add(src)

    def add(lid: str, fid: str, value: str, got: Fetched, rid: str, path: str) -> None:
        url = got.source.record_url(rid)
        excerpt = f"{got.source.filename} > {rid} > {path}"
        assertions.append((lid, fid, value, got.source.key, url, excerpt, got.retrieved_at, 1.0))

    for r in pldb:
        p_fields: list[tuple[str, str, str | None]] = [
            ("appeared", "appeared", str(r.appeared) if r.appeared is not None else None),
            ("creators", "creators", r.creators),
            ("website", "website", r.website),
            ("kind", "primaryTag", r.kind),
            ("latest-version", "latestVersion", r.latest_version),
            ("extensions", "fileExtensions", " ".join(r.extensions) or None),
            ("aliases", "aka", " ".join(r.aliases) or None),
            ("influenced-by", "influencedBy", " ".join(r.influenced_by) or None),
        ]
        for fid, key, value in p_fields:
            if value:
                fact(fid, "pldb")
                add(r.id, fid, value, pldb_raw, r.id, f"{key}: {value}")
        for key, flag in r.traits.items():
            fid = vocab.trait_id(key)
            entry = features.setdefault(
                fid,
                (
                    vocab.trait_label(key),
                    vocab.trait_category(key),
                    "trait",
                    f"Whether the language has: {vocab.trait_label(key).lower()} (PLDB `{key}`).",
                    set(),
                ),
            )
            entry[4].add("pldb")
            add(r.id, fid, "yes" if flag else "no", pldb_raw, r.id, f"{key}: {str(flag).lower()}")

    for g in ling:
        lid = linguist_ids[g.name]
        l_fields = [
            ("kind", "type", g.kind),
            ("extensions", "extensions", " ".join(g.extensions)),
            ("aliases", "aliases", " ".join(g.aliases)),
            ("interpreters", "interpreters", " ".join(g.interpreters)),
        ]
        for fid, key, value in l_fields:
            if value:
                fact(fid, "linguist")
                add(lid, fid, value, ling_raw, g.name, f"{key}: {value}")

    edges = sorted(
        {
            (src, r.id, "influence", "pldb", PLDB.record_url(r.id))
            for r in pldb
            for src in r.influenced_by
            if src in langs and src != r.id
        }
    )

    digest = hashlib.sha256(
        f"{pldb_raw.sha256}:{ling_raw.sha256}:{vocab.VOCAB_VERSION}:{BUILD_VERSION}".encode()
    ).hexdigest()
    manifest = kb.Manifest(
        snapshot_id=f"base-{digest[:12]}",
        snapshot_hash=digest,
        built_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        vocab_version=vocab.VOCAB_VERSION,
        build_version=BUILD_VERSION,
        counts={
            "languages": len(langs),
            "features": len(features),
            "assertions": len(assertions),
            "edges": len(edges),
        },
        sources=[
            kb.SourceInfo(
                key=g.source.key,
                title=g.source.title,
                url=g.source.url,
                licence=g.source.licence,
                licence_url=g.source.licence_url,
                retrieved_at=g.retrieved_at,
                sha256=g.sha256,
                origin=g.origin,
            )
            for g in (pldb_raw, ling_raw)
        ],
    )

    target = base_dir(home)
    target.mkdir(parents=True, exist_ok=True)
    tmp = target / f".building-{digest[:12]}.duckdb"
    tmp.unlink(missing_ok=True)
    try:
        con = duckdb.connect(str(tmp))
        try:
            con.execute(kb.SCHEMA)
            lang_rows = [
                (
                    lang.id,
                    lang.name,
                    lang.kind,
                    lang.appeared,
                    lang.website,
                    lang.creators,
                    lang.rank,
                    sorted(lang.aliases),
                    sorted(lang.extensions),
                    sorted(lang.sources),
                )
                for lang in sorted(langs.values(), key=lambda x: x.id)
            ]
            feature_rows = [(fid, *v[:4], sorted(v[4])) for fid, v in sorted(features.items())]
            for table, rows in (
                ("languages", lang_rows),
                ("features", feature_rows),
                ("assertions", assertions),
                ("edges", edges),
            ):
                _bulk_insert(con, table, rows, target)
            con.execute("INSERT INTO meta VALUES ('manifest', ?)", [json.dumps(manifest.to_json())])
            con.execute("CHECKPOINT")
        finally:
            con.close()
        tmp.replace(target / kb.DB_NAME)
        (target / kb.MANIFEST_NAME).write_text(
            json.dumps(manifest.to_json(), indent=2, sort_keys=True), encoding="utf-8"
        )
    except duckdb.Error as err:
        raise DataError(f"Could not write the knowledge base: {err}.") from err
    finally:
        tmp.unlink(missing_ok=True)
        Path(f"{tmp}.wal").unlink(missing_ok=True)
    note(
        f"wrote {manifest.snapshot_id}: {len(langs)} languages, "
        f"{len(assertions)} assertions, {len(edges)} influence edges"
    )
    return manifest
