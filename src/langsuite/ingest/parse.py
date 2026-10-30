"""Parse upstream payloads into plain records, with validation and licence filtering.

Only allow-listed PLDB fields are read. Fields copied from Wikipedia or from
code-example sites under share-alike or unknown licences are never touched (SPEC §2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import yaml

from langsuite.core.errors import DataError
from langsuite.ingest.vocab import is_trait_key

PLDB_MIN_RECORDS = 1000
LINGUIST_MIN_RECORDS = 300


@dataclass
class PldbRecord:
    id: str
    name: str
    kind: str
    appeared: int | None
    creators: str | None
    website: str | None
    latest_version: str | None
    github_language: str | None
    extensions: list[str]
    aliases: list[str]
    influenced_by: list[str]
    rank: int | None
    traits: dict[str, bool] = field(default_factory=dict)


@dataclass
class LinguistRecord:
    name: str
    kind: str
    extensions: list[str]
    aliases: list[str]
    interpreters: list[str]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _words(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = _text(value)
    return text.split() if text else []


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _bad(source: str, why: str) -> DataError:
    return DataError(
        f"{source} data is not in the expected format ({why}).",
        hint="Upstream may have changed; your existing base was left untouched.",
    )


def parse_pldb(raw: bytes, min_records: int = PLDB_MIN_RECORDS) -> list[PldbRecord]:
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as err:
        raise _bad("PLDB", f"invalid JSON: {err}") from err
    if not isinstance(payload, list):
        raise _bad("PLDB", "top level is not a list")
    records: list[PldbRecord] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        rid = _text(item.get("id"))
        if not rid or rid in seen:
            continue
        seen.add(rid)
        traits = {k: v for k, v in item.items() if isinstance(v, bool) and is_trait_key(k)}
        aka = _text(item.get("aka"))
        records.append(
            PldbRecord(
                id=rid,
                name=_text(item.get("name")) or rid,
                kind=_text(item.get("primaryTag")) or _text(item.get("tags")) or "unknown",
                appeared=_int(item.get("appeared")),
                creators=_text(item.get("creators")),
                website=_text(item.get("website")),
                latest_version=_text(item.get("latestVersion")),
                github_language=_text(item.get("githubLanguage")),
                extensions=_words(item.get("fileExtensions")),
                aliases=[aka] if aka else [],
                influenced_by=_words(item.get("influencedBy")),
                rank=_int(item.get("rank")),
                traits=dict(sorted(traits.items())),
            )
        )
    if len(records) < min_records:
        raise _bad("PLDB", f"only {len(records)} records, expected at least {min_records}")
    return records


def parse_linguist(raw: bytes, min_records: int = LINGUIST_MIN_RECORDS) -> list[LinguistRecord]:
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as err:
        raise _bad("Linguist", f"invalid YAML: {err}") from err
    if not isinstance(payload, dict):
        raise _bad("Linguist", "top level is not a mapping")
    records = [
        LinguistRecord(
            name=str(name),
            kind=_text(info.get("type")) or "unknown",
            extensions=[e.lstrip(".") for e in _words(info.get("extensions"))],
            aliases=_words(info.get("aliases")),
            interpreters=_words(info.get("interpreters")),
        )
        for name, info in payload.items()
        if isinstance(info, dict)
    ]
    if len(records) < min_records:
        raise _bad("Linguist", f"only {len(records)} records, expected at least {min_records}")
    return records
