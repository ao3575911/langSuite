"""docs and inclusion (SPEC §7, M5f): quote official docs verbatim; inclusion status."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.markup import escape
from typer.core import TyperGroup

from langsuite.cli.kb_cmds import _console, _emit, _json
from langsuite.core import docs as d
from langsuite.core.errors import NoResultError
from langsuite.core.workspace import open_kb, remember

docs_app = typer.Typer(help="Search or quote official docs.", no_args_is_help=True)


class _ShowByDefault(TyperGroup):
    """`inclusion rust` means `inclusion show rust`; `inclusion check`/`list` stay subcommands."""

    def resolve_command(self, ctx: Any, args: list[str]) -> Any:
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args.insert(0, "show")
        return super().resolve_command(ctx, args)


inclusion_app = typer.Typer(
    help="Inclusion status and checks.", invoke_without_command=True, cls=_ShowByDefault
)


def _lang_key(lang: str | None) -> str | None:
    if lang is None:
        return None
    cfg = d.sources()
    if lang.lower() in cfg:
        return lang.lower()
    with open_kb() as kb:
        found = kb.resolve(lang)
    if found.id in cfg:
        return found.id
    raise NoResultError(
        f"No official docs registered for {found.name}.",
        hint=f"Registered: {', '.join(sorted(cfg))}.",
    )


def _quotes(ctx: typer.Context, rows: list[d.Quote]) -> None:
    if _json(ctx):
        _emit("docs", {"method": d.METHOD, "quotes": [q.to_json() for q in rows]})
        return
    con = _console(ctx)
    for q in rows:
        flag = " [lw.warn]archived[/]" if q.archived else ""
        con.print(f"[lw.title]{escape(q.lang)} · {escape(q.title or '(intro)')}[/]{flag}")
        for line in q.text.splitlines():
            con.print(f"  > {escape(line)}")
        more = " (excerpt)" if q.truncated else ""
        con.print(
            f"  [lw.muted]{escape(q.url)} · version {escape(q.version)} · "
            f"{escape(q.licence)}{more} · fetched {q.fetched_at}[/]"
        )


@docs_app.command("search")
def docs_search(
    ctx: typer.Context,
    query: Annotated[list[str], typer.Argument(help="Words to look for.")],
    lang: Annotated[str | None, typer.Option("--lang", "-l", help="One language.")] = None,
    top: Annotated[int, typer.Option(help="How many sections.")] = 3,
) -> None:
    """Search ingested official docs; every result quotes the page verbatim with a link.

    Example: langsuite docs search pattern matching --lang rust
    """
    text = " ".join(query)
    rows = d.search(text, _lang_key(lang), limit=top)
    if not rows:
        raise NoResultError(
            f"Nothing in the ingested docs for `{text}`.",
            hint="Fetch pages first: `langsuite docs ingest rust`.",
        )
    remember("docs", {"query": text, "lang": lang})
    _quotes(ctx, rows)


@docs_app.command("quote")
def docs_quote(
    ctx: typer.Context,
    lang: Annotated[str, typer.Argument(help="Language.")],
    query: Annotated[list[str], typer.Argument(help="Topic to quote.")],
) -> None:
    """The single best section on a topic, verbatim, with link, version and anchor.

    Example: langsuite docs quote python for loops
    """
    rows = d.search(" ".join(query), _lang_key(lang), limit=1)
    if not rows:
        raise NoResultError("No matching section.", hint=f"Try `langsuite docs ingest {lang}`.")
    _quotes(ctx, rows)


@docs_app.command("ingest")
def docs_ingest(
    ctx: typer.Context,
    lang: Annotated[str | None, typer.Argument(help="Language (default: all registered).")] = None,
) -> None:
    """Fetch registered docs pages; only pages whose ETag or hash changed are re-read.

    Example: langsuite docs ingest python
    """
    keys = [_lang_key(lang)] if lang else sorted(d.sources())
    out: dict[str, Any] = {str(k): d.ingest(str(k)) for k in keys}
    if _json(ctx):
        _emit("ingest", out)
        return
    con = _console(ctx)
    for k, rep in out.items():
        con.print(
            f"[lw.title]{k}[/] changed {len(rep['changed'])}, unchanged "
            f"{len(rep['unchanged'])}, failing {len(rep['failed'])}, "
            f"archived {len(rep['archived'])}"
        )


def _inclusion_row(kb: Any, lang_id: str) -> dict[str, Any]:
    lang = kb.resolve(lang_id)
    cfg = d.sources()
    key = lang.id if lang.id in cfg else None
    pages = d.status(key) if key else []
    checks = {
        "in_pldb": "pldb" in lang.sources,
        "in_linguist": "linguist" in lang.sources,
        "has_facts": bool(kb.assertions(lang.id)),
        "official_docs": bool(key),
        "docs_healthy": bool(pages) and all(p["state"] == "ok" for p in pages),
    }
    state = "included" if checks["in_pldb"] and checks["has_facts"] else "listed"
    flags = [p["url"] for p in pages if p["state"] in ("failing", "archived")]
    return {
        "lang": lang.id,
        "name": lang.name,
        "status": state,
        "checks": checks,
        "docs": pages,
        "flagged": flags,
        "rank": lang.rank,
        "website": lang.website,
    }


@inclusion_app.callback()
def inclusion(ctx: typer.Context) -> None:
    """Why a language is in the base, and whether its official docs links still work.

    Example: langsuite inclusion rust
    """
    if not ctx.invoked_subcommand:
        _inclusion_show(ctx, None)


@inclusion_app.command("show")
def inclusion_show(
    ctx: typer.Context,
    lang: Annotated[str | None, typer.Argument(help="Language (default: those with docs).")] = None,
) -> None:
    """Show one language's inclusion checks (same as `inclusion LANG`).

    Example: langsuite inclusion show rust
    """
    _inclusion_show(ctx, lang)


def _inclusion_show(ctx: typer.Context, lang: str | None) -> None:
    with open_kb() as kb:
        ids = [kb.resolve(lang).id] if lang else sorted(d.sources())
        rows = [_inclusion_row(kb, i) for i in ids]
    if _json(ctx):
        _emit("inclusion", rows)
        return
    con = _console(ctx)
    for r in rows:
        ok = [k for k, v in r["checks"].items() if v]
        miss = [k for k, v in r["checks"].items() if not v]
        con.print(
            f"[lw.title]{escape(r['name'])}[/] {r['status']} · ✓ {', '.join(ok)}"
            + (f" · ✗ {', '.join(miss)}" if miss else "")
        )
        for p in r["docs"]:
            if p["state"] != "ok":
                note = " (still readable)" if p["readable"] else ""
                con.print(f"  [lw.warn]{p['state']}[/] {escape(p['url'])}{note}")


@inclusion_app.command("check")
def inclusion_check(
    ctx: typer.Context,
    lang: Annotated[str | None, typer.Argument(help="Language (default: all with docs).")] = None,
) -> None:
    """Re-check docs links now: failures are flagged, then archived after 14 days.

    Example: langsuite inclusion check go
    """
    keys = [_lang_key(lang)] if lang else sorted(d.sources())
    out = {str(k): d.ingest(str(k)) for k in keys}
    if _json(ctx):
        _emit("inclusion_check", out)
        return
    con = _console(ctx)
    for k, rep in out.items():
        bad = rep["failed"] + rep["archived"]
        con.print(f"[lw.title]{k}[/] {'all links ok' if not bad else f'{len(bad)} flagged'}")
        for u in rep["failed"]:
            con.print(f"  [lw.warn]failing[/] {escape(u)}")
        for u in rep["archived"]:
            con.print(f"  [lw.warn]archived[/] {escape(u)} (still readable)")


@inclusion_app.command("list")
def inclusion_list(
    ctx: typer.Context,
    status: Annotated[
        str | None, typer.Option(help="Only pages in this state: ok, failing, archived.")
    ] = None,
) -> None:
    """Every registered docs page and its link state.

    Example: langsuite inclusion list --status archived
    """
    rows = [
        {"lang": k, **p}
        for k in sorted(d.sources())
        for p in d.status(k)
        if status is None or p["state"] == status
    ]
    if _json(ctx):
        _emit("inclusion_list", rows)
        return
    con = _console(ctx)
    if not rows:
        con.print("[lw.muted]Nothing in that state.[/]")
    for r in rows:
        con.print(f"{r['state']:<12} {escape(r['lang']):<8} {escape(r['url'])}")
