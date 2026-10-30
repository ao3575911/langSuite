"""`query` and `similar` (SPEC §7, §10 M2). Thin adapters over langsuite.core."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from langsuite.cli.kb_cmds import _console, _emit, _json, _mode, _year
from langsuite.core import query as q
from langsuite.core import similarity as sim
from langsuite.core.errors import NoResultError, NotBuiltYetError
from langsuite.core.modes import Mode
from langsuite.core.workspace import Workspace, open_kb, remember


class By(StrEnum):
    FEATURES = "features"
    CODE = "code"
    BOTH = "both"


def query(
    ctx: typer.Context,
    text: Annotated[
        str, typer.Argument(help='Filter, e.g. "eval=lazy and typing=static top=5".')
    ] = "",
    top: Annotated[int | None, typer.Option("--top", "-n", min=1, help="Max rows.")] = None,
    save: Annotated[
        str | None, typer.Option("--save", help="Also save this query under a name.")
    ] = None,
    saved: Annotated[str | None, typer.Option("--saved", help="Run a saved query by name.")] = None,
) -> None:
    """Filter languages with the query DSL.

    Example: langsuite query "homoiconicity year<1990 sort=year" --save old-lisps
    """
    if saved:
        text = Workspace.open().saved_query(saved)
    if save:
        Workspace.open().save_query(save, text)
    with open_kb() as kb:
        result = q.run(kb, text, top=top)
        remember("query", {"text": text, "top": top})
        if _json(ctx):
            _emit("query", result.to_json())
            if not result.rows:
                raise typer.Exit(2)
            return
        if not result.rows:
            raise NoResultError(
                f"No languages match `{result.normalised}`.",
                hint="Loosen a condition, or check values with `langsuite feature show <f>`.",
            )
        con = _console(ctx)
        table = Table(box=None, header_style="lw.title", pad_edge=False)
        table.add_column("id", style="lw.accent", no_wrap=True)
        table.add_column("name")
        table.add_column("kind", style="lw.muted")
        table.add_column("year", justify="right")
        table.add_column("traits", justify="right", style="lw.muted")
        for row in result.rows:
            lang = row.language
            table.add_row(
                escape(lang.id), escape(lang.name), escape(lang.kind), _year(lang), str(row.traits)
            )
        con.print(table)
        tail = f"{len(result.rows)} of {result.total} · {escape(result.normalised)}"
        if _mode(ctx) is not Mode.CONCISE:
            tail += f" · sort {'-' if result.descending else ''}{result.sort}"
            tail += f" · {result.snapshot_id}"
        con.print(f"[lw.muted]{tail}[/]")
        if _mode(ctx) is Mode.THOROUGH and result.features:
            con.print(
                "[lw.muted]Features are PLDB traits; unknown means no source says "
                "either way. Evidence: `langsuite lang show <id> --evidence`.[/]"
            )


def similar(
    ctx: typer.Context,
    lang: Annotated[str, typer.Argument(help="Id, name, alias or .extension.")],
    by: Annotated[By, typer.Option("--by", help="Evidence lens.")] = By.FEATURES,
    k: Annotated[int, typer.Option("--k", "-k", min=1, max=200, help="How many.")] = 10,
    min_traits: Annotated[
        int,
        typer.Option("--min-traits", min=1, help="Skip languages with fewer known traits."),
    ] = sim.DEFAULT_MIN_TRAITS,
    baseline: Annotated[
        bool,
        typer.Option("--baseline/--no-baseline", help="z-score vs shuffled features."),
    ] = True,
    against: Annotated[
        str | None, typer.Option("--vs", help="Score one pair instead of ranking.")
    ] = None,
) -> None:
    """Languages most like a language, with shared features and a baseline.

    Example: langsuite similar scheme --k 5
    """
    if by is not By.FEATURES:
        raise NotBuiltYetError(f"similar --by {by.value}", "M5")
    with open_kb() as kb:
        if against:
            pair = sim.compare_pair(kb, lang, against)
            remember("pair", {"a": kb.resolve(lang).id, "b": pair.id})
            if _json(ctx):
                _emit("similar-pair", {"method": sim.METHOD, **pair.to_json()})
                return
            _print_pair(ctx, kb.resolve(lang).name, pair)
            return
        result = sim.similar(kb, lang, k=k, min_traits=min_traits, baseline=baseline)
        remember(
            "similar",
            {"lang": result.query.id, "k": k, "min_traits": min_traits, "baseline": baseline},
        )
        if _json(ctx):
            _emit("similar", result.to_json())
            if not result.neighbours:
                raise typer.Exit(2)
            return
        if not result.neighbours:
            raise NoResultError(
                f"No language has {min_traits}+ known traits to compare with.",
                hint="Lower --min-traits.",
            )
        mode = _mode(ctx)
        con = _console(ctx)
        con.print(
            f"[lw.title]Most like {escape(result.query.name)}[/] "
            f"[lw.muted]({result.known_traits} known traits · {result.candidates} candidates)[/]"
        )
        table = Table(box=None, header_style="lw.title", pad_edge=False)
        table.add_column("#", justify="right", style="lw.muted")
        table.add_column("id", style="lw.accent", no_wrap=True)
        table.add_column("name")
        table.add_column("score", justify="right")
        if baseline:
            table.add_column("z", justify="right")
        if mode is not Mode.CONCISE:
            table.add_column("shared traits", style="lw.muted", overflow="fold")
        for n, nb in enumerate(result.neighbours, 1):
            row = [str(n), escape(nb.id), escape(nb.name), f"{nb.score:.3f}"]
            if baseline and nb.baseline:
                z = nb.baseline.z
                style = "lw.ok" if z >= 3 else ("lw.warn" if z >= 2 else "lw.muted")
                row.append(f"[{style}]{z:.1f}[/]")
            if mode is not Mode.CONCISE:
                limit = None if mode is Mode.THOROUGH else 6
                shown = nb.shared[:limit] if limit else nb.shared
                more = f" +{len(nb.shared) - len(shown)}" if len(shown) < len(nb.shared) else ""
                row.append(escape(", ".join(shown)) + more)
            table.add_row(*row)
        con.print(table)
        foot = f"{result.method} · {result.snapshot_id}"
        if baseline:
            foot += f" · z vs {sim.BASELINE_METHOD} ({sim.DEFAULT_ROUNDS} rounds); z≥3 is strong"
        con.print(f"[lw.muted]{foot}[/]")


def _print_pair(ctx: typer.Context, query_name: str, pair: sim.Neighbour) -> None:
    con = _console(ctx)
    b = pair.baseline
    con.print(f"[lw.title]{escape(query_name)} vs {escape(pair.name)}[/]: score {pair.score:.3f}")
    if b:
        con.print(
            f"[lw.muted]shuffled baseline mean {b.mean:.3f} ± {b.sd:.3f} over {b.rounds} "
            f"rounds (seed {b.seed}) → z = {b.z:.1f}[/]"
        )
    con.print("[b]Shared[/]: " + (escape(", ".join(pair.shared)) or "—"))
    if _mode(ctx) is not Mode.CONCISE:
        con.print(
            f"[b]Only {escape(query_name)}[/]: " + (escape(", ".join(pair.only_query)) or "—")
        )
        con.print(f"[b]Only {escape(pair.name)}[/]: " + (escape(", ".join(pair.only_other)) or "—"))


__all__ = ["By", "_year", "query", "similar"]
