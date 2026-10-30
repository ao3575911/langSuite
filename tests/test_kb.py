"""Knowledge base: ingest, provenance, lookup and CLI (SPEC §3, §10 M1)."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from langsuite.cli.app import main
from langsuite.core.errors import DataError, NoResultError
from langsuite.core.kb import KnowledgeBase, Manifest, read_manifest
from langsuite.ingest import fetch as fetch_mod
from langsuite.ingest import vocab
from langsuite.ingest.build import build
from langsuite.ingest.parse import parse_linguist, parse_pldb
from langsuite.ingest.sources import PLDB, Source

FIXTURES = Path(__file__).parent / "fixtures" / "kb"


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    try:
        main(args)
        code = 0
    except SystemExit as exc:
        code = int(exc.code or 0)
    out = capsys.readouterr()
    return code, out.out, out.err


# ----- build and provenance ----------------------------------------------------


def test_every_assertion_has_source_and_time(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        rows = [a for lang in kb.languages for a in kb.assertions(lang.id)]
        assert rows
        for a in rows:
            assert a.source in {"pldb", "linguist"}
            assert a.source_url.startswith("https://")
            assert a.retrieved_at.endswith("Z")
            assert a.excerpt


def test_merge_joins_linguist_to_pldb(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        haskell = kb.resolve("haskell")
        assert haskell.sources == ("linguist", "pldb")
        assert "hs" in haskell.extensions
        assert kb.resolve("Nix").sources == ("linguist",)  # Linguist-only language kept


def test_share_alike_fields_never_ingested(kb_home: Path) -> None:
    db = (kb_home / "base" / "current.duckdb").read_bytes()
    assert b"SHOULD NOT BE INGESTED" not in db


def test_conflicting_values_kept_side_by_side(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        ext = [a for a in kb.assertions("haskell") if a.feature_id == "extensions"]
        assert {a.source for a in ext} == {"pldb", "linguist"}


def test_influence_edges(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        parents, _ = kb.edges("haskell")
        assert {e.src for e in parents} >= {"miranda", "ml"}


def test_build_is_deterministic(tmp_path: Path, kb_home: Path) -> None:
    again = build(home=tmp_path / "again", from_dir=FIXTURES)
    first = read_manifest(kb_home)
    assert first is not None
    assert again.snapshot_id == first.snapshot_id
    assert again.counts == first.counts


def test_failed_build_keeps_old_base(tmp_path: Path) -> None:
    home = tmp_path / "h"
    good = build(home=home, from_dir=FIXTURES)
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "pldb.json").write_text("{not json", encoding="utf-8")
    (bad / "languages.yml").write_bytes((FIXTURES / "languages.yml").read_bytes())
    with pytest.raises(DataError, match="PLDB data is not in the expected format"):
        build(home=home, from_dir=bad)
    with KnowledgeBase(home) as kb:
        assert kb.manifest.snapshot_id == good.snapshot_id


def test_missing_from_file(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="Cannot read PLDB"):
        build(home=tmp_path, from_dir=tmp_path)


def test_damaged_base(tmp_path: Path) -> None:
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "current.duckdb").write_bytes(b"garbage" * 100)
    with pytest.raises(DataError, match="damaged"):
        KnowledgeBase(tmp_path)


def test_manifest_age_and_stale() -> None:
    m = Manifest("base-x", "x", "2000-01-01T00:00:00Z", 1, 1, {})
    assert m.age_days() > 365
    assert m.stale


# ----- parse validation -------------------------------------------------------


@pytest.mark.parametrize("raw", [b"{}", b"[]", b"nope"])
def test_parse_pldb_rejects_bad(raw: bytes) -> None:
    with pytest.raises(DataError):
        parse_pldb(raw)


@pytest.mark.parametrize("raw", [b"- a", b"x: [", b"{}"])
def test_parse_linguist_rejects_bad(raw: bytes) -> None:
    with pytest.raises(DataError):
        parse_linguist(raw)


def test_parse_pldb_skips_junk() -> None:
    raw = json.dumps([1, {"id": ""}, {"id": "a"}, {"id": "a"}, {"id": "b", "appeared": "x"}])
    recs = parse_pldb(raw.encode(), min_records=1)
    assert [r.id for r in recs] == ["a", "b"]
    assert recs[1].appeared is None


def test_vocab_ids() -> None:
    assert vocab.trait_id("hasTypeInference") == "type-inference"
    assert vocab.trait_id("isCaseSensitive") == "case-sensitive"
    assert vocab.trait_id("hasUTF8Strings") == "utf8-strings"
    assert vocab.trait_category("hasLazyEvaluation") == "Evaluation"
    assert vocab.trait_category("hasStaticTyping") == "Types"
    assert vocab.trait_category("hasZzz") == "Other"
    assert not vocab.is_trait_key("isLanguage")
    with pytest.raises(ValueError, match="nope"):
        vocab.trait_id("nope")


# ----- lookup -----------------------------------------------------------------


def test_resolve_by_alias_extension_and_suggest(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        assert kb.resolve("HASKELL").id == "haskell"
        assert kb.resolve(".hs").id == "haskell"
        assert kb.resolve(".py").id == "python"  # extension beats the PLDB id `py`
        assert kb.resolve("python3").id == "python"  # Linguist alias
        with pytest.raises(NoResultError) as err:
            kb.resolve("haskel")
        assert "haskell" in (err.value.hint or "")


def test_search_ranking(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        assert kb.search("hask")[0].id == "haskell"
        assert kb.search("")[:1]
        assert kb.search("zzzz") == []
        assert kb.search("hsk", limit=None)[0].id == "haskell"  # fuzzy subsequence


def test_feature_resolution(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        assert kb.resolve_feature("Type inference").id == "type-inference"
        assert kb.resolve_feature("typeinference").id == "type-inference"
        with pytest.raises(NoResultError):
            kb.resolve_feature("qqq")


# ----- CLI --------------------------------------------------------------------


def test_cli_show_evidence_lists_sources(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--plain", "lang", "show", "haskell", "--evidence"], capsys)
    assert code == 0
    assert "Haskell" in out
    assert "https://pldb.io/concepts/haskell.html" in out
    assert "languages.yml" in out
    assert "Public domain" in out and "MIT" in out


def test_cli_show_json(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--json", "lang", "show", "hs"], capsys)
    data = json.loads(out)
    assert code == 0 and data["kind"] == "language"
    assert data["data"]["language"]["id"] == "haskell"
    assert all(a["retrieved_at"] for a in data["data"]["assertions"])


@pytest.mark.parametrize("mode", ["concise", "default", "thorough"])
def test_cli_show_modes(kb_home: Path, capsys: pytest.CaptureFixture[str], mode: str) -> None:
    code, out, _ = run(["--plain", "-m", mode, "lang", "show", "haskell"], capsys)
    assert code == 0
    assert ("Sources" in out) == (mode == "thorough")


def test_cli_not_found_suggests(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(["--plain", "lang", "show", "haskel"], capsys)
    assert code == 2
    assert "Did you mean `haskell`" in err


def test_cli_no_base(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(["--plain", "lang", "list"], capsys)
    assert code == 3
    assert "langsuite base build" in err
    code, _, err = run(["base", "status"], capsys)
    assert code == 3


def test_cli_list_filters(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--json", "lang", "list", "--kind", "pl", "-n", "0"], capsys)
    data = json.loads(out)["data"]
    assert code == 0 and data["total"] >= 5
    code, out, _ = run(["--plain", "-m", "concise", "l", "list", "-f", "type-inference"], capsys)
    assert code == 0 and "haskell" in out
    code, _, _ = run(["--plain", "lang", "list", "zzzz"], capsys)
    assert code == 2


def test_cli_features(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--plain", "feature", "list"], capsys)
    assert code == 0 and "type-inference" in out
    code, out, _ = run(["--json", "ft", "list", "--all"], capsys)
    assert any(i["kind"] == "fact" for i in json.loads(out)["data"]["items"])
    code, out, _ = run(["--plain", "feature", "list", "-c", "types"], capsys)
    assert code == 0
    code, _, err = run(["--plain", "feature", "list", "-c", "nope"], capsys)
    assert code == 2 and "Categories" in err
    code, out, _ = run(["--plain", "feature", "show", "type-inference", "-n", "1"], capsys)
    assert code == 0 and "Yes" in out
    code, out, _ = run(["--json", "feature", "show", "type-inference"], capsys)
    assert "haskell" in json.loads(out)["data"]["yes"]
    code, out, _ = run(["--plain", "feature", "show", "appeared"], capsys)
    assert "Descriptive fact" in out


def test_cli_base_build_and_status(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--plain", "base", "build", "--from", str(FIXTURES)], capsys)
    assert code == 0 and "Built base-" in out
    code, out, _ = run(["--plain", "base", "status"], capsys)
    assert code == 0 and "PLDB" in out and "fresh" in out
    code, out, _ = run(["--json", "b", "status"], capsys)
    assert json.loads(out)["data"]["age_days"] == 0
    code, out, _ = run(["--json", "base", "build", "--from", str(FIXTURES)], capsys)
    assert json.loads(out)["data"]["log"]
    code, _, err = run(["--plain", "base", "pull"], capsys)
    assert code == 2  # SOURCE is now a required argument


def test_cli_offline_without_cache(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(["--plain", "base", "build", "--offline"], capsys)
    assert code == 3 and "No cached copy" in err


# ----- fetch ------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    body = b"[]"
    plan: ClassVar[list[int]] = []
    seen: ClassVar[list[dict[str, str]]] = []

    def do_GET(self) -> None:
        type(self).seen.append(dict(self.headers))
        status = type(self).plan.pop(0) if type(self).plan else 200
        if status == 200 and self.headers.get("If-None-Match") == '"v1"':
            status = 304
        self.send_response(status)
        if status == 200:
            self.send_header("ETag", '"v1"')
            self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        if status == 200:
            self.wfile.write(self.body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def server() -> Iterator[Source]:
    _Handler.plan, _Handler.seen = [], []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    yield Source("pldb", "Test", f"http://127.0.0.1:{port}/x", "PD", "", "t.json")
    httpd.shutdown()


def test_fetch_caches_and_revalidates(server: Source, tmp_path: Path) -> None:
    first = fetch_mod.fetch(server, tmp_path, sleep=lambda _s: None)
    assert first.origin == "network" and first.sha256 == hashlib.sha256(b"[]").hexdigest()
    second = fetch_mod.fetch(server, tmp_path, sleep=lambda _s: None)
    assert second.origin == "not-modified"
    assert _Handler.seen[-1].get("If-None-Match") == '"v1"'
    assert "langsuite/" in _Handler.seen[-1].get("User-Agent", "")
    offline = fetch_mod.fetch(server, tmp_path, offline=True)
    assert offline.origin == "cache"


def test_fetch_retries_then_succeeds(server: Source, tmp_path: Path) -> None:
    _Handler.plan = [503, 500]
    got = fetch_mod.fetch(server, tmp_path, sleep=lambda _s: None)
    assert got.origin == "network" and len(_Handler.seen) == 3


def test_fetch_falls_back_to_cache(server: Source, tmp_path: Path) -> None:
    fetch_mod.fetch(server, tmp_path, sleep=lambda _s: None)
    (tmp_path / "t.json.meta.json").write_text(
        json.dumps({**json.loads((tmp_path / "t.json.meta.json").read_text()), "etag": ""})
    )
    _Handler.plan = [500, 500, 500]
    got = fetch_mod.fetch(server, tmp_path, sleep=lambda _s: None)
    assert got.origin == "cache" and "network failed" in got.note


def test_fetch_fails_cleanly(server: Source, tmp_path: Path) -> None:
    _Handler.plan = [404]
    with pytest.raises(DataError, match="HTTP 404"):
        fetch_mod.fetch(server, tmp_path, sleep=lambda _s: None)
    assert len(_Handler.seen) == 1  # no retry on 404


def test_fetch_unreachable(tmp_path: Path) -> None:
    src = Source("x", "Nowhere", "http://127.0.0.1:9/", "", "", "n.json")
    with pytest.raises(DataError, match="Could not download Nowhere"):
        fetch_mod.fetch(src, tmp_path, timeout=1, sleep=lambda _s: None)


def test_corrupt_cache_ignored(tmp_path: Path) -> None:
    (tmp_path / PLDB.filename).write_bytes(b"x")
    (tmp_path / f"{PLDB.filename}.meta.json").write_text('{"sha256": "bad"}')
    with pytest.raises(DataError, match="No cached copy"):
        fetch_mod.fetch(PLDB, tmp_path, offline=True)


# ----- live (optional; CI job `kb-live`) --------------------------------------


@pytest.mark.skipif(os.environ.get("LANGSUITE_LIVE") != "1", reason="network test")
def test_live_acceptance(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = build(home=tmp_path)
    assert manifest.counts["languages"] >= 800
    with KnowledgeBase(tmp_path) as kb:
        rows = kb.assertions(kb.resolve("haskell").id)
        assert {a.source for a in rows} == {"pldb", "linguist"}
