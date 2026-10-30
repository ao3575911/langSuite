"""Verified Rosetta evidence: run pack solutions in the sandbox (SPEC §4 Evidence, M4).

A solution counts as verified when one of its page variants passes (exit 0 and, for
tasks with a fixed output, the output matches). Results are content-hash cached.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langsuite.verify.rosetta import Task
from langsuite.verify.sandbox import Docker, Status, VerifyResult, run_code
from langsuite.verify.toolchains import BY_LANG


@dataclass
class SolutionCheck:
    task: Task
    lang: str
    variant: int | None  # index of the passing variant, None if none passed
    tried: int
    result: VerifyResult  # the passing run, or the last failing one

    @property
    def verified(self) -> bool:
        return self.variant is not None

    @property
    def code(self) -> str:
        sol = self.task.solutions[self.lang]
        return sol.variants[self.variant or 0]

    def to_json(self) -> dict[str, Any]:
        return {
            "task": self.task.title,
            "lang": self.lang,
            "verified": self.verified,
            "variant": self.variant,
            "tried": self.tried,
            "attribution": self.task.attribution,
            "result": self.result.to_json(),
        }


def check_solution(
    task: Task,
    lang: str,
    *,
    docker: Docker | None = None,
    pull: bool = True,
    home: Path | None = None,
) -> SolutionCheck:
    tc = BY_LANG[lang]
    sol = task.solutions[lang]
    last: VerifyResult | None = None
    tried = 0
    for i, code in enumerate(sol.variants):
        tried = i + 1
        res = run_code(
            tc, tc.prepare(code), expected=task.expected, docker=docker, pull=pull, home=home
        )
        if res.status is Status.PASS:
            return SolutionCheck(task, lang, i, i + 1, res)
        last = res
        if res.status in {Status.REFUSED, Status.ERROR}:
            break
    assert last is not None
    return SolutionCheck(task, lang, None, tried, last)


def check_many(
    pairs: Iterable[tuple[Task, str]],
    *,
    docker: Docker | None = None,
    pull: bool = True,
    home: Path | None = None,
    workers: int = 4,
    progress: Callable[[SolutionCheck], None] | None = None,
) -> list[SolutionCheck]:
    jobs = [(t, lang) for t, lang in pairs if lang in BY_LANG and lang in t.solutions]

    def one(job: tuple[Task, str]) -> SolutionCheck:
        res = check_solution(job[0], job[1], docker=docker, pull=pull, home=home)
        if progress:
            progress(res)
        return res

    with ThreadPoolExecutor(max(1, workers)) as ex:
        out = list(ex.map(one, jobs))
    return sorted(out, key=lambda c: (c.task.title, c.lang))


def verified_rate(checks: Iterable[SolutionCheck]) -> dict[str, tuple[int, int]]:
    """Per language: (verified, attempted). Feeds the M5c verified-run-rate criterion."""
    out: dict[str, tuple[int, int]] = {}
    for c in checks:
        ok, n = out.get(c.lang, (0, 0))
        out[c.lang] = (ok + int(c.verified), n + 1)
    return out
