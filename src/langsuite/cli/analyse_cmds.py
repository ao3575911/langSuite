"""cluster, dashboard, influence, like, rank, compare, diff (SPEC §7, §10 M5-M5c)."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.markup import escape
from rich.table import Table

from langsuite.cli.kb_cmds import _console, _emit, _json, _mode
from langsuite.core import analysis as an
from langsuite.core import similarity as sim
from langsuite.core.errors import NoResultError, UsageError
from langsuite.core.modes import Mode
from langsuite.core.workspace import Workspace, _read, _write, open_kb, remember
from langsuite.verify import rosetta

# ----- cluster labels kept in the workspace (M5b) ------------------------------------------


def _labels_path() -> Any:
    return Workspace.open().path / "cluster-names.json"


def cluster_names() -> dict[str, str]:
    """medoid language id -> user's name; keyed by medoid so it survives base upgrades."""
    try:
        data: dict[str, str] = _read(_labels_path(), {})
    except Exception:
        return {}
    return data


def _cluster_args(
    k: int | None, top: int, min_traits: int, rounds: int, seed: int, langs: str | None
) -> dict[str, Any]:
    only = [x.strip() for x in langs.split(",") if x.strip()] if langs else None
    return {
        "k": k,
        "top": top,
        "min_traits": min_traits,
        "rounds": rounds,
        "seed": seed,
        "only": only,
    }


def _first_ev(w: an.LabelWord) -> str:
    return next(iter(w.evidence.values()))[0]


def _print_clusters(ctx: typer.Context, res: an.Clustering, labels: bool) -> None:
    con = _console(ctx)
    mode = _mode(ctx)
    con.print(
        f"[lw.title]{len(res.clusters)} clusters of {res.languages} languages[/] "
        f"[lw.muted](silhouette {res.silhouette:.3f} · bootstrap {res.rounds} runs over traits, "
        f"seed {res.seed})[/]"
    )
    t = Table(box=None, header_style="lw.title", pad_edge=False)
    t.add_column("#", justify="right", style="lw.muted")
    t.add_column("label" if labels else "medoid", style="lw.accent", overflow="fold")
    t.add_column("n", justify="right")
    t.add_column("support", justify="right")
    t.add_column("members", overflow="fold", style="lw.muted")
    limit = None if mode is Mode.THOROUGH else 8
    for c in res.clusters:
        style = "lw.ok" if c.support >= 0.7 else ("lw.warn" if c.support >= 0.4 else "lw.muted")
        shown = c.members[:limit] if limit else c.members
        more = f" +{len(c.members) - len(shown)}" if len(shown) < len(c.members) else ""
        t.add_row(
            str(c.number),
            escape(c.title if labels else c.medoid),
            str(len(c.members)),
            f"[{style}]{c.support:.2f}[/]",
            escape(", ".join(shown)) + more,
        )
    con.print(t)
    if labels and mode is not Mode.CONCISE:
        for c in res.clusters:
            for w in c.label:
                con.print(
                    f"[lw.muted]  {c.number}. {escape(w.trait)}: {w.share:.0%} of members "
                    f"(+{w.lift:.0%} vs rest), evidence "
                    f"{escape(_first_ev(w))}…[/]"
                )
    if res.disagreements and mode is not Mode.CONCISE:
        con.print("[lw.title]Feature/code disagreements[/] [lw.muted](Rosetta code shingles)[/]")
        for d in res.disagreements[:5]:
            con.print(
                f"  {escape(d['a'])} ~ {escape(d['b'])}: features {d['features']:.2f}, "
                f"code {d['code']:.2f} · {d['kind']}"
            )
    con.print(
        f"[lw.muted]{res.method} · support = share of bootstrap runs that recover the "
        f"cluster (member Jaccard ≥ {an.MATCH}); ≥0.7 is stable · {res.snapshot_id}[/]"
    )


def cluster(
    ctx: typer.Context,
    k: Annotated[
        int | None,
        typer.Option("--k", "-k", min=1, help="Clusters (default: best silhouette, 4 to 12)."),
    ] = None,
    top: Annotated[
        int, typer.Option("--top", min=3, help="Use the top-N ranked languages.")
    ] = an.DEFAULT_TOP,
    min_traits: Annotated[
        int, typer.Option("--min-traits", min=1, help="Skip sparse languages.")
    ] = 10,
    rounds: Annotated[
        int, typer.Option("--bootstrap", min=0, help="Bootstrap rounds.")
    ] = an.DEFAULT_BOOT,
    seed: Annotated[int, typer.Option("--seed", help="Bootstrap seed.")] = an.DEFAULT_SEED,
    langs: Annotated[
        str | None, typer.Option("--langs", help="Cluster only these, comma-separated.")
    ] = None,
) -> None:
    """Cluster languages into families by features, with bootstrap support.

    Example: langsuite cluster --langs haskell,ocaml,scheme,racket,c --k 2
    """
    args = _cluster_args(k, top, min_traits, rounds, seed, langs)
    with open_kb() as kb:
        res = an.cluster(kb, names=cluster_names(), **args)
    remember("cluster", args)
    if _json(ctx):
        _emit("cluster", res.to_json())
        return
    _print_clusters(ctx, res, labels=False)


