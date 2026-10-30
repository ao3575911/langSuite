"""Cited questions and guides (SPEC M5d).

Answers are built only from the knowledge base and the Rosetta pack, never generated
free-form: each sentence carries the citations it rests on, and anything the base cannot
support is an abstention. Method `kb-templates/1`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from langsuite.core.errors import NoResultError
from langsuite.core.kb import Assertion, KnowledgeBase, Language

METHOD = "kb-templates/1"
PLDB = "https://pldb.io/concepts/{}.html"
ABSTAIN = (
    "I can't answer that from the knowledge base, so I won't guess. "
    "Try `langsuite lang show <lang>`, `feature list`, or `snippet <task> --lang <lang>`."
)


@dataclass(frozen=True)
class Citation:
    id: str
    source: str
    url: str
    excerpt: str


@dataclass
class Sentence:
    text: str
    cites: list[Citation] = field(default_factory=list)


@dataclass
class Answer:
    question: str
    intent: str
    sentences: list[Sentence]
    abstained: bool = False
    code: str = ""
    code_lang: str = ""
    snapshot: str = ""

    @property
    def citations(self) -> list[Citation]:
        seen: dict[str, Citation] = {}
        for s in self.sentences:
            for c in s.cites:
                seen.setdefault(c.id, c)
        return list(seen.values())

    def to_json(self) -> dict[str, Any]:
        order = {c.id: n for n, c in enumerate(self.citations, 1)}
        return {
            "method": METHOD,
            "question": self.question,
            "intent": self.intent,
            "abstained": self.abstained,
            "sentences": [
                {"text": s.text, "cites": [order[c.id] for c in s.cites]} for s in self.sentences
            ],
            "citations": [{"n": order[c.id], **c.__dict__} for c in self.citations],
            "code": self.code,
            "code_lang": self.code_lang,
            "snapshot": self.snapshot,
        }


def _fact(lang: Language, field_: str, value: object) -> Citation:
    key = f"{lang.id}\x1f{field_}\x1f{value}"
    cid = "fact-" + hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:12]
    src = "PLDB" if any("pldb" in s.lower() for s in lang.sources) else ", ".join(lang.sources)
    return Citation(cid, src, PLDB.format(lang.id), f"{field_}: {value}")


def _ev(a: Assertion) -> Citation:
    return Citation(
        a.evidence_id, a.source, a.source_url, a.excerpt or f"{a.feature_id}: {a.value}"
    )


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().rstrip("?!. "))


def _lang(kb: KnowledgeBase, text: str) -> Language | None:
    text = text.strip().strip("'\"`").removeprefix("the ").removesuffix(" language").strip()
    if not text:
        return None
    try:
        return kb.resolve(text)
    except NoResultError:
        return None


KINDS = {
    "pl": "programming language",
    "textMarkup": "markup language",
    "queryLanguage": "query language",
}

_FEATURE_FORMS = ("{}", "{}s", "{}-evaluation", "{}-typing", "{}-types", "{}-notation")


def _feature(kb: KnowledgeBase, text: str) -> str | None:
    q = re.sub(r"^(an? |the )", "", text.strip()).replace(" ", "-").replace("_", "-")
    q = re.sub(r"(-evaluation|-typing)$", r"\1", q)
    ids = {f.id: f for f in kb.features}
    labels = {f.label.lower().replace(" ", "-"): f.id for f in kb.features}
    for form in _FEATURE_FORMS:
        cand = form.format(q)
        if cand in ids:
            return cand
        if cand in labels:
            return labels[cand]
    if q.endswith("s") and q[:-1] in ids:
        return q[:-1]
    return None


# (intent, pattern); first match wins. Language and feature names are validated after.
_PATTERNS: tuple[tuple[str, str], ...] = (
    ("howto", r"^(?:how (?:do i|do you|to|would i|can i)|show(?: me)?)\s+(?:write |do |implement |code )?(?P<task>.+?) in (?P<lang>.+)$"),  # noqa: E501
    ("when", r"^(?:when (?:was|did) (?P<lang>.+?) (?:created|released|first appear(?:ed)?|appear|come out|made|designed)|how old is (?P<lang2>.+))$"),  # noqa: E501
    ("who", r"^who (?:created|designed|made|invented|wrote) (?P<lang>.+)$"),
    ("which", r"^(?:which|what) languages (?:have|support|use|offer|feature) (?P<feat>.+)$"),
    ("has", r"^(?:does|do|can) (?P<lang>.+?) (?:have|support|use|offer|do) (?P<feat>.+)$"),
    ("is", r"^is (?P<lang>.+?) (?P<feat>[a-z][a-z -]+)$"),
    ("influenced_by", r"^(?:what|which languages?) (?:influenced|inspired|shaped) (?P<lang>.+)$"),
    ("influenced", r"^(?:what|which languages?) (?:did|has) (?P<lang>.+?) (?:influence|inspire|shape)d?$"),  # noqa: E501
    ("what", r"^(?:what is|what's|tell me about|describe) (?P<lang>.+)$"),
)  # fmt: skip


def answer(kb: KnowledgeBase, question: str, tasks: dict[str, Any] | None = None) -> Answer:
    q = _clean(question)
    for intent, pat in _PATTERNS:
        m = re.match(pat, q)
        if not m:
            continue
        g = {k: v for k, v in m.groupdict().items() if v}
        out = _HANDLERS[intent](kb, g, tasks)
        if out is not None:
            out.question, out.snapshot = question.strip(), kb.manifest.snapshot_id
            return out
    return Answer(
        question.strip(), "abstain", [Sentence(ABSTAIN)], True, snapshot=kb.manifest.snapshot_id
    )


def _when(kb: KnowledgeBase, g: dict[str, str], _t: Any) -> Answer | None:
    lang = _lang(kb, g.get("lang") or g.get("lang2", ""))
    if lang is None or lang.appeared is None:
        return None
    return Answer(
        "",
        "when",
        [
            Sentence(
                f"{lang.name} first appeared in {lang.appeared}.",
                [_fact(lang, "appeared", lang.appeared)],
            )
        ],
    )


def _who(kb: KnowledgeBase, g: dict[str, str], _t: Any) -> Answer | None:
    lang = _lang(kb, g["lang"])
    if lang is None or not lang.creators:
        return None
    return Answer(
        "",
        "who",
        [
            Sentence(
                f"{lang.name} was created by {lang.creators}.",
                [_fact(lang, "creators", lang.creators)],
            )
        ],
    )


def _what(kb: KnowledgeBase, g: dict[str, str], _t: Any) -> Answer | None:
    lang = _lang(kb, g["lang"])
    if lang is None:
        return None
    bits = [
        Sentence(
            f"{lang.name} is a {KINDS.get(lang.kind, lang.kind or 'language')} in the knowledge base.",  # noqa: E501
            [_fact(lang, "kind", lang.kind)],
        )
    ]
    if lang.appeared:
        bits.append(
            Sentence(
                f"It first appeared in {lang.appeared}.", [_fact(lang, "appeared", lang.appeared)]
            )
        )
    if lang.creators:
        bits.append(
            Sentence(
                f"It was created by {lang.creators}.", [_fact(lang, "creators", lang.creators)]
            )
        )
    yes = [a for a in kb.assertions(lang.id) if a.value == "yes"][:5]
    if yes:
        names = ", ".join(a.feature_id for a in yes)
        bits.append(Sentence(f"Sourced traits include {names}.", [_ev(a) for a in yes]))
    return Answer("", "what", bits)


def _has(kb: KnowledgeBase, g: dict[str, str], _t: Any) -> Answer | None:
    lang, feat = _lang(kb, g["lang"]), _feature(kb, g["feat"])
    if lang is None or feat is None:
        return None
    rows = [a for a in kb.assertions(lang.id) if a.feature_id == feat]
    if not rows or rows[0].value not in ("yes", "no"):
        return None  # unknown: abstain rather than infer from silence
    a = rows[0]
    verb = "has" if a.value == "yes" else "does not have"
    return Answer(
        "",
        "has",
        [
            Sentence(
                f"Yes: {lang.name} {verb} {feat}."
                if a.value == "yes"
                else f"No: {lang.name} {verb} {feat}.",
                [_ev(a)],
            )
        ],
    )


def _which(kb: KnowledgeBase, g: dict[str, str], _t: Any) -> Answer | None:
    feat = _feature(kb, g["feat"])
    if feat is None:
        return None
    langs = kb.languages_with(feat)
    if not langs:
        return None
    top = sorted(langs, key=lambda x: (x.rank is None, x.rank or 0, x.id))[:8]
    cites = []
    for lang in top:
        cites += [
            _ev(a) for a in kb.assertions(lang.id) if a.feature_id == feat and a.value == "yes"
        ][:1]
    names = ", ".join(x.name for x in top)
    more = f" ({len(langs)} in total; best known first)" if len(langs) > len(top) else ""
    return Answer("", "which", [Sentence(f"Languages with {feat}: {names}{more}.", cites)])


def _influence(kb: KnowledgeBase, g: dict[str, str], _t: Any, up: bool) -> Answer | None:
    lang = _lang(kb, g["lang"])
    if lang is None:
        return None
    parents, children = kb.edges(lang.id)
    edges = parents if up else children
    if not edges:
        return None
    other = [e.src if up else e.dst for e in edges]
    names = ", ".join((kb.language(i).name if kb.language(i) else i) for i in other[:10])  # type: ignore[union-attr]
    cites = [
        Citation(
            "edge-"
            + hashlib.sha1(f"{e.src}>{e.dst}".encode(), usedforsecurity=False).hexdigest()[:12],
            e.source,
            e.source_url,
            f"{e.src} influenced {e.dst}",
        )
        for e in edges[:10]
    ]
    text = f"{lang.name} was influenced by {names}." if up else f"{lang.name} influenced {names}."
    return Answer("", "influenced_by" if up else "influenced", [Sentence(text, cites)])


def _howto(kb: KnowledgeBase, g: dict[str, str], tasks: dict[str, Any] | None) -> Answer | None:
    from langsuite.verify import rosetta

    lang = _lang(kb, g["lang"])
    if lang is None:
        return None
    tasks = tasks if tasks is not None else rosetta.load_tasks()
    try:
        task = rosetta.find_task(tasks, g["task"])
    except Exception:
        return None
    sol = task.solutions.get(lang.id)
    if sol is None:
        return None
    cite = Citation(f"rc-{task.revid}-{lang.id}", "Rosetta Code", task.permalink, task.attribution)
    return Answer(
        "",
        "howto",
        [
            Sentence(
                f"Here is {task.title} in {lang.name} from Rosetta Code (not verified here; run `langsuite snippet {task.slug} --lang {lang.id}` to check it).",  # noqa: E501
                [cite],
            )
        ],
        code=sol.code,
        code_lang=lang.id,
    )


_HANDLERS = {
    "when": _when,
    "who": _who,
    "what": _what,
    "has": _has,
    "is": _has,
    "which": _which,
    "influenced_by": lambda kb, g, t: _influence(kb, g, t, True),
    "influenced": lambda kb, g, t: _influence(kb, g, t, False),
    "howto": _howto,
}


def guide(kb: KnowledgeBase, lang_q: str, tasks: dict[str, Any] | None = None) -> Answer:
    """How to start with a language, and when it fits, from sourced facts only."""
    from langsuite.core import analysis as an
    from langsuite.verify import rosetta

    lang = kb.resolve(lang_q)
    out = _what(kb, {"lang": lang.id}, None) or Answer("", "guide", [])
    out.intent, out.question, out.snapshot = "guide", f"guide {lang.id}", kb.manifest.snapshot_id
    s = an.score(kb, lang)
    used = {b.lstrip("+-") for c in s.criteria for b in c.basis}
    basis = [_ev(a) for a in kb.assertions(lang.id) if a.feature_id in used]
    if lang.rank is not None:
        basis.append(_fact(lang, "rank", lang.rank))
    if lang.appeared is not None:
        basis.append(_fact(lang, "appeared", lang.appeared))
    if s.n:
        out.sentences.append(
            Sentence(
                f"On criteria/1 it scores {s.total:.1f} ({s.grade}) from {s.n} of {len(s.criteria)} criteria; see `langsuite compare {lang.id} <other>`.",  # noqa: E501
                basis or [_fact(lang, "rank", lang.rank)],
            )
        )
    tasks = tasks if tasks is not None else rosetta.load_tasks()
    have = sorted(t.title for t in tasks.values() if lang.id in t.solutions)
    if have:
        first = next(t for t in tasks.values() if t.title == have[0])
        out.sentences.append(
            Sentence(
                f"Rosetta examples to start from: {', '.join(have)}.",
                [
                    Citation(
                        f"rc-{first.revid}-{lang.id}",
                        "Rosetta Code",
                        first.permalink,
                        first.attribution,
                    )
                ],
            )
        )
        out.code, out.code_lang = first.solutions[lang.id].code, lang.id
    return out
