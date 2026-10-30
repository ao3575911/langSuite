"""M2: query DSL, feature similarity and the shuffled baseline (SPEC §4, §7, §10 M2)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from langsuite.cli.app import main
from langsuite.core import query as q
from langsuite.core import similarity as sim
from langsuite.core.errors import NoResultError, NotBuiltYetError
from langsuite.core.kb import KnowledgeBase

# Golden pairs: (language, expected neighbour). On fixtures only Scheme/Racket exists;
# the live job checks the full set against the real base.
FIXTURE_GOLDEN = [("scheme", "racket")]
LIVE_GOLDEN = [
    ("scheme", "racket"),
    ("clojure", "clojurescript"),
    ("ocaml", "reason"),
    ("java", "kotlin"),
]


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    try:
        main(args)
        code = 0
    except SystemExit as exc:
        code = int(exc.code or 0)
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def kb(kb_home: Path) -> Any:
    with KnowledgeBase(kb_home) as base:
        yield base


# ----- similarity ----------------------------------------------------------------


def test_golden_racket_in_schemes_top3(kb: KnowledgeBase) -> None:
    result = sim.similar(kb, "scheme", k=3, min_traits=1)
    assert "racket" in [n.id for n in result.neighbours]


@pytest.mark.parametrize(("a", "b"), FIXTURE_GOLDEN)
def test_golden_pairs_beat_shuffled_baseline_by_3sd(kb: KnowledgeBase, a: str, b: str) -> None:
    pair = sim.compare_pair(kb, a, b)
    assert pair.baseline is not None
    assert pair.baseline.z >= 3, pair.baseline


def test_similar_is_deterministic(kb: KnowledgeBase, kb_home: Path) -> None:
    first = sim.similar(kb, "scheme", baseline=True, min_traits=1).to_json()
    with KnowledgeBase(kb_home) as again:
        second = sim.similar(again, "scheme", baseline=True, min_traits=1).to_json()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_baseline_seed_changes_null_but_not_score(kb: KnowledgeBase) -> None:
    tm = kb.trait_matrix()
    i, j = tm.index["scheme"], tm.index["racket"]
    b1, b2 = tm.baseline(i, j, seed=1), tm.baseline(i, j, seed=2)
    assert b1.mean != b2.mean
    assert tm.pair_score(i, j) == tm.pair_score(j, i)


def test_similarity_properties(kb: KnowledgeBase) -> None:
    tm = kb.trait_matrix()
    scores = tm.scores(tm.index["haskell"])
    assert scores[tm.index["haskell"]] == pytest.approx(1.0)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_neighbours_carry_evidence(kb: KnowledgeBase) -> None:
    top = sim.similar(kb, "scheme", k=1, min_traits=1).neighbours[0]
    assert "homoiconicity" in top.shared
    traits = kb.trait_matrix().traits_of("racket")
    assert set(top.shared) | set(top.only_other) == traits


def test_min_traits_filters_sparse_languages(kb: KnowledgeBase) -> None:
    ids = [n.id for n in sim.similar(kb, "scheme", k=20, min_traits=10).neighbours]
    assert "lisp" not in ids and "miranda" not in ids


def test_language_without_traits_is_explained(kb: KnowledgeBase) -> None:
    with pytest.raises(NoResultError, match="No feature data"):
        sim.similar(kb, "nix")


# ----- query DSL -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("homoiconicity", {"lisp", "racket", "scheme"}),
        ("homoiconicity year<1990", {"lisp", "scheme"}),
        ("homoiconicity and not macros", {"lisp"}),
        ("monads or homoiconicity", {"haskell", "lisp", "racket", "scheme"}),
        ("(monads or homoiconicity) and year>=1990", {"haskell", "racket"}),
        ("type-classes", {"haskell"}),
        ("typeclasses=yes", {"haskell"}),
        ("ext=.hs", {"haskell"}),
        ("name~sch", {"scheme"}),
        ("kind=data", {"xml"}),
        ("source=linguist kind!=pl", {"nix", "xml"}),
        ("has=pattern-matching", None),
    ],
)
def test_query_filters(kb: KnowledgeBase, text: str, expected: set[str] | None) -> None:
    result = q.run(kb, text)
    got = {r.language.id for r in result.rows}
    if expected is None:
        assert "haskell" in got
    else:
        assert got == expected


def test_shorthand_key_value(kb: KnowledgeBase) -> None:
    result = q.run(kb, "typing=static")
    assert result.normalised == "static-typing"
    assert "haskell" in {r.language.id for r in result.rows}


def test_feature_unknown_value(kb: KnowledgeBase) -> None:
    unknown = {r.language.id for r in q.run(kb, "monads=unknown").rows}
    assert "haskell" not in unknown and "nix" in unknown


def test_sort_and_top(kb: KnowledgeBase) -> None:
    asc = [r.language.id for r in q.run(kb, "kind=pl sort=year").rows]
    desc = [r.language.id for r in q.run(kb, "kind=pl sort=-year").rows]
    assert asc[0] == "lisp" and desc == list(reversed(asc))
    assert len(q.run(kb, "kind=pl top=3").rows) == 3
    assert q.run(kb, "kind=pl top=3").total > 3
    assert [r.language.id for r in q.run(kb, "sort=-traits top=1").rows] == ["python"]


def test_query_same_output_twice(kb: KnowledgeBase) -> None:
    a = q.run(kb, "year>1970 sort=name").to_json()
    b = q.run(kb, "year>1970 sort=name").to_json()
    assert a == b


@pytest.mark.parametrize(
    ("text", "message", "pos"),
    [
        ("(macros", "Missing", 0),
        ("kind=pl and", "after `and`", 11),
        ("year>abc", "needs a number", 0),
        ("year~19", "text fields", 0),
        ("nosuchthing", "No feature matches", 0),
        ("frob=zzz", "Unknown field", 0),
        ("macros=maybe", "isn't a feature value", 0),
        ("sort=colour", "Can't sort", 5),
        ("top=0", "whole number", 4),
        ("kind=pl )", "Unexpected", 8),
        ("()", "Empty parentheses", 0),
        ('name="unterminated', "Unexpected character", 5),
    ],
)
def test_query_errors_point_at_problem(
    kb: KnowledgeBase, text: str, message: str, pos: int
) -> None:
    with pytest.raises(q.QueryError, match=message) as info:
        q.run(kb, text)
    assert info.value.position == pos
    assert info.value.hint is not None and info.value.hint.endswith("^")


def test_planned_fields_say_when(kb: KnowledgeBase) -> None:
    with pytest.raises(NotBuiltYetError, match="M5c"):
        q.run(kb, "score>=70")
    with pytest.raises(NotBuiltYetError, match="M5c"):
        q.run(kb, "sort=-score")


def test_validate_and_length_cap(kb: KnowledgeBase) -> None:
    assert q.validate(kb, "macros") is None
    assert q.validate(None, "(macros") is not None
    assert isinstance(q.validate(kb, "x" * 3000), q.QueryError)


# ----- CLI -----------------------------------------------------------------------


def test_cli_similar(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--plain", "similar", "scheme", "-k", "3", "--min-traits", "1"], capsys)
    assert code == 0
    assert "Racket" in out and "shuffled-features" in out


def test_cli_similar_json_and_alias(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--json", "s", "scheme", "--min-traits", "1"], capsys)
    data = json.loads(out)["data"]
    assert code == 0 and data["method"] == sim.METHOD
    assert data["neighbours"][0]["id"] == "racket"
    assert data["neighbours"][0]["baseline"]["z"] >= 3


def test_cli_similar_pair(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--plain", "-m", "thorough", "similar", "scheme", "--vs", "racket"], capsys)
    assert code == 0 and "z =" in out and "Only Racket" in out
    code, out, _ = run(["--json", "similar", "scheme", "--vs", "racket"], capsys)
    assert json.loads(out)["data"]["baseline"]["z"] >= 3


def test_cli_similar_code_lens_is_planned(
    kb_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = run(["--plain", "similar", "scheme", "--by", "code"], capsys)
    assert code == 2 and "M5" in err


def test_cli_similar_too_strict(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(["--plain", "similar", "scheme", "--min-traits", "500"], capsys)
    assert code == 2 and "--min-traits" in err


@pytest.mark.parametrize("mode", ["concise", "default", "thorough"])
def test_cli_query_modes(kb_home: Path, capsys: pytest.CaptureFixture[str], mode: str) -> None:
    code, out, _ = run(["--plain", "-m", mode, "q", "homoiconicity sort=year"], capsys)
    assert code == 0 and out.index("lisp") < out.index("scheme")


def test_cli_query_json(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["--json", "query", "type-classes", "--top", "1"], capsys)
    data = json.loads(out)["data"]
    assert code == 0 and data["total"] == 1 and len(data["rows"]) == 1
    assert data["features"] == ["type-classes"]


def test_cli_query_no_match_and_error(kb_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(["--plain", "query", "homoiconicity and monads"], capsys)
    assert code == 2 and "No languages match" in err
    code, out, _ = run(["--json", "query", "homoiconicity and monads"], capsys)
    assert code == 2 and json.loads(out)["data"]["total"] == 0
    code, _, err = run(["--plain", "query", "(macros"], capsys)
    assert code == 2 and "Missing" in err and "^" in err


def test_cli_without_base(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(["--plain", "similar", "scheme"], capsys)
    assert code == 3 and "base build" in err


# ----- live (optional; CI job `kb-live`) --------------------------------------


@pytest.mark.skipif(os.environ.get("LANGSUITE_LIVE") != "1", reason="network test")
def test_live_golden(tmp_path: Path) -> None:
    from langsuite.ingest.build import build

    build(home=tmp_path)
    with KnowledgeBase(tmp_path) as base:
        top3 = [n.id for n in sim.similar(base, "scheme", k=3).neighbours]
        assert "racket" in top3
        for a, b in LIVE_GOLDEN:
            pair = sim.compare_pair(base, a, b)
            assert pair.baseline is not None and pair.baseline.z >= 3, (a, b, pair.baseline)