dashboard_app = typer.Typer(help="Cluster dashboard with labels.", invoke_without_command=True)


@dashboard_app.callback()
def dashboard(
    ctx: typer.Context,
    k: Annotated[int | None, typer.Option("--k", "-k", min=1, help="Clusters.")] = None,
    top: Annotated[
        int, typer.Option("--top", min=3, help="Top-N ranked languages.")
    ] = an.DEFAULT_TOP,
    rounds: Annotated[
        int, typer.Option("--bootstrap", min=0, help="Bootstrap rounds.")
    ] = an.DEFAULT_BOOT,
    langs: Annotated[
        str | None, typer.Option("--langs", help="Only these, comma-separated.")
    ] = None,
) -> None:
    """Labelled clusters: each label word is a trait with sourced evidence per member.

    Example: langsuite dashboard --langs haskell,ml,scheme,racket --k 2
    """
    if ctx.invoked_subcommand:
        return
    args = _cluster_args(k, top, 10, rounds, an.DEFAULT_SEED, langs)
    with open_kb() as kb:
        res = an.cluster(kb, names=cluster_names(), **args)
    remember("cluster", args)
    if _json(ctx):
        _emit("dashboard", res.to_json())
        return
    _print_clusters(ctx, res, labels=True)


@dashboard_app.command("rename")
def dashboard_rename(
    ctx: typer.Context,
    medoid: Annotated[str, typer.Argument(help="The cluster's medoid language (see `cluster`).")],
    name: Annotated[str, typer.Argument(help="New label; empty to reset.")] = "",
) -> None:
    """Name a cluster in this workspace; kept across base upgrades.

    Example: langsuite dashboard rename haskell "ML family"
    """
    with open_kb() as kb:
        lang = kb.resolve(medoid)
    names = cluster_names()
    if name:
        names[lang.id] = name
    else:
        names.pop(lang.id, None)
    _write(_labels_path(), dict(sorted(names.items())))
    _console(ctx).print(f"Cluster around {escape(lang.id)}: {escape(name or '(auto label)')}")


def influence(
    ctx: typer.Context,
    lang: Annotated[str, typer.Argument(help="Language.")],
    depth: Annotated[int, typer.Option("--depth", "-d", min=1, max=4, help="Hops each way.")] = 2,
) -> None:
    """Influence graph around a language: what shaped it, and what it shaped.

    Example: langsuite influence haskell --depth 1
    """
    with open_kb() as kb:
        root, nodes = an.influence(kb, lang, depth)
    remember("lang", {"lang": root.id})
    if _json(ctx):
        _emit("influence", {"lang": root.id, "nodes": [n.__dict__ for n in nodes]})
        return
    con = _console(ctx)
    before = [n for n in nodes if n.depth < 0]
    after = [n for n in nodes if n.depth > 0]
    con.print(
        f"[lw.title]{escape(root.name)}[/] [lw.muted]({len(before)} upstream · "
        f"{len(after)} downstream, {depth} hop(s))[/]"
    )
    for title, group in (("Influenced by", before), ("Influenced", after)):
        con.print(f"[b]{title}[/]")
        if not group:
            con.print("  —")
        for n in group:
            pad = "  " * abs(n.depth)
            via = "" if abs(n.depth) == 1 else f" [lw.muted](via {escape(n.via)})[/]"
            con.print(f"{pad}{escape(n.id)} [lw.muted]{escape(n.name)}[/]{via}")
    con.print("[lw.muted]edges: PLDB influencedBy/influenced, with source URL in --json[/]")


