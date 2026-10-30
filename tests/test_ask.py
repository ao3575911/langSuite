"""M5d: cited answers and guides. Golden set: 25 simple, 25 advanced, 20 out-of-KB."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from langsuite.cli.app import app
from langsuite.core import ask as qa
from langsuite.core.kb import KnowledgeBase
from langsuite.verify import rosetta


def _golden(kb: KnowledgeBase) -> tuple[list[tuple[str, Any]], list[tuple[str, Any]]]:
    """(question, check) pairs built from the fixture base so every expected answer is sourced."""
    simple: list[tuple[str, Any]] = []
    advanced: list[tuple[str, Any]] = []
    for lang in kb.languages:
        if lang.appeared:
            simple.append((f"When was {lang.name} created?", str(lang.appeared)))
            simple.append((f"how old is {lang.id}", str(lang.appeared)))
        if lang.creators:
            simple.append((f"Who designed {lang.name}?", lang.creators))
        simple.append((f"What is {lang.name}?", lang.name))
    for lang in kb.languages:
        for a in kb.assertions(lang.id):
            if a.value in ("yes", "no") and len(advanced) < 15 and a.feature_id != "comments":
                want = "Yes" if a.value == "yes" else "No"
                advanced.append((f"Does {lang.name} have {a.feature_id.replace('-', ' ')}?", want))
    for feat in ("homoiconicity", "macros", "type inference", "garbage collection"):
        if kb.languages_with(feat.replace(" ", "-")):
            advanced.append(
                (f"Which languages have {feat}?", kb.languages_with(feat.replace(" ", "-"))[0].name)
            )
    tasks = rosetta.load_tasks()
    for t in ("fizzbuzz", "factorial", "fibonacci sequence"):
        for lid in ("python", "haskell"):
            advanced.append((f"How do I write {t} in {lid}?", "Rosetta Code"))
    for lang in kb.languages:
        parents, _ = kb.edges(lang.id)
        if parents and len(advanced) < 25:
            advanced.append((f"What influenced {lang.name}?", parents[0].src))
    assert tasks
    return simple[:25], advanced[:25]


OUT_OF_KB = [
    "what is the meaning of life",
    "who won the 2018 world cup",
    "when was cobol-2099 created",
    "does python have monads",
    "who designed klingonscript",
    "is haskell faster than c",
    "how do i write a compiler in python",
    "how do i write fizzbuzz in klingonscript",
    "which languages have teleportation",
    "what influenced klingonscript",
    "should i learn rust",
    "does scheme have quantum types",
    "what is love",
    "tell me a joke",
    "why is the sky blue",
    "how old is the universe",
    "how do i write fizzbuzz in clean",
    "is lisp turing complete",
    "which is the best language",
    "what did nonexistent-lang influence",
]


def test_golden_set(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        simple, advanced = _golden(kb)
        assert len(simple) == 25 and len(advanced) == 25
        correct = answered = 0
        for q, want in simple + advanced:
            ans = qa.answer(kb, q)
            if ans.abstained:
                continue
            answered += 1
            assert all(s.cites for s in ans.sentences), q  # 100% of sentences cited
            text = " ".join(s.text for s in ans.sentences) + " ".join(
                c.source for c in ans.citations
            )
            correct += want.lower() in text.lower()
        assert answered >= 45
        assert correct / answered >= 0.9
        abstained = sum(qa.answer(kb, q).abstained for q in OUT_OF_KB)
        assert abstained / len(OUT_OF_KB) >= 0.95


def test_citations_point_at_real_evidence(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        ans = qa.answer(kb, "which languages have macros")
        ids = {a.evidence_id for lang in kb.languages for a in kb.assertions(lang.id)}
    assert ans.citations and all(c.id in ids for c in ans.citations)


def test_guide_cites_every_sentence(kb_home: Path) -> None:
    with KnowledgeBase() as kb:
        g = qa.guide(kb, "scheme")
    assert g.sentences and all(s.cites for s in g.sentences)
    assert g.code and g.code_lang == "scheme"


def test_cli_ask_json_and_extract_keeps_citations(kb_home: Path) -> None:
    r = CliRunner()
    assert r.invoke(app, ["workspace", "init", "w"]).exit_code == 0
    out = r.invoke(app, ["--json", "ask", "does haskell have type inference"])
    data = json.loads(out.stdout)["data"]
    assert out.exit_code == 0 and not data["abstained"] and data["citations"]
    ex = r.invoke(app, ["--json", "extract", "last"])
    finding = json.loads(ex.stdout)["data"]
    assert set(c["id"] for c in data["citations"]) <= set(finding["evidence"])
    plain = r.invoke(app, ["--plain", "ask", "what", "is", "the", "meaning", "of", "life"])
    assert plain.exit_code == 0 and "won't guess" in plain.stdout


@pytest.mark.parametrize("mode", ["concise", "default", "thorough"])
def test_abstain_identical_across_modes(kb_home: Path, mode: str) -> None:
    out = CliRunner().invoke(app, ["--plain", "--mode", mode, "ask", "tell me a joke"])
    assert out.exit_code == 0 and qa.ABSTAIN.split(",")[0] in out.stdout
