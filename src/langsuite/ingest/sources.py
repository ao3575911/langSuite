"""Upstream sources for the knowledge base, with their licences (SPEC §2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    url: str
    licence: str
    licence_url: str
    filename: str

    def record_url(self, record_id: str) -> str:
        if self.key == "pldb":
            return f"https://pldb.io/concepts/{record_id}.html"
        return LINGUIST_BLOB


LINGUIST_BLOB = "https://github.com/github-linguist/linguist/blob/main/lib/linguist/languages.yml"

PLDB = Source(
    key="pldb",
    title="PLDB",
    url="https://pldb.io/pldb.json",
    licence="Public domain",
    licence_url="https://github.com/breck7/pldb",
    filename="pldb.json",
)
LINGUIST = Source(
    key="linguist",
    title="GitHub Linguist",
    url="https://raw.githubusercontent.com/github-linguist/linguist/main/lib/linguist/languages.yml",
    licence="MIT",
    licence_url="https://github.com/github-linguist/linguist/blob/main/LICENSE",
    filename="languages.yml",
)
SOURCES: tuple[Source, ...] = (PLDB, LINGUIST)