def like(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(help="Rosetta task, e.g. fizzbuzz.")],
    as_: Annotated[str, typer.Option("--as", help="Write it the way this language does.")],
    in_: Annotated[str | None, typer.Option("--in", help="Target language.")] = None,
    k: Annotated[int, typer.Option("--k", "-k", min=1, max=20, help="Neighbours to show.")] = 3,
) -> None:
    """Do a task the way language Y does: Y's solution, and the closest code elsewhere.

    Example: langsuite like fizzbuzz --as haskell --in python
    """
    tasks = rosetta.load_tasks()
    t = rosetta.find_task(tasks, task)
    with open_kb() as kb:
        y = kb.resolve(as_).id
        target = kb.resolve(in_).id if in_ else None
    if y not in t.solutions:
        raise NoResultError(
            f"{t.title} has no {y} solution in the pack.", hint="See `langsuite snippet --tasks`."
        )
    ref = an.shingles(t.solutions[y].code)
    if target:
        sol = t.solutions.get(target)
        if sol is None:
            raise NoResultError(f"{t.title} has no {target} solution in the pack.")
        scored = sorted(
            ((an._jaccard(ref, an.shingles(v)), n) for n, v in enumerate(sol.variants)),
            key=lambda p: (-p[0], p[1]),
        )
        best, n = scored[0]
        picks = [(target, sol.variants[n], best, n)]
    else:
        near = an.code_similar(tasks, y, k=50, min_tasks=1)
        picks = [
            (c.id, t.solutions[c.id].code, an._jaccard(ref, an.shingles(t.solutions[c.id].code)), 0)
            for c in near
            if c.id in t.solutions
        ][:k]
    remember("snippet", {"task": t.slug, "langs": [y] + [p[0] for p in picks]})
    if _json(ctx):
        _emit(
            "like",
            {
                "task": t.slug,
                "as": y,
                "attribution": t.attribution,
                "licence": t.licence,
                "reference": t.solutions[y].code,
                "picks": [
                    {"lang": p[0], "code": p[1], "similarity": round(p[2], 4), "variant": p[3]}
                    for p in picks
                ],
            },
        )
        return
    con = _console(ctx)
    con.print(f"[lw.title]{escape(t.title)} the {escape(y)} way[/]")
    con.print(escape(t.solutions[y].code), markup=False, highlight=False)
    for lang, code, s, n in picks:
        con.print(
            f"[lw.title]{escape(lang)}[/] [lw.muted](code similarity {s:.2f}, variant {n + 1})[/]"
        )
        con.print(code, markup=False, highlight=False)
    con.print(f"[lw.muted]{an.CODE_METHOD} · {escape(t.attribution)} · {escape(t.licence)}[/]")


def rank(
    ctx: typer.Context,
    by: Annotated[str, typer.Option("--by", help="score or custom (your profile).")] = "score",
    desc: Annotated[bool, typer.Option("--desc/--asc", help="Order.")] = True,
    top: Annotated[int, typer.Option("--top", "-n", min=1, help="Rows.")] = 10,
    filter_: Annotated[
        str, typer.Option("--filter", help='e.g. "grade>=B paradigm=functional".')
    ] = "",
    min_n: Annotated[
        int, typer.Option("--min-criteria", min=1, max=5, help="Need this many criteria.")
    ] = 3,
) -> None:
    """Rank languages by score, with grades and per-criterion points.

    Example: langsuite rank --top 5 --filter "grade>=B paradigm=functional"
    """
    if by not in ("score", "custom"):
        raise UsageError("--by is score or custom.")
    profile = Workspace.open().meta.get("profile") if by == "custom" else None
    with open_kb() as kb:
        res = an.rank(kb, by, desc, top, filter_, profile, min_n)
    if _json(ctx):
        _emit("rank", res.to_json())
        if not res.rows:
            raise typer.Exit(2)
        return
    if not res.rows:
        raise NoResultError("No language matches that filter.", hint="Loosen --filter.")
    con = _console(ctx)
    t = Table(box=None, header_style="lw.title", pad_edge=False)
    t.add_column("#", justify="right", style="lw.muted")
    t.add_column("id", style="lw.accent", no_wrap=True)
    t.add_column("score", justify="right")
    t.add_column("grade", justify="center")
    t.add_column("conf", justify="right", style="lw.muted")
    if by == "custom":
        t.add_column("custom", justify="right")
    if _mode(ctx) is not Mode.CONCISE:
        for cid in an.criteria()["criteria"]:
            t.add_column(str(cid)[:5], justify="right", style="lw.muted")
    for n, s in enumerate(res.rows, 1):
        row = [str(n), escape(s.lang), f"{s.total:.1f}", s.grade, f"{s.confidence:.0%}"]
        if by == "custom":
            row.append(f"{s.custom:.1f}" if s.custom is not None else "—")
        if _mode(ctx) is not Mode.CONCISE:
            row += ["—" if c.points is None else f"{c.points:.0f}" for c in s.criteria]
        t.add_row(*row)
    con.print(t)
    con.print(
        f"[lw.muted]{len(res.rows)} of {res.total} · {res.method} · missing criteria lower "
        f"confidence, never add zeros · {res.snapshot_id}[/]"
    )


