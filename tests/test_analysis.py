"""M5, M5b, M5c: clusters with bootstrap, labels with evidence, influence, code similarity,
scores and grades, and their CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from langsuite.cli.app import app
from langsuite.core import analysis as an
from langsuite.core.kb import KnowledgeBase
from langsuite.verify import rosetta

LISPS = ["lisp", "scheme", "racket"]
MLS = ["haskell", "miranda", "ml"]


def _cli(*args: str) -> Any:
    return CliRunner().invoke(app, list(args))


def test_cluster_is_deterministic_with_support(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        a = an.cluster(kb, min_traits=3, rounds=30)
        b = an.cluster(kb, min_traits=3, rounds=30)
    assert a.to_json() == b.to_json()
    assert sum(len(c.members) for c in a.clusters) == a.languages
    assert all(0.0 <= c.support <= 1.0 for c in a.clusters)
    assert 4 <= a.k <= 8


def test_known_families_split_and_are_labelled(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        res = an.cluster(kb, k=4, min_traits=1, rounds=50, only=[*LISPS, *MLS, "clean"])
        by_member = {m: c for c in res.clusters for m in c.members}
        lisp = by_member["scheme"]
        assert set(lisp.members) >= {"scheme", "racket"}
        words = {w.trait for w in lisp.label}
        assert len(words) == 3 and all(w.lift > 0 for w in lisp.label)
        for w in lisp.label:  # every label word has a sourced assertion per member that has it
            for member, ids in w.evidence.items():
                assert ids and all(i.startswith("ev-") for i in ids)
                assert any(a.feature_id == w.trait for a in kb.assertions(member))
        # the fixture is sparse: Scheme and Racket stay together, Haskell stands apart
        assert by_member["haskell"] is not lisp
        assert "macros" in words
        assert lisp.support >= 0.7


def test_cluster_rename_persists_by_medoid(kb_home: Path) -> None:
    args = ["--json", "dashboard", "--langs", ",".join(LISPS + MLS), "--k", "2", "--bootstrap", "5"]
    first = json.loads(_cli(*args).stdout)["data"]
    medoid = first["clusters"][0]["medoid"]
    assert _cli("workspace", "init", "w1").exit_code == 0
    assert _cli("dashboard", "rename", medoid, "My family").exit_code == 0
    again = json.loads(_cli(*args).stdout)["data"]
    assert again["clusters"][0]["title"] == "My family"
    assert _cli("dashboard", "rename", medoid).exit_code == 0
    assert json.loads(_cli(*args).stdout)["data"]["clusters"][0]["title"] != "My family"


def test_influence_both_ways(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        root, nodes = an.influence(kb, "haskell", 1)
    assert root.id == "haskell"
    assert {n.id for n in nodes if n.depth == -1} >= {"miranda", "lisp"}
    out = _cli("--plain", "influence", "haskell", "-d", "1")
    assert out.exit_code == 0 and "Influenced by" in out.stdout


def test_code_similarity_and_disagreements(kb_home: Path) -> None:
    tasks = rosetta.load_tasks()
    near = an.code_similar(tasks, "scheme", k=5)
    assert near and all(0 <= c.score <= 1 for c in near)
    assert near == sorted(near, key=lambda c: (-c.score, c.id))
    assert an.tokens('print("hi", 42)') == ["print", "(", "S", ",", "N", ")"]
    with pytest.raises(Exception, match="No Rosetta"):
        an.code_similar(tasks, "no-such-lang")
    out = _cli("--plain", "similar", "scheme", "--by", "both", "--k", "3")
    assert out.exit_code == 0 and "both" in out.stdout


def test_scores_reproducible_and_sum(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        lang = kb.resolve("haskell")
        s1, s2 = an.score(kb, lang), an.score(kb, lang)
    assert s1 == s2
    present = [c.points for c in s1.criteria if c.points is not None]
    assert s1.total == pytest.approx(sum(present) / len(present))  # unrounded mean
    assert s1.n == len(present) and s1.confidence == pytest.approx(s1.n / len(s1.criteria))


def test_missing_criterion_never_adds_zero(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        for lang in kb.languages:
            s = an.score(kb, lang)
            for c in s.criteria:
                if c.points is None:
                    assert not c.basis
            if s.n:
                assert s.total == pytest.approx(
                    sum(c.points for c in s.criteria if c.points is not None) / s.n
                )


@pytest.mark.parametrize(
    ("total", "grade"),
    [(85.0, "A"), (84.99, "B"), (70.0, "B"), (69.99, "C"), (55.0, "C"), (54.9, "D"), (39.9, "E")],
)
def test_grade_cutoffs(total: float, grade: str) -> None:
    assert an.grade(total) == grade


def test_rank_desc_asc_filter_and_profile(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        d = an.rank(kb, top=5, min_n=1)
        a = an.rank(kb, top=100, descending=False, min_n=1)
        assert [r.lang for r in d.rows] == [r.lang for r in reversed(a.rows)][:5]
        f = an.rank(kb, top=50, filter_text="grade>=B paradigm=functional", min_n=1)
        assert f.rows and all(r.grade in "AB" for r in f.rows)
        values = kb.trait_values()
        assert all("functional" in an.paradigms(values.get(r.lang, {})) for r in f.rows)
        base = an.rank(kb, top=50, min_n=1)
        custom = an.rank(kb, by="custom", top=50, min_n=1, profile={"safety": 1.0})
        assert {r.lang: r.total for r in base.rows} == {r.lang: r.total for r in custom.rows}
        for r in custom.rows:
            safety = next(c for c in r.criteria if c.id == "safety")
            assert (r.custom is None) == (safety.points is None)
    out = _cli("--plain", "rank", "--top", "3", "--filter", "grade>=A")
    assert out.exit_code in (0, 2)


def test_compare_diff_like_cli(kb_home: Path) -> None:
    out = _cli("--plain", "compare", "haskell", "scheme")
    assert out.exit_code == 0 and "total" in out.stdout and "Shared" in out.stdout
    d = _cli("--json", "diff", "fizzbuzz", "--lang", "python,scheme")
    data = json.loads(d.stdout)["data"]
    assert d.exit_code == 0 and len(data["pairs"]) == 1 and data["licence"]
    lk = _cli("--plain", "like", "fizzbuzz", "--as", "haskell", "--in", "python")
    assert lk.exit_code == 0 and "the haskell way" in lk.stdout
    assert _cli("--plain", "diff", "fizzbuzz", "--lang", "python").exit_code != 0
    assert _cli("--plain", "cluster", "--min-traits", "3", "--bootstrap", "3").exit_code == 0


async def test_dashboard_and_analyse_panes(kb_home: Path) -> None:
    from textual.widgets import Static

    from langsuite.tui.app import LangsuiteApp

    app_ = LangsuiteApp()
    async with app_.run_test(size=(120, 40)) as pilot:
        await pilot.press("4")
        pane = app_.query_one("#pane-analyse")
        pane.run_command("rank --top 3 --min-criteria 1")  # type: ignore[attr-defined]
        await app_.workers.wait_for_complete()
        await pilot.pause()
        text = str(app_.query_one("#analyse-output", Static).render())
        assert "rank --top 3" in text and "grade" in text
        await pilot.press("1")
        dash = app_.query_one("#pane-dashboard")
        dash.run_command("influence haskell -d 1")  # type: ignore[attr-defined]
        await app_.workers.wait_for_complete()
        await pilot.pause()
        assert "Influenced by" in str(app_.query_one("#dashboard-output", Static).render())
