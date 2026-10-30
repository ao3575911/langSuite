"""Feature similarity with a shuffled-feature baseline (SPEC §4, §10 M2).

Method `features-idf-jaccard/1`: each language is the set of traits a source asserts it
*has*. Two languages are compared with a weighted Jaccard index where each trait weighs
``1 + ln((N + 1) / (df + 1))``, so sharing a rare trait (homoiconicity) counts more than
sharing a common one (comments). Unknown is not "no": a trait missing from the sources
is simply absent, and languages with fewer than ``min_traits`` known traits are left out
of rankings because their scores would be noise.

Baseline `shuffled-features/2`: in each of ``rounds`` seeded rounds both languages'
trait sets are replaced by random sets of the same size, drawn without replacement in
proportion to how common each trait is. That keeps how much the sources know about each
language and how frequent each trait is, and destroys any real association. ``z`` is how
many standard deviations the real score sits above the shuffled mean.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from langsuite.core.errors import NoResultError
from langsuite.core.kb import KnowledgeBase, Language

METHOD = "features-idf-jaccard/1"
BASELINE_METHOD = "shuffled-features/2"
DEFAULT_K = 10
DEFAULT_MIN_TRAITS = 5
DEFAULT_ROUNDS = 1000
DEFAULT_SEED = 1729


@dataclass(frozen=True)
class Baseline:
    method: str
    rounds: int
    seed: int
    mean: float
    sd: float
    z: float

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Neighbour:
    id: str
    name: str
    score: float
    shared: tuple[str, ...]
    only_query: tuple[str, ...]
    only_other: tuple[str, ...]
    baseline: Baseline | None = None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["baseline"] = self.baseline.to_json() if self.baseline else None
        return data


@dataclass(frozen=True)
class SimilarResult:
    query: Language
    method: str
    snapshot_id: str
    min_traits: int
    known_traits: int
    candidates: int
    neighbours: list[Neighbour] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "query": self.query.to_json(),
            "method": self.method,
            "snapshot_id": self.snapshot_id,
            "min_traits": self.min_traits,
            "known_traits": self.known_traits,
            "candidates": self.candidates,
            "neighbours": [n.to_json() for n in self.neighbours],
        }


class TraitMatrix:
    """Boolean language-by-trait matrix built once per knowledge base."""

    def __init__(self, langs: list[str], traits: list[str], matrix: NDArray[np.bool_]) -> None:
        self.langs = langs
        self.traits = traits
        self.matrix = matrix
        self.index = {lang: i for i, lang in enumerate(langs)}
        n = len(langs)
        df = matrix.sum(axis=0)
        self.weights: NDArray[np.float64] = 1.0 + np.log((n + 1) / (df + 1))
        self.counts: NDArray[np.int64] = matrix.sum(axis=1).astype(np.int64)
        total = max(int(df.sum()), 1)
        with np.errstate(divide="ignore"):
            self._log_freq: NDArray[np.float64] = np.log(df / total)

    @classmethod
    def from_kb(cls, kb: KnowledgeBase) -> TraitMatrix:
        rows = kb.trait_pairs()
        langs = sorted({r[0] for r in rows})
        traits = sorted({r[1] for r in rows})
        li = {lang: i for i, lang in enumerate(langs)}
        ti = {t: i for i, t in enumerate(traits)}
        matrix = np.zeros((len(langs), len(traits)), dtype=bool)
        for lang, trait in rows:
            matrix[li[lang], ti[trait]] = True
        return cls(langs, traits, matrix)

    def traits_of(self, lang_id: str) -> set[str]:
        i = self.index.get(lang_id)
        if i is None:
            return set()
        return {self.traits[j] for j in np.flatnonzero(self.matrix[i])}

    def scores(self, i: int, matrix: NDArray[np.bool_] | None = None) -> NDArray[np.float64]:
        m = self.matrix if matrix is None else matrix
        row = m[i]
        inter = (m & row).astype(np.float64) @ self.weights
        union = (m | row).astype(np.float64) @ self.weights
        out: NDArray[np.float64] = np.divide(
            inter, union, out=np.zeros_like(inter), where=union > 0
        )
        return out

    def pair_score(self, a: int, b: int, matrix: NDArray[np.bool_] | None = None) -> float:
        m = self.matrix if matrix is None else matrix
        inter = float((m[a] & m[b]).astype(np.float64) @ self.weights)
        union = float((m[a] | m[b]).astype(np.float64) @ self.weights)
        return inter / union if union > 0 else 0.0

    def _random_rows(self, rng: np.random.Generator, size: int, rounds: int) -> NDArray[np.bool_]:
        """`rounds` random trait sets of `size` traits, drawn without replacement with
        probability proportional to each trait's frequency (Gumbel top-k)."""
        f = len(self.traits)
        out = np.zeros((rounds, f), dtype=bool)
        if size <= 0:
            return out
        keys = self._log_freq + rng.gumbel(size=(rounds, f))
        top = np.argpartition(-keys, size - 1, axis=1)[:, :size]
        np.put_along_axis(out, top, True, axis=1)
        return out

    def _null_scores(
        self, a: int, b: int, rng: np.random.Generator, rounds: int
    ) -> NDArray[np.float64]:
        va = self._random_rows(rng, int(self.counts[a]), rounds)
        vb = self._random_rows(rng, int(self.counts[b]), rounds)
        inter = (va & vb).astype(np.float64) @ self.weights
        union = (va | vb).astype(np.float64) @ self.weights
        out: NDArray[np.float64] = np.divide(
            inter, union, out=np.zeros_like(inter), where=union > 0
        )
        return out

    def baseline(
        self,
        a: int,
        b: int,
        rounds: int = DEFAULT_ROUNDS,
        seed: int = DEFAULT_SEED,
        chunk: int = 500,
    ) -> Baseline:
        """Pair score against a shuffled-feature null.

        Each round replaces both languages' trait sets with random sets of the same
        size, drawn by trait frequency. This keeps how much is known about each
        language and how common each trait is, and removes any real association.
        """
        rng = np.random.default_rng(seed)
        null = np.concatenate(
            [
                self._null_scores(a, b, rng, min(chunk, rounds - start))
                for start in range(0, rounds, chunk)
            ]
        )
        mean = float(null.mean())
        sd = float(null.std(ddof=1)) if rounds > 1 else 0.0
        real = self.pair_score(a, b)
        z = (real - mean) / sd if sd > 0 else (float("inf") if real > mean else 0.0)
        return Baseline(BASELINE_METHOD, rounds, seed, round(mean, 4), round(sd, 4), round(z, 2))


