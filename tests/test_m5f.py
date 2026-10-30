"""M5f: docs ingest and quoting, dead-link archiving, signed snapshots, changelog and gate."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from typer.testing import CliRunner

from langsuite.cli.app import app
from langsuite.core import docs, snapshots
from langsuite.core.errors import AuthError
from langsuite.core.kb import KnowledgeBase

T0 = datetime(2026, 10, 1, tzinfo=UTC)
PAGE_A = "https://docs.example.org/a.html"
PAGE_B = "https://docs.example.org/b.html"
HTML_A = """<html><nav>menu</nav><h1 id="intro">Intro</h1><p>Welcome.</p>
<h2 id="loops">For loops</h2><p>The for statement iterates over the items of any sequence,
in the order that they appear in the sequence.</p><script>x()</script></html>"""
HTML_B = "<h2 id='match'>Match</h2><p>A match expression compares a value against patterns.</p>"


def _cfg(licence: str = "PSF-2.0") -> dict[str, Any]:
    return {
        "fx": {
            "version": "3.13",
            "licence": licence,
            "licence_url": "https://l",
            "pages": [PAGE_A, PAGE_B],
        }
    }


class Site:
    def __init__(self) -> None:
        self.pages = {PAGE_A: HTML_A, PAGE_B: HTML_B}
        self.down: set[str] = set()
        self.calls: list[str] = []

    def __call__(self, url: str, etag: str | None) -> docs.Fetch:
        self.calls.append(url)
        if url in self.down:
            return docs.Fetch(404)
        body = self.pages[url]
        tag = f'"{hash(body)}"'
        return docs.Fetch(304) if etag == tag else docs.Fetch(200, tag, body)


def test_quote_is_verbatim_with_link_version_anchor(tmp_path: Path) -> None:
    docs.ingest("fx", fetch=Site(), home=tmp_path, cfg=_cfg(), now=T0)
    (q,) = docs.search("for loops sequence", "fx", home=tmp_path, limit=1)
    assert q.url == PAGE_A + "#loops" and q.version == "3.13" and q.licence == "PSF-2.0"
    assert q.text.startswith("The for statement iterates") and "menu" not in q.text
    assert q.text.replace("\n", " ") in HTML_A.replace("\n", " ")
    assert "x()" not in q.text


def test_unknown_licence_short_excerpt_and_link(tmp_path: Path) -> None:
    site = Site()
    site.pages[PAGE_A] = "<h2 id='long'>Long</h2><p>" + "word loops. " * 200 + "</p>"
    docs.ingest("fx", fetch=site, home=tmp_path, cfg=_cfg("UNKNOWN"), now=T0)
    (q,) = docs.search("loops", "fx", home=tmp_path, limit=1)
    assert len(q.text) <= docs.SHORT_EXCERPT and q.truncated and q.url.endswith("#long")


def test_changed_page_reingests_only_that_page(tmp_path: Path) -> None:
    site = Site()
    docs.ingest("fx", fetch=site, home=tmp_path, cfg=_cfg(), now=T0)
    site.pages[PAGE_B] = HTML_B.replace("patterns", "patterns, top to bottom")
    rep = docs.ingest("fx", fetch=site, home=tmp_path, cfg=_cfg(), now=T0 + timedelta(days=1))
    assert rep["changed"] == [PAGE_B] and rep["unchanged"] == [PAGE_A]


def test_dead_link_flagged_then_archived_still_readable(tmp_path: Path) -> None:
    site = Site()
    docs.ingest("fx", fetch=site, home=tmp_path, cfg=_cfg(), now=T0)
    site.down.add(PAGE_A)
    for day, want in [(1, "failed"), (8, "failed"), (16, "archived")]:
        rep = docs.ingest("fx", fetch=site, home=tmp_path, cfg=_cfg(), now=T0 + timedelta(days=day))
        assert rep[want] == [PAGE_A]
    states = {r["url"]: r["state"] for r in docs.status("fx", tmp_path)}
    assert states == {PAGE_A: "archived", PAGE_B: "ok"}
    (q,) = docs.search("for loops", "fx", home=tmp_path, limit=1)
    assert q.archived and q.text.startswith("The for statement")


def _keys(tmp_path: Path) -> tuple[bytes, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    priv = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    pub = tmp_path / "cosign.pub"
    pub.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return priv, pub


def test_signed_snapshot_pulls_and_tampered_is_rejected(kb_home: Path, tmp_path: Path) -> None:
    priv, pub = _keys(tmp_path)
    out = tmp_path / "pub"
    bundle = snapshots.pack(kb_home, out)
    snapshots.sign(bundle, priv)
    fresh = tmp_path / "fresh"
    m = snapshots.pull(str(out), pub.read_bytes(), home=fresh)
    with KnowledgeBase(fresh) as kb:
        assert kb.manifest.snapshot_id == m.snapshot_id and kb.languages
    data = bytearray(bundle.read_bytes())
    data[len(data) // 2] ^= 0xFF
    bundle.write_bytes(bytes(data))
    with pytest.raises(AuthError):
        snapshots.pull(str(out), pub.read_bytes(), home=tmp_path / "other")
    res = CliRunner().invoke(app, ["base", "pull", str(out), "--key", str(pub)])
    assert isinstance(res.exception, AuthError)  # main() maps this to exit 4
    nokey = CliRunner().invoke(app, ["base", "pull", str(out)])
    assert isinstance(nokey.exception, AuthError) and "No publisher key" in str(nokey.exception)


def test_changelog_gate_and_stale_fields(kb_home: Path) -> None:
    with KnowledgeBase(kb_home) as a, KnowledgeBase(kb_home) as b:
        log = snapshots.changelog(a, b, now=datetime(2099, 1, 1, tzinfo=UTC))
    assert not log.added and not log.changes and not log.jumps and log.stale
    log.scores = [
        {"lang": "x", "old": 50.0, "new": 70.0, "delta": 20.0},
        {"lang": "y", "old": 50.0, "new": 60.0, "delta": 10.0},
    ]
    assert [j["lang"] for j in log.jumps] == ["x"] and not log.to_json()["publish_ok"]
    assert "| x | 50.0 | 70.0 | +20.0 |" in snapshots.issue_body(log)


def test_changelog_cli_lists_every_change(kb_home: Path, tmp_path: Path) -> None:
    import duckdb

    from langsuite.core.kb import DB_NAME, retain_snapshot

    with KnowledgeBase(kb_home) as kb:
        old = kb.manifest
    retain_snapshot(kb_home, old)
    db = kb_home / "base" / DB_NAME
    (kb_home / "base" / DB_NAME).unlink()  # break the hard link to the kept copy
    import shutil

    shutil.copyfile(kb_home / "base" / "snapshots" / old.snapshot_id / DB_NAME, db)
    con = duckdb.connect(str(db))
    row = con.execute("SELECT lang_id, feature_id, value FROM assertions LIMIT 1").fetchone()
    assert row is not None
    con.execute(
        "UPDATE assertions SET value = 'changed' WHERE lang_id = ? AND feature_id = ?",
        [row[0], row[1]],
    )
    man = json.loads(con.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])  # type: ignore[index]
    man["snapshot_id"] = "base-new000000000"
    con.execute("UPDATE meta SET value = ? WHERE key = 'manifest'", [json.dumps(man)])
    con.close()
    (kb_home / "base" / "manifest.json").write_text(json.dumps(man))
    res = CliRunner().invoke(
        app, ["--json", "base", "changelog", old.snapshot_id, "base-new000000000"]
    )
    assert res.exit_code == 0, res.stdout
    data = json.loads(res.stdout)["data"]
    assert {"lang": row[0], "feature": row[1], "old": row[2], "new": "changed"} in data["changes"]


def test_inclusion_subcommands_not_swallowed_by_lang(kb_home: Path) -> None:
    r = CliRunner()
    assert r.invoke(app, ["--plain", "inclusion", "list"]).exit_code == 0
    assert r.invoke(app, ["--plain", "inclusion", "list", "--status", "archived"]).exit_code == 0
    out = r.invoke(app, ["--plain", "inclusion", "haskell"])
    assert out.exit_code == 0 and "Haskell" in out.stdout
