"""M3: workspaces, findings, notes, saved queries, own data, pinned snapshots (SPEC §10 M3)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from langsuite.cli.app import main
from langsuite.core import kb as kbmod
from langsuite.core.errors import DataError, NoResultError, NotBuiltYetError, UsageError
from langsuite.core.kb import KnowledgeBase, Overlay
from langsuite.core.workspace import (
    Workspace,
    active_slug,
    canonical,
    command_line,
    digest,
    open_kb,
    pinned_snapshots,
)
from langsuite.ingest import build as buildmod

FIXTURES = Path(__file__).parent / "fixtures" / "kb"
EXAMPLE = Path(__file__).parent.parent / "examples" / "own-data.yml"

OWN = {
    "languages": [
        {
            "id": "quill",
            "name": "Quill",
            "appeared": 2026,
            "extensions": ["qul"],
            "influenced_by": ["scheme"],
            "source": "https://example.org/quill",
            "traits": {
                "homoiconicity": True,
                "macros": "yes",
                "prefix-notation": "yes",
                "line-comments": "yes",
                "comments": "yes",
                "garbage-collection": "no",
            },
        }
    ],
    "assertions": [{"lang": "python", "feature": "macros", "value": "no"}],
}


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    try:
        main(args)
        code = 0
    except SystemExit as exc:
        code = int(exc.code or 0)
    out = capsys.readouterr()
    return code, out.out, out.err


def data(out: str) -> Any:
    return json.loads(out)["data"]


# ----- own data overlay ------------------------------------------------------------


def test_custom_language_overlay(kb_home: Path) -> None:
    ws = Workspace.open()
    assert ws.import_data(OWN) == (1, 7, 1)
    with open_kb() as kb:
        quill = kb.resolve("quill")
        assert quill.sources == ("user",)
        assert kb.resolve(".qul").id == "quill"
        assert {a.feature_id for a in kb.assertions("quill")} >= {"homoiconicity", "macros"}
        assert "quill" in {lang.id for lang in kb.languages_with("homoiconicity")}
        assert kb.trait_values()["quill"]["garbage-collection"] == "no"
        assert ("quill", "macros") in kb.trait_pairs()
        parents, _ = kb.edges("quill")
        assert [e.src for e in parents] == ["scheme"]
        counts = kb.feature_counts()
        with KnowledgeBase() as base:
            assert (
                counts["homoiconicity"]["yes"] == base.feature_counts()["homoiconicity"]["yes"] + 1
            )
            with pytest.raises(NoResultError):
                base.resolve("quill")  # the shared base is untouched
    from langsuite.core import query as q
    from langsuite.core import similarity as sim

    with open_kb() as kb:
        assert "quill" in {r.language.id for r in q.run(kb, "homoiconicity and macros").rows}
        top = sim.similar(kb, "quill", k=3, rounds=50).neighbours[0]
        assert top.id in {"scheme", "racket", "lisp", "clojure"}


def test_overlay_validation(kb_home: Path) -> None:
    ws = Workspace.open()
    with pytest.raises(UsageError, match="already in the base"):
        ws.import_data({"languages": [{"id": "scheme"}]})
    with pytest.raises(UsageError, match="unknown language"):
        ws.import_data({"assertions": [{"lang": "nope", "feature": "macros", "value": "yes"}]})
    with pytest.raises(UsageError, match="Unknown feature"):
        ws.import_data({"languages": [{"id": "zz", "traits": {"flying": "yes"}}]})
    with pytest.raises(UsageError, match="yes or no"):
        ws.import_data({"languages": [{"id": "zz", "traits": {"macros": "maybe"}}]})
    with pytest.raises(UsageError, match="not a valid language id"):
        ws.import_data({"languages": [{"id": "Bad Id"}]})
    with pytest.raises(UsageError, match="malformed"):
        ws.import_data({"languages": [{"name": "no id"}]})
    with pytest.raises(UsageError, match="mapping"):
        ws.import_data([1, 2])  # type: ignore[arg-type]
    assert not ws.overlay
    ws.import_data(OWN)
    ws.import_data({"assertions": [{"lang": "quill", "feature": "macros", "value": "no"}]})
    macros = [a for a in ws.overlay.assertions if a.lang_id == "quill" and a.feature_id == "macros"]
    assert [a.value for a in macros] == ["no"]  # later imports replace earlier facts
    ws.clear_overlay()
    assert not ws.overlay


def test_overlay_round_trips_json() -> None:
    ov = Overlay.from_json(
        {
            "languages": [
                {
                    "id": "a",
                    "name": "A",
                    "kind": "pl",
                    "appeared": None,
                    "website": None,
                    "creators": None,
                    "rank": None,
                    "aliases": ["x"],
                    "extensions": [],
                    "sources": ["user"],
                }
            ]
        }
    )
    assert Overlay.from_json(ov.to_json()) == ov
    assert ov and not Overlay()


# ----- findings and reproducibility --------------------------------------------------


def _home_with_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, src: Path) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("LANGSUITE_HOME", str(home))
    buildmod.build(home=home, from_dir=src)
    return home


def _upgraded_fixtures(tmp_path: Path) -> Path:
    """Fixture sources with Scheme losing macros and gaining a trait: a new snapshot."""
    src = tmp_path / "src2"
    shutil.copytree(FIXTURES, src)
    pldb = json.loads((src / "pldb.json").read_text(encoding="utf-8"))
    for rec in pldb:
        if rec.get("id") == "scheme":
            rec["hasMacros"] = False
            rec["hasPatternMatching"] = True
    (src / "pldb.json").write_text(json.dumps(pldb), encoding="utf-8")
    return src


def test_base_upgrade_keeps_old_findings_reproducible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home_with_base(tmp_path, monkeypatch, FIXTURES)
    ws = Workspace.open()
    ws.import_data(OWN)
    saved = [
        ws.save_finding("query", {"text": "macros sort=year", "top": None}),
        ws.save_finding("similar", {"lang": "scheme", "k": 3, "min_traits": 5, "baseline": True}),
        ws.save_finding("pair", {"a": "scheme", "b": "racket"}),
        ws.save_finding("lang", {"lang": "scheme"}),
    ]
    old = saved[0].snapshot_id
    assert all(f.snapshot_id == old for f in saved)
    assert all(f.overlay for f in saved)
    assert saved[3].evidence and all(e.startswith("ev-") for e in saved[3].evidence)

    buildmod.build(home=home, from_dir=_upgraded_fixtures(tmp_path))
    new = kbmod.read_manifest(home)
    assert new is not None and new.snapshot_id != old
    assert {m.snapshot_id for m in kbmod.kept_snapshots(home)} == {old, new.snapshot_id}

    # the same commands now give different answers on the new base ...
    from langsuite.core.workspace import run_recorded

    with open_kb() as kb:
        fresh, _, _ = run_recorded(kb, "query", {"text": "macros sort=year", "top": None})
    assert digest(fresh) != saved[0].result_sha256
    # ... but every old finding re-runs bit-for-bit on its own snapshot
    for f in saved:
        check = ws.verify(f.id)
        assert check.ok, f.id
        assert check.snapshot_id == old
    assert old in pinned_snapshots(home)


def test_tampered_finding_is_caught(kb_home: Path) -> None:
    ws = Workspace.open()
    f = ws.save_finding("lang", {"lang": "haskell"})
    path = ws.path / "findings" / f"{f.id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["result_sha256"] = "0" * 64
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert not ws.verify(f.id).ok


def test_prune_keeps_pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(buildmod, "KEEP_SNAPSHOTS", 1)
    home = _home_with_base(tmp_path, monkeypatch, FIXTURES)
    first = kbmod.read_manifest(home)
    assert first is not None
    ws = Workspace.open()
    ws.pin(None)
    assert ws.pinned == first.snapshot_id
    buildmod.build(home=home, from_dir=_upgraded_fixtures(tmp_path))
    kept = {m.snapshot_id for m in kbmod.kept_snapshots(home)}
    assert first.snapshot_id in kept  # pinned survives the prune
    with ws.kb() as kb:
        assert kb.manifest.snapshot_id == first.snapshot_id
    ws.unpin()
    third = tmp_path / "src3"
    shutil.copytree(FIXTURES, third)
    (third / "languages.yml").write_text(
        (third / "languages.yml").read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    pldb = json.loads((third / "pldb.json").read_text(encoding="utf-8"))
    pldb[0]["creators"] = "Someone Else"
    (third / "pldb.json").write_text(json.dumps(pldb), encoding="utf-8")
    buildmod.build(home=home, from_dir=third)
    kept = {m.snapshot_id for m in kbmod.kept_snapshots(home)}
    assert first.snapshot_id not in kept  # unpinned and old: pruned
    with pytest.raises(DataError, match="not kept"):
        KnowledgeBase(home, snapshot=first.snapshot_id)


def test_finding_refs_and_last(kb_home: Path) -> None:
    ws = Workspace.open()
    with pytest.raises(NoResultError, match="No findings"):
        ws.finding("last")
    with pytest.raises(NoResultError, match="Nothing to extract"):
        ws.last()
    a = ws.save_finding("lang", {"lang": "haskell"}, title="  Haskell  ", tags=["b", "a", "a"])
    b = ws.save_finding("lang", {"lang": "scheme"})
    assert (a.id, b.id) == ("f1", "f2")
    assert a.title == "Haskell" and a.tags == ["a", "b"]
    assert ws.finding("last").id == "f2" and ws.finding("1").id == "f1"
    with pytest.raises(NoResultError, match="No finding"):
        ws.finding("f9")
    with pytest.raises(UsageError, match="Unknown finding kind"):
        ws.save_finding("dance", {})
    ws.remove_finding("f1")
    assert [f.id for f in ws.findings()] == ["f2"]
    assert ws.save_finding("lang", {"lang": "c"}).id == "f3"


def test_command_line_and_canonical() -> None:
    assert command_line("query", {"text": "a b", "top": 3}) == 'langsuite query "a b" --top 3'
    assert command_line("similar", {"lang": "c", "k": 2, "baseline": False}).endswith(
        "--no-baseline"
    )
    assert command_line("pair", {"a": "x", "b": "y"}) == "langsuite similar x --vs y"
    assert command_line("lang", {"lang": "x"}) == "langsuite lang show x"
    assert canonical({"b": 1, "a": [1.5]}) == '{"a":[1.5],"b":1}'


def test_workspaces_and_notes(kb_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert active_slug() == "default"
    from langsuite.tui.app import _default_handle

    assert _default_handle() == "$langsuite/guest/default"
    with pytest.raises(NoResultError, match="No workspace named"):
        Workspace.open(slug="nope")
    with pytest.raises(UsageError):
        Workspace(slug="Bad Name")
    monkeypatch.setenv("LANGSUITE_WORKSPACE", "env-one")
    assert active_slug() == "env-one"
    monkeypatch.delenv("LANGSUITE_WORKSPACE")
    ws = Workspace.open()
    with pytest.raises(UsageError, match="needs some text"):
        ws.add_note("  ")
    with pytest.raises(NoResultError):
        ws.add_note("x", on="f7")
    n1 = ws.add_note("first")
    n2 = ws.add_note("on haskell", on="haskell")
    assert [n.id for n in ws.notes()] == [n1.id, n2.id]
    assert ws.notes(on="haskell") == [n2]
    ws.remove_note("n1")
    with pytest.raises(NoResultError):
        ws.remove_note("n1")
    ws.save_query("lisps", "homoiconicity")
    assert ws.saved_query("lisps") == "homoiconicity"
    with pytest.raises(NoResultError):
        ws.saved_query("nope")
    with pytest.raises(UsageError):
        ws.save_query("long", "a" * 3000)
    ws.forget_query("lisps")
    with pytest.raises(NoResultError):
        ws.forget_query("lisps")


def test_bundle_round_trip(kb_home: Path) -> None:
    ws = Workspace.open()
    ws.import_data(OWN)
    ws.save_finding("lang", {"lang": "quill"})
    ws.add_note("hi", on="f1")
    ws.save_query("q1", "macros")
    bundle = ws.bundle()
    other = Workspace(slug="copy")
    assert other.load_bundle(bundle) == 1
    assert other.verify("f1").ok
    assert other.saved_queries() == {"q1": "macros"}
    with pytest.raises(UsageError, match="not empty"):
        other.load_bundle(bundle)
    with pytest.raises(UsageError, match="not a langsuite workspace"):
        Workspace(slug="x").load_bundle({"kind": "other"})
    bundle["findings"][0]["result"]["language"]["name"] = "Forged"
    with pytest.raises(DataError, match="altered"):
        Workspace(slug="forged").load_bundle(bundle)


def test_damaged_files_are_reported(kb_home: Path) -> None:
    ws = Workspace.open()
    (ws.path / "notes.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(DataError, match="unreadable"):
        ws.notes()


# ----- CLI ------------------------------------------------------------------------


def test_cli_extract_flow(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(["extract"], capsys)
    assert code == 2 and "Nothing to extract" in err
    assert run(["--plain", "query", "macros", "--save", "macro-langs"], capsys)[0] == 0
    code, out, _ = run(["--plain", "extract", "last", "--title", "Macro languages"], capsys)
    assert code == 0 and "Saved f1" in out and "sha256" in out
    run(["--plain", "similar", "scheme", "-k", "3"], capsys)
    code, out, _ = run(["--json", "x"], capsys)
    assert data(out)["kind"] == "similar" and data(out)["id"] == "f2"
    run(["--plain", "lang", "show", "haskell"], capsys)
    assert run(["--plain", "x"], capsys)[0] == 0
    run(["--plain", "similar", "scheme", "--vs", "racket"], capsys)
    assert run(["--plain", "x", "--tag", "pair"], capsys)[0] == 0
    code, out, _ = run(["--plain", "x", "f1", "--title", "again"], capsys)
    assert "Saved f5" in out
    code, out, _ = run(["--plain", "f", "ls"], capsys)
    assert code == 0 and "Macro languages" in out and "5 findings" in out
    code, out, _ = run(["--json", "finding", "list"], capsys)
    assert len(data(out)) == 5 and "result" not in data(out)[0]
    code, out, _ = run(["--plain", "query", "--saved", "macro-langs"], capsys)
    assert code == 0 and "macros" in out


def test_cli_finding_commands(
    kb_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(["--plain", "finding", "list"], capsys)
    assert "No findings yet" in out
    assert run(["--plain", "finding", "save", "query", "homoiconicity"], capsys)[0] == 0
    assert run(["--plain", "finding", "save", "similar", "scheme", "-k", "2"], capsys)[0] == 0
    assert run(["--plain", "finding", "save", "pair", "python", "--vs", "c"], capsys)[0] == 0
    assert run(["--plain", "finding", "save", "lang", "lisp"], capsys)[0] == 0
    code, _, err = run(["--plain", "finding", "save", "pair", "python"], capsys)
    assert code == 2 and "--vs" in err
    code, _, err = run(["--plain", "finding", "save", "poem", "x"], capsys)
    assert code == 2
    run(["--plain", "note", "add", "worth a look", "--on", "f2"], capsys)
    code, out, _ = run(["--plain", "finding", "show", "f2", "--verify"], capsys)
    assert code == 0 and "reproducible" in out and "worth a look" in out and "Racket" in out
    code, out, _ = run(["--json", "finding", "show", "last", "--verify"], capsys)
    assert data(out)["verification"]["reproducible"] is True
    code, out, _ = run(["--plain", "finding", "verify"], capsys)
    assert code == 0 and "4 of 4 reproducible" in out
    code, out, _ = run(["--json", "finding", "verify", "f1"], capsys)
    assert data(out)[0]["reproducible"]
    for fmt in ("md", "json", "csv"):
        code, out, _ = run(["--plain", "finding", "export", "--format", fmt], capsys)
        assert code == 0 and "f1" in out
    target = tmp_path / "f1.md"
    code, out, _ = run(["--plain", "finding", "export", "f1", "-o", str(target)], capsys)
    assert "Wrote 1" in out and target.read_text(encoding="utf-8").startswith("# Query:")
    # tamper with a stored hash: verify must fail with exit 3
    path = Workspace.open().path / "findings" / "f1.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["result_sha256"] = "f" * 64
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert run(["--plain", "finding", "verify"], capsys)[0] == 3
    code, out, _ = run(["--plain", "finding", "show", "f1", "--verify"], capsys)
    assert code == 3 and "changed" in out
    assert run(["--json", "finding", "show", "f1", "--verify"], capsys)[0] == 3
    code, out, _ = run(["--plain", "finding", "rm", "f1"], capsys)
    assert "Removed f1" in out
    assert run(["--json", "finding", "remove", "f2"], capsys)[0] == 0


def test_cli_notes(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, out, _ = run(["--plain", "note", "list"], capsys)
    assert "No notes yet" in out
    _, out, _ = run(["--plain", "n", "add", "macro hygiene", "--on", "racket"], capsys)
    assert "Added n1 on racket" in out
    _, out, _ = run(["--json", "note", "add", "plain"], capsys)
    assert data(out)["id"] == "n2"
    _, out, _ = run(["--plain", "note", "ls", "--on", "racket"], capsys)
    assert "macro hygiene" in out and "plain" not in out
    _, out, _ = run(["--json", "note", "list"], capsys)
    assert len(data(out)) == 2
    assert "Removed n1" in run(["--plain", "note", "rm", "n1"], capsys)[1]
    assert run(["--json", "note", "remove", "n2"], capsys)[0] == 0


def test_cli_workspaces(kb_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--plain", "workspace", "init", "lisp-survey"], capsys)
    assert code == 0 and "lisp-survey" in out
    code, out, _ = run(["--plain", "w", "ls"], capsys)
    assert "* lisp-survey" in out
    code, out, _ = run(["--plain", "workspace", "import", str(EXAMPLE)], capsys)
    assert code == 0 and "Added 1 language," in out
    code, out, _ = run(["--plain", "lang", "show", "quill"], capsys)
    assert code == 0 and "Quill" in out
    run(["--plain", "finding", "save", "similar", "quill", "-k", "3"], capsys)
    run(["--plain", "query", "macros", "--save", "macros"], capsys)
    code, out, _ = run(["--plain", "workspace", "show"], capsys)
    assert "findings 1" in out and "quill" in out and "macros" in out
    code, out, _ = run(["--json", "workspace", "show"], capsys)
    assert data(out)["own_languages"] == ["quill"]
    bundle = tmp_path / "ws.json"
    code, out, _ = run(["--plain", "workspace", "export", str(bundle)], capsys)
    assert "Wrote lisp-survey" in out
    code, out, _ = run(["--plain", "workspace", "export"], capsys)
    assert json.loads(out)["kind"] == "langsuite-workspace"
    code, out, _ = run(["--plain", "workspace", "import", str(bundle), "--as", "copy"], capsys)
    assert "Imported workspace copy with 1 findings" in out
    code, out, _ = run(["--json", "workspace", "use", "copy"], capsys)
    assert data(out)["workspace"] == "copy"
    assert run(["--plain", "finding", "verify"], capsys)[0] == 0
    code, out, _ = run(["--plain", "workspace", "use", "default"], capsys)
    assert "Active workspace: default" in out
    code, _, err = run(["--plain", "lang", "show", "quill"], capsys)
    assert code == 2  # own data stays in its workspace
    code, _, err = run(["--plain", "workspace", "use", "ghost"], capsys)
    assert code == 2 and "workspace init ghost" in err
    code, out, _ = run(["--json", "workspace", "list"], capsys)
    assert {w["workspace"] for w in data(out)} >= {"default", "lisp-survey", "copy"}
    run(["--plain", "workspace", "use", "lisp-survey"], capsys)
    code, out, _ = run(["--plain", "workspace", "forget-data"], capsys)
    assert "cleared" in out
    code, _, err = run(["--plain", "workspace", "import", str(tmp_path / "missing.yml")], capsys)
    assert code == 2 and "Cannot read" in err
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    code, _, err = run(["--plain", "workspace", "import", str(bad)], capsys)
    assert code == 2 and "not valid" in err
    code, out, _ = run(["--json", "workspace", "init", "x2", "--no-use"], capsys)
    assert data(out)["active"] is False
    code, out, _ = run(["--json", "workspace", "import", str(EXAMPLE), "--as", "x2"], capsys)
    assert data(out)["languages"] == 1
    with pytest.raises(NotBuiltYetError):
        main(["--debug", "workspace", "sync"])


def test_cli_base_pin_and_snapshots(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--plain", "base", "snapshots"], capsys)
    assert "base-" in out and "current" in out
    code, out, _ = run(["--plain", "base", "pin"], capsys)
    assert code == 0 and "pinned to base-" in out
    code, out, _ = run(["--json", "base", "snapshots"], capsys)
    assert data(out)[0]["pinned"] and data(out)[0]["current"]
    code, out, _ = run(["--plain", "workspace", "show"], capsys)
    assert "pinned  base-" in out
    code, _, err = run(["--plain", "base", "pin", "base-000000000000"], capsys)
    assert code == 3 and "not kept" in err
    code, out, _ = run(["--json", "base", "pin", "--clear"], capsys)
    assert data(out)["snapshot"] is None
    assert "follows" in run(["--plain", "base", "pin", "--clear"], capsys)[1]


def test_cli_base_snapshots_empty(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--plain", "base", "snapshots"], capsys)
    assert code == 0 and "No snapshots kept" in out
    code, _, _err = run(["--plain", "base", "pin"], capsys)
    assert code == 3