def _pts(c: an.Criterion) -> str:
    return "—" if c.points is None else f"{c.points:.0f}"


def compare(
    ctx: typer.Context,
    a: Annotated[str, typer.Argument(help="First language.")],
    b: Annotated[str, typer.Argument(help="Second language.")],
) -> None:
    """Compare two languages: scores per criterion, shared and distinct traits, code.

    Example: langsuite compare haskell ocaml
    """
    with open_kb() as kb:
        la, lb = kb.resolve(a), kb.resolve(b)
        cache: dict[str, Any] = {}
        sa, sb = an.score(kb, la, _cache=cache), an.score(kb, lb, _cache=cache)
        pair = sim.compare_pair(kb, la.id, lb.id)
    code = an.pair_code_score(rosetta.load_tasks(), la.id, lb.id)
    remember("pair", {"a": la.id, "b": lb.id})
    if _json(ctx):
        _emit(
            "compare",
            {
                "a": sa.to_json(),
                "b": sb.to_json(),
                "features": pair.to_json(),
                "code": None if code is None else {"score": code[0], "tasks": code[1]},
            },
        )
        return
    con = _console(ctx)
    t = Table(box=None, header_style="lw.title", pad_edge=False)
    t.add_column("criterion")
    t.add_column(escape(la.id), justify="right")
    t.add_column(escape(lb.id), justify="right")
    for ca, cb in zip(sa.criteria, sb.criteria, strict=True):
        t.add_row(escape(ca.label), _pts(ca), _pts(cb))
    t.add_row("[b]total[/]", f"{sa.total:.1f} {sa.grade}", f"{sb.total:.1f} {sb.grade}")
    con.print(t)
    con.print(
        f"features: {pair.score:.3f} ({sim.METHOD})"
        + (
            f" · code: {code[0]:.3f} over {code[1]} Rosetta tasks"
            if code
            else " · code: no shared tasks"
        )
    )
    con.print("[b]Shared[/]: " + (escape(", ".join(pair.shared)) or "—"))
    con.print(f"[b]Only {escape(la.id)}[/]: " + (escape(", ".join(pair.only_query)) or "—"))
    con.print(f"[b]Only {escape(lb.id)}[/]: " + (escape(", ".join(pair.only_other)) or "—"))


def diff(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(help="Rosetta task.")],
    langs: Annotated[str, typer.Option("--lang", "-l", help="Two or more, comma-separated.")],
) -> None:
    """Diff one task across languages: size, shared code shingles, side by side.

    Example: langsuite diff fizzbuzz --lang python,ruby
    """
    t = rosetta.find_task(rosetta.load_tasks(), task)
    with open_kb() as kb:
        ids = [kb.resolve(x.strip()).id for x in langs.split(",") if x.strip()]
    if len(ids) < 2:
        raise UsageError("Give two or more languages: --lang a,b.")
    missing = [i for i in ids if i not in t.solutions]
    if missing:
        raise NoResultError(f"{t.title} has no solution for {', '.join(missing)} in the pack.")
    sols = {i: t.solutions[i].code for i in ids}
    sh = {i: an.shingles(c) for i, c in sols.items()}
    rows = [
        {"lang": i, "lines": len(c.splitlines()), "tokens": len(an.tokens(c))}
        for i, c in sols.items()
    ]
    pairs = [
        {"a": a, "b": b, "similarity": round(an._jaccard(sh[a], sh[b]), 4)}
        for n, a in enumerate(ids)
        for b in ids[n + 1 :]
    ]
    remember("snippet", {"task": t.slug, "langs": ids})
    if _json(ctx):
        _emit(
            "diff",
            {
                "task": t.slug,
                "attribution": t.attribution,
                "licence": t.licence,
                "sizes": rows,
                "pairs": pairs,
                "code": sols,
            },
        )
        return
    con = _console(ctx)
    con.print(
        f"[lw.title]{escape(t.title)}[/]: "
        + " · ".join(f"{r['lang']} {r['lines']} lines/{r['tokens']} tokens" for r in rows)
    )
    for p in pairs:
        con.print(f"[lw.muted]{p['a']} ~ {p['b']}: shingle similarity {p['similarity']:.2f}[/]")
    for i, c in sols.items():
        con.print(f"[lw.title]{escape(i)}[/]")
        con.print(c, markup=False, highlight=False)
    con.print(f"[lw.muted]{an.CODE_METHOD} · {escape(t.attribution)} · {escape(t.licence)}[/]")