def _require(tm: TraitMatrix, lang: Language) -> int:
    i = tm.index.get(lang.id)
    if i is None:
        raise NoResultError(
            f"No feature data for {lang.name} yet, so similarity can't be computed.",
            hint=f"See what is known with `langsuite lang show {lang.id} --evidence`.",
        )
    return i


def similar(
    kb: KnowledgeBase,
    query: str,
    k: int = DEFAULT_K,
    min_traits: int = DEFAULT_MIN_TRAITS,
    baseline: bool = False,
    rounds: int = DEFAULT_ROUNDS,
    seed: int = DEFAULT_SEED,
    matrix: TraitMatrix | None = None,
) -> SimilarResult:
    """Top-k languages by feature similarity. Deterministic: ties break by id."""
    lang = kb.resolve(query)
    tm = matrix or kb.trait_matrix()
    i = _require(tm, lang)
    scores = tm.scores(i)
    eligible = [j for j in range(len(tm.langs)) if j != i and tm.counts[j] >= min_traits]
    ranked = sorted(eligible, key=lambda j: (-round(float(scores[j]), 12), tm.langs[j]))
    mine = tm.traits_of(lang.id)
    out: list[Neighbour] = []
    for j in ranked[: max(k, 0)]:
        other_id = tm.langs[j]
        other = kb.language(other_id)
        theirs = tm.traits_of(other_id)
        out.append(
            Neighbour(
                id=other_id,
                name=other.name if other else other_id,
                score=round(float(scores[j]), 4),
                shared=tuple(sorted(mine & theirs)),
                only_query=tuple(sorted(mine - theirs)),
                only_other=tuple(sorted(theirs - mine)),
                baseline=tm.baseline(i, j, rounds, seed) if baseline else None,
            )
        )
    return SimilarResult(
        query=lang,
        method=METHOD,
        snapshot_id=kb.manifest.snapshot_id,
        min_traits=min_traits,
        known_traits=len(mine),
        candidates=len(eligible),
        neighbours=out,
    )


def compare_pair(
    kb: KnowledgeBase,
    a: str,
    b: str,
    rounds: int = DEFAULT_ROUNDS,
    seed: int = DEFAULT_SEED,
) -> Neighbour:
    """Score one pair against its shuffled baseline."""
    la, lb = kb.resolve(a), kb.resolve(b)
    tm = kb.trait_matrix()
    i, j = _require(tm, la), _require(tm, lb)
    ta, tb = tm.traits_of(la.id), tm.traits_of(lb.id)
    return Neighbour(
        id=lb.id,
        name=lb.name,
        score=round(tm.pair_score(i, j), 4),
        shared=tuple(sorted(ta & tb)),
        only_query=tuple(sorted(ta - tb)),
        only_other=tuple(sorted(tb - ta)),
        baseline=tm.baseline(i, j, rounds, seed),
    )
