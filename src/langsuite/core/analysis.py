"""Clusters, labels, influence, code similarity and scores (SPEC §10 M5, M5b, M5c).

Everything here is deterministic: same snapshot, same arguments, same seed -> same output.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import cache
from importlib import resources
from typing import Any

import numpy as np
import yaml
from numpy.typing import NDArray

from langsuite.core import defaults
from langsuite.core.errors import DataError, NoResultError, UsageError
from langsuite.core.kb import KnowledgeBase, Language

CLUSTER_METHOD = "k-medoids/idf-jaccard/1"
CODE_METHOD = "code-shingles-jaccard/1"
DEFAULT_TOP = defaults.ANALYSIS_TOP
DEFAULT_BOOT = defaults.ANALYSIS_BOOT
DEFAULT_SEED = defaults.ANALYSIS_SEED
MATCH = 0.75  # a bootstrap cluster "is" the original if member Jaccard >= this

# ----- feature similarity matrix ---------------------------------------------------------


def _sim_matrix(m: NDArray[np.bool_], w: NDArray[np.float64]) -> NDArray[np.float64]:
    mf = m.astype(np.float64)
    inter = (mf * w) @ mf.T
    tot = mf @ w
    union = tot[:, None] + tot[None, :] - inter
    out: NDArray[np.float64] = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
    return out


def _average_linkage(dist: NDArray[np.float64], k: int) -> list[list[int]]:
    n = len(dist)
    clusters: dict[int, list[int]] = {i: [i] for i in range(n)}
    d = dist.astype(np.float64).copy()
    np.fill_diagonal(d, np.inf)
    alive = np.ones(n, dtype=bool)
    while len(clusters) > k:
        masked = np.where(alive[:, None] & alive[None, :], d, np.inf)
        flat = int(np.argmin(masked))
        i, j = divmod(flat, n)
        if i > j:
            i, j = j, i
        si, sj = len(clusters[i]), len(clusters[j])
        row = (si * d[i] + sj * d[j]) / (si + sj)
        d[i, :] = row
        d[:, i] = row
        d[i, i] = np.inf
        alive[j] = False
        d[j, :] = np.inf
        d[:, j] = np.inf
        clusters[i] = sorted(clusters[i] + clusters.pop(j))
    return sorted(clusters.values(), key=lambda c: (-len(c), c[0]))


def _kmedoids(dist: NDArray[np.float64], k: int, iters: int = 50) -> list[list[int]]:
    """Deterministic k-medoids: farthest-first start from the global medoid, then alternate."""
    meds = [int(np.argmin(dist.sum(axis=1)))]
    while len(meds) < k:
        meds.append(int(np.argmax(dist[:, meds].min(axis=1))))
    for _ in range(iters):
        assign = np.argmin(dist[:, meds], axis=1)
        new = []
        for c in range(k):
            members = np.flatnonzero(assign == c)
            if len(members) == 0:
                new.append(meds[c])
                continue
            sub = dist[np.ix_(members, members)].sum(axis=1)
            new.append(int(members[int(np.argmin(sub))]))
        if new == meds:
            break
        meds = new
    assign = np.argmin(dist[:, meds], axis=1)
    groups = [sorted(int(i) for i in np.flatnonzero(assign == c)) for c in range(k)]
    return sorted((g for g in groups if g), key=lambda g: (-len(g), g[0]))


def _silhouette(dist: NDArray[np.float64], groups: list[list[int]]) -> float:
    label = np.empty(len(dist), dtype=int)
    for g, members in enumerate(groups):
        label[members] = g
    scores = []
    for i in range(len(dist)):
        own = [j for j in groups[label[i]] if j != i]
        if not own:
            scores.append(0.0)
            continue
        a = float(dist[i, own].mean())
        b = min(float(dist[i, g].mean()) for n, g in enumerate(groups) if n != label[i])
        scores.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return float(np.mean(scores))


def _jaccard(a: set[Any], b: set[Any]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


@dataclass
class LabelWord:
    trait: str
    share: float  # fraction of members with the trait
    lift: float  # share in cluster minus share outside
    evidence: dict[str, list[str]] = field(default_factory=dict)  # member -> evidence ids


@dataclass
class Cluster:
    number: int
    members: list[str]
    names: list[str]
    medoid: str
    support: float  # bootstrap support, 0..1
    cohesion: float  # mean within-cluster similarity
    label: list[LabelWord] = field(default_factory=list)
    name: str = ""  # user rename, if any

    @property
    def title(self) -> str:
        return self.name or " · ".join(w.trait for w in self.label) or "(no shared traits)"

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["title"] = self.title
        return d


@dataclass
class Clustering:
    clusters: list[Cluster]
    k: int
    silhouette: float
    rounds: int
    seed: int
    languages: int
    snapshot_id: str
    method: str = CLUSTER_METHOD
    disagreements: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "k": self.k,
            "silhouette": round(self.silhouette, 4),
            "bootstrap": {"rounds": self.rounds, "seed": self.seed, "match": MATCH},
            "languages": self.languages,
            "snapshot": self.snapshot_id,
            "clusters": [c.to_json() for c in self.clusters],
            "disagreements": self.disagreements,
        }


def _pick_langs(kb: KnowledgeBase, top: int, min_traits: int, only: list[str] | None) -> list[str]:
    tm = kb.trait_matrix()
    if only:
        ids = [kb.resolve(x).id for x in only]
        return [i for i in ids if i in tm.index]
    ok = [lang for lang in tm.langs if tm.counts[tm.index[lang]] >= min_traits]
    by = kb._by_id
    ok.sort(key=lambda lang: (by[lang].rank or 10**9, lang) if lang in by else (10**9, lang))
    return sorted(ok[:top])


def cluster(
    kb: KnowledgeBase,
    k: int | None = None,
    top: int = DEFAULT_TOP,
    min_traits: int = 10,
    rounds: int = DEFAULT_BOOT,
    seed: int = DEFAULT_SEED,
    only: list[str] | None = None,
    names: dict[str, str] | None = None,
) -> Clustering:
    tm = kb.trait_matrix()
    langs = _pick_langs(kb, top, min_traits, only)
    if len(langs) < 3:
        raise NoResultError(
            "Too few languages with enough known traits to cluster.", hint="Lower --min-traits."
        )
    idx = [tm.index[lang] for lang in langs]
    m = tm.matrix[idx]
    sim = _sim_matrix(m, tm.weights)
    dist = 1.0 - sim
    groups: list[list[int]]
    if k is None:
        best: tuple[float, int, list[list[int]]] | None = None
        for cand in range(min(4, len(langs) - 1), min(12, len(langs) - 1) + 1):
            cand_groups = _kmedoids(dist, cand)
            sc = _silhouette(dist, cand_groups)
            if best is None or sc > best[0] + 1e-12:
                best = (sc, cand, cand_groups)
        assert best is not None
        sil, k, groups = best
    else:
        if not 1 <= k < len(langs):
            raise UsageError(f"--k must be between 1 and {len(langs) - 1}.")
        groups = _kmedoids(dist, k)
        sil = _silhouette(dist, groups) if k > 1 else 0.0
    # bootstrap over traits
    rng = np.random.default_rng(seed)
    hits = [0] * len(groups)
    sets = [set(g) for g in groups]
    ntraits = m.shape[1]
    for _ in range(rounds):
        counts = np.bincount(rng.integers(0, ntraits, ntraits), minlength=ntraits)
        bsim = _sim_matrix(m, tm.weights * counts)
        bgroups = [set(g) for g in _kmedoids(1.0 - bsim, k)]
        for n, orig in enumerate(sets):
            if any(_jaccard(orig, b) >= MATCH for b in bgroups):
                hits[n] += 1
    by = kb._by_id
    out: list[Cluster] = []
    present = m.astype(np.float64)
    for n, g in enumerate(groups):
        members = [langs[i] for i in g]
        sub = sim[np.ix_(g, g)]
        medoid = members[int(np.argmax(sub.sum(axis=1)))]
        coh = float((sub.sum() - len(g)) / (len(g) * (len(g) - 1))) if len(g) > 1 else 1.0
        c = Cluster(
            n + 1,
            members,
            [by[x].name if x in by else x for x in members],
            medoid,
            hits[n] / rounds if rounds else 1.0,
            coh,
        )
        c.label = _label(kb, tm.traits, present, g, members)
        c.name = (names or {}).get(medoid, "")
        out.append(c)
    result = Clustering(out, k, sil, rounds, seed, len(langs), kb.manifest.snapshot_id)
    result.disagreements = disagreements(kb, out)
    return result


def _label(
    kb: KnowledgeBase,
    traits: list[str],
    present: NDArray[np.float64],
    g: list[int],
    members: list[str],
    n: int = 3,
) -> list[LabelWord]:
    inside = present[g].mean(axis=0)
    rest = [i for i in range(len(present)) if i not in set(g)]
    outside = present[rest].mean(axis=0) if rest else np.zeros_like(inside)
    lift = inside - outside
    order = sorted(range(len(traits)), key=lambda t: (-round(float(lift[t]), 9), traits[t]))
    words: list[LabelWord] = []
    for t in order:
        if inside[t] < 0.5 or lift[t] <= 0:
            continue
        ev: dict[str, list[str]] = {}
        for lang in members:
            ids = [a.evidence_id for a in kb.assertions(lang) if a.feature_id == traits[t]]
            if ids:
                ev[lang] = ids
        if ev:  # every label word must be backed by a sourced assertion
            words.append(LabelWord(traits[t], float(inside[t]), float(lift[t]), ev))
        if len(words) == n:
            break
    return words


# ----- influence -------------------------------------------------------------------------


@dataclass
class InfluenceNode:
    id: str
    name: str
    depth: int  # negative: influenced this language; positive: influenced by it
    via: str
    source_url: str


def influence(
    kb: KnowledgeBase, query: str, depth: int = 2
) -> tuple[Language, list[InfluenceNode]]:
    lang = kb.resolve(query)
    by = kb._by_id
    out: list[InfluenceNode] = []
    for sign in (-1, 1):
        seen = {lang.id}
        frontier = [lang.id]
        for d in range(1, depth + 1):
            nxt = []
            for cur in frontier:
                into, out_of = kb.edges(cur)
                edges = into if sign < 0 else out_of
                for e in sorted(edges, key=lambda e: (e.src, e.dst)):
                    other = e.src if sign < 0 else e.dst
                    if other in seen:
                        continue
                    seen.add(other)
                    nxt.append(other)
                    name = by[other].name if other in by else other
                    out.append(InfluenceNode(other, name, sign * d, cur, e.source_url))
            frontier = nxt
    return lang, out


# ----- code similarity ---------------------------------------------------------------------

_TOKEN = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\d+(?:\.\d+)?|\w+|[^\s\w]")


def tokens(code: str) -> list[str]:
    out = []
    for t in _TOKEN.findall(code):
        if t[0] in "\"'":
            out.append("S")
        elif t[0].isdigit():
            out.append("N")
        else:
            out.append(t.lower())
    return out


def shingles(code: str, n: int = 3) -> set[tuple[str, ...]]:
    t = tokens(code)
    return {tuple(t[i : i + n]) for i in range(max(len(t) - n + 1, 1))} if t else set()


@dataclass
class CodeNeighbour:
    id: str
    score: float
    tasks: int  # tasks both have solutions for


def code_profiles(tasks: dict[str, Any]) -> dict[str, dict[str, set[tuple[str, ...]]]]:
    prof: dict[str, dict[str, set[tuple[str, ...]]]] = {}
    for slug, task in sorted(tasks.items()):
        for lang, sol in task.solutions.items():
            prof.setdefault(lang, {})[slug] = shingles(sol.code)
    return prof


def code_similar(
    tasks: dict[str, Any], lang: str, k: int = 10, min_tasks: int = 2
) -> list[CodeNeighbour]:
    prof = code_profiles(tasks)
    if lang not in prof:
        raise NoResultError(
            f"No Rosetta Code solutions for {lang} in the installed packs.",
            hint="Fetch more tasks with `langsuite snippet --fetch <task>`.",
        )
    mine = prof[lang]
    out = []
    for other, theirs in prof.items():
        if other == lang:
            continue
        common = sorted(mine.keys() & theirs.keys())
        if len(common) < min_tasks:
            continue
        score = float(np.mean([_jaccard(mine[t], theirs[t]) for t in common]))
        out.append(CodeNeighbour(other, score, len(common)))
    out.sort(key=lambda c: (-c.score, c.id))
    return out[:k]


def pair_code_score(tasks: dict[str, Any], a: str, b: str) -> tuple[float, int] | None:
    prof = code_profiles(tasks)
    if a not in prof or b not in prof:
        return None
    common = sorted(prof[a].keys() & prof[b].keys())
    if not common:
        return None
    return float(np.mean([_jaccard(prof[a][t], prof[b][t]) for t in common])), len(common)


def disagreements(
    kb: KnowledgeBase, clusters: list[Cluster], limit: int = 10
) -> list[dict[str, Any]]:
    """Pairs in one feature cluster whose code looks unlike, and vice versa (M5)."""
    from langsuite.verify.rosetta import load_tasks

    try:
        tasks = load_tasks()
    except (OSError, DataError):
        return []
    prof = code_profiles(tasks)
    tm = kb.trait_matrix()
    where = {m: c.number for c in clusters for m in c.members}
    langs = sorted(lang for lang in where if lang in prof)
    pairs = []
    for i, a in enumerate(langs):
        for b in langs[i + 1 :]:
            common = sorted(prof[a].keys() & prof[b].keys())
            if len(common) < 2:
                continue
            code = float(np.mean([_jaccard(prof[a][t], prof[b][t]) for t in common]))
            feat = tm.pair_score(tm.index[a], tm.index[b])
            pairs.append((a, b, feat, code, where[a] == where[b]))
    if len(pairs) < 3:
        return []
    feats = np.array([p[2] for p in pairs])
    codes = np.array([p[3] for p in pairs])
    zf = (feats - feats.mean()) / (feats.std() or 1.0)
    zc = (codes - codes.mean()) / (codes.std() or 1.0)
    out: list[dict[str, Any]] = []
    for (a, b, f, c, same), x, y in zip(pairs, zf, zc, strict=True):
        gap = float(x - y)
        if abs(gap) >= 1.5:
            kind = "features alike, code unlike" if gap > 0 else "code alike, features unlike"
            out.append(
                {
                    "a": a,
                    "b": b,
                    "features": round(f, 3),
                    "code": round(c, 3),
                    "same_cluster": same,
                    "gap_z": round(gap, 2),
                    "kind": kind,
                }
            )
    out.sort(key=lambda d: (-abs(d["gap_z"]), d["a"], d["b"]))
    return out[:limit]


# ----- scores and grades -------------------------------------------------------------------


@cache
def criteria() -> dict[str, Any]:
    text = resources.files("langsuite.core").joinpath("data/criteria.yaml").read_text("utf-8")
    data: dict[str, Any] = yaml.safe_load(text)
    return data


def grade(total: float) -> str:
    for cut, letter in criteria()["grades"]:
        if total >= cut:
            return str(letter)
    return "E"


GRADE_ORDER = "EDCBA"


@dataclass
class Criterion:
    id: str
    label: str
    points: float | None  # None: missing (no stated data), never counted as zero
    basis: list[str]


@dataclass
class Score:
    lang: str
    name: str
    criteria: list[Criterion]
    total: float  # unrounded mean of present criteria
    n: int
    confidence: float
    grade: str
    custom: float | None = None
    method: str = "criteria/1"

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _max_rank(kb: KnowledgeBase) -> int:
    ranks = [lang.rank for lang in kb.languages if lang.rank]
    return max(ranks) if ranks else 1


def score(
    kb: KnowledgeBase,
    lang: Language,
    profile: dict[str, float] | None = None,
    now_year: int | None = None,
    _cache: dict[str, Any] | None = None,
) -> Score:
    cfg = criteria()
    cache_ = _cache if _cache is not None else {}
    if "values" not in cache_:
        cache_["values"] = kb.trait_values()
        cache_["max_rank"] = _max_rank(kb)
    values: dict[str, str] = cache_["values"].get(lang.id, {})
    year = now_year or (
        int(kb.manifest.built_at[:4]) if kb.manifest.built_at else datetime.now(UTC).year
    )
    out: list[Criterion] = []
    for cid, spec in cfg["criteria"].items():
        label = spec["label"]
        if spec.get("rank"):
            if lang.rank:
                mr = max(cache_["max_rank"], 2)
                pts = 100.0 * (1.0 - math.log(lang.rank) / math.log(mr))
                out.append(Criterion(cid, label, max(0.0, pts), [f"rank {lang.rank} of {mr}"]))
            else:
                out.append(Criterion(cid, label, None, []))
            continue
        if "age" in spec:
            if lang.appeared:
                pts = min(100.0, 100.0 * max(0, year - lang.appeared) / spec["age"])
                out.append(Criterion(cid, label, pts, [f"appeared {lang.appeared}"]))
            else:
                out.append(Criterion(cid, label, None, []))
            continue
        plus, minus = spec.get("plus", []), spec.get("minus", [])
        known_plus = [t for t in plus if t in values]
        known_minus = [t for t in minus if t in values]
        if not known_plus and not known_minus:
            out.append(Criterion(cid, label, None, []))
            continue
        yes_plus = [t for t in known_plus if values[t] != "no"]
        yes_minus = [t for t in known_minus if values[t] != "no"]
        raw = len(yes_plus) / max(len(plus), 1) * 100.0 * 2.0  # half the list = full marks
        raw -= 25.0 * len(yes_minus)
        basis = [f"+{t}" for t in yes_plus] + [f"-{t}" for t in yes_minus]
        out.append(Criterion(cid, label, float(min(100.0, max(0.0, raw))), basis))
    present = [c for c in out if c.points is not None]
    total = float(np.mean([c.points for c in present])) if present else 0.0
    custom = None
    if profile:
        ws = [(profile.get(c.id, 0.0), c.points) for c in present]
        den = sum(w for w, _ in ws)
        custom = sum(w * float(p or 0) for w, p in ws) / den if den > 0 else None
    n = len(present)
    return Score(lang.id, lang.name, out, total, n, n / len(out), grade(total), custom)


def paradigms(values: dict[str, str]) -> list[str]:
    out = []
    for name, traits in criteria()["paradigms"].items():
        if sum(1 for t in traits if values.get(t, "no") != "no") >= 2:
            out.append(name)
    return out


_GRADE_FILTER = re.compile(r"grade(>=|<=|=|>|<)([A-Ea-e])")
_SCORE_FILTER = re.compile(r"score(>=|<=|=|>|<)(\d+(?:\.\d+)?)")
_BAD_SCORE_FILTER = re.compile(r"\b(?:grade|score)\s*(?:>=|<=|=|>|<)?\S*")
_PARADIGM_FILTER = re.compile(r"paradigm=([a-z-]+)")


def _cmp(a: float, op: str, b: float) -> bool:
    return {">=": a >= b, "<=": a <= b, "=": a == b, ">": a > b, "<": a < b}[op]


@dataclass
class Ranking:
    rows: list[Score]
    by: str
    descending: bool
    filter: str
    total: int
    snapshot_id: str
    method: str = "criteria/1"

    def to_json(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "by": self.by,
            "descending": self.descending,
            "filter": self.filter,
            "total": self.total,
            "snapshot": self.snapshot_id,
            "rows": [r.to_json() for r in self.rows],
        }


def rank(
    kb: KnowledgeBase,
    by: str = "score",
    descending: bool = True,
    top: int = 10,
    filter_text: str = "",
    profile: dict[str, float] | None = None,
    min_n: int = 3,
) -> Ranking:
    from langsuite.core import query as q

    rest = filter_text
    conds: list[tuple[str, str, str]] = []
    for rx, kind in ((_GRADE_FILTER, "grade"), (_SCORE_FILTER, "score")):
        for mt in rx.finditer(filter_text):
            conds.append((kind, mt.group(1), mt.group(2)))
        rest = rx.sub(" ", rest)
    bad = _BAD_SCORE_FILTER.search(rest)
    if bad:
        raise UsageError(
            f"Bad filter `{bad.group(0)}`.",
            hint="Grades run A to E (grade>=B); scores are numbers (score>=70).",
        )
    para = _PARADIGM_FILTER.findall(rest)
    rest = _PARADIGM_FILTER.sub(" ", rest).strip()
    if by == "custom" and not profile:
        raise UsageError("No scoring profile: set one with `langsuite settings profile ...`.")
    allowed: set[str] | None = None
    if rest:
        allowed = {r.language.id for r in q.run(kb, rest, top=100000).rows}
    cache_: dict[str, Any] = {}
    values = kb.trait_values()
    rows = []
    for lang in kb.languages:
        if allowed is not None and lang.id not in allowed:
            continue
        if para and not set(para) <= set(paradigms(values.get(lang.id, {}))):
            continue
        s = score(kb, lang, profile, _cache=cache_)
        if s.n < min_n:
            continue
        ok = True
        for kind, op, val in conds:
            if kind == "grade":
                ok &= _cmp(GRADE_ORDER.index(s.grade), op, GRADE_ORDER.index(val.upper()))
            else:
                ok &= _cmp(s.total, op, float(val))
        if ok:
            rows.append(s)

    def key(s: Score) -> tuple[float, str]:
        v = s.custom if by == "custom" else s.total
        return (float(v or 0.0), s.lang)

    rows.sort(key=key, reverse=descending)
    if descending:  # ties broken by id ascending in both directions
        rows.sort(key=lambda s: (-key(s)[0], s.lang))
    else:
        rows.sort(key=lambda s: (key(s)[0], s.lang))
    total = len(rows)
    return Ranking(rows[:top], by, descending, filter_text, total, kb.manifest.snapshot_id)


def fingerprint(obj: Any) -> str:
    return hashlib.sha256(repr(obj).encode()).hexdigest()[:16]
