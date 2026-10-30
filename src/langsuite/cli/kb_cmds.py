"""Knowledge-base commands: `lang`, `feature`, `base` (SPEC §7, §10 M1)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from langsuite.cli.output import make_console, to_json
from langsuite.core.errors import NoResultError
from langsuite.core.kb import Assertion, Language, kept_snapshots, read_manifest
from langsuite.core.modes import Mode
from langsuite.core.workspace import Workspace, open_kb, remember

lang_app = typer.Typer(no_args_is_help=True, help="List languages or show one.")
feature_app = typer.Typer(no_args_is_help=True, help="List or show language features.")
base_app = typer.Typer(no_args_is_help=True, help="Build and inspect knowledge-base snapshots.")


def _obj(ctx: typer.Context) -> Any:
    node: typer.Context | None = ctx
    while node is not None and node.obj is None:
        node = node.parent  # type: ignore[assignment]
    return node.obj if node is not None else None


def _console(ctx: typer.Context) -> Console:
    obj = _obj(ctx)
    return make_console(plain=bool(getattr(obj, "plain", False)))


def _json(ctx: typer.Context) -> bool:
    return bool(getattr(_obj(ctx), "json", False))


def _mode(ctx: typer.Context) -> Mode:
    return Mode(str(getattr(_obj(ctx), "mode", Mode.DEFAULT)))


def _emit(kind: str, data: Any) -> None:
    typer.echo(to_json(kind, data))


def _year(lang: Language) -> str:
    return str(lang.appeared) if lang.appeared is not None else "—"


# ----- lang ------------------------------------------------------------------


@lang_app.command("list")
def lang_list(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Filter by name, alias or extension.")] = "",
    kind: Annotated[str | None, typer.Option("--kind", help="e.g. pl, esolang.")] = None,
    feature: Annotated[
        str | None, typer.Option("--feature", "-f", help="Only languages with this feature.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", min=0, help="0 = no limit.")] = 25,
) -> None:
    """List languages, most notable first.

    Example: langsuite lang list lisp --feature macros
    """
    with open_kb() as kb:
        hits = kb.search(query, limit=None)
        if kind:
            hits = [h for h in hits if h.kind.lower() == kind.lower()]
        if feature:
            feat = kb.resolve_feature(feature)
            allowed = {lang.id for lang in kb.languages_with(feat.id)}
            hits = [h for h in hits if h.id in allowed]
        total = len(hits)
        shown = hits[:limit] if limit else hits
        if not shown:
            raise NoResultError(
                "No languages match.", hint="Try a shorter search or drop --kind/--feature."
            )
        if _json(ctx):
            _emit("languages", {"total": total, "items": [h.to_json() for h in shown]})
            return
        table = Table(box=None, header_style="lw.title", pad_edge=False)
        table.add_column("id", style="lw.accent", no_wrap=True)
        table.add_column("name")
        table.add_column("kind", style="lw.muted")
        table.add_column("year", justify="right")
        if _mode(ctx) is not Mode.CONCISE:
            table.add_column("extensions", style="lw.muted", overflow="ellipsis", max_width=24)
        for lang in shown:
            row = [escape(lang.id), escape(lang.name), escape(lang.kind), _year(lang)]
            if _mode(ctx) is not Mode.CONCISE:
                row.append(escape(" ".join(f".{e}" for e in lang.extensions[:4])))
            table.add_row(*row)
        con = _console(ctx)
        con.print(table)
        con.print(f"[lw.muted]{len(shown)} of {total} · {kb.manifest.snapshot_id}[/]")


def _evidence_table(rows: list[Assertion], labels: dict[str, str]) -> tuple[Table, list[str]]:
    """Assertions with numbered citations; returns the table and the citation URLs."""
    refs: list[str] = []
    table = Table(box=None, header_style="lw.title", pad_edge=False)
    table.add_column("feature", style="lw.accent", no_wrap=True)
    table.add_column("value", overflow="fold", max_width=28)
    table.add_column("ref", style="lw.cite", no_wrap=True)
    table.add_column("retrieved", style="lw.muted", no_wrap=True)
    table.add_column("excerpt", style="lw.muted", overflow="fold")
    for a in rows:
        if a.source_url not in refs:
            refs.append(a.source_url)
        table.add_row(
            escape(labels.get(a.feature_id, a.feature_id)),
            escape(a.value),
            f"[{refs.index(a.source_url) + 1}]",
            a.retrieved_at[:10],
            escape(a.excerpt.rsplit(" > ", 1)[-1]),
        )
    return table, refs


@lang_app.command("show")
def lang_show(
    ctx: typer.Context,
    lang: Annotated[str, typer.Argument(help="Id, name, alias or .extension.")],
    evidence: Annotated[
        bool, typer.Option("--evidence", "-e", help="List every assertion with its source.")
    ] = False,
) -> None:
    """Show one language: facts, features and lineage, with sources.

    Example: langsuite lang show haskell --evidence
    """
    with open_kb() as kb:
        language = kb.resolve(lang)
        rows = kb.assertions(language.id)
        parents, children = kb.edges(language.id)
        feats = {f.id: f for f in kb.features}
        remember("lang", {"lang": language.id})
        if _json(ctx):
            _emit(
                "language",
                {
                    "language": language.to_json(),
                    "assertions": [a.to_json() for a in rows],
                    "influenced_by": [e.src for e in parents],
                    "influenced": [e.dst for e in children],
                    "snapshot": kb.manifest.snapshot_id,
                },
            )
            return
        mode = _mode(ctx)
        show_evidence = evidence or mode is Mode.THOROUGH
        con = _console(ctx)
        facts: dict[str, list[Assertion]] = defaultdict(list)
        traits_yes: dict[str, list[str]] = defaultdict(list)
        traits_no: list[str] = []
        for a in rows:
            feat = feats.get(a.feature_id)
            if feat is None or feat.kind == "fact":
                facts[a.feature_id].append(a)
            elif a.value == "yes":
                traits_yes[feat.category].append(feat.label)
            else:
                traits_no.append(feat.label)

        lines = [
            f"[lw.muted]id[/] {escape(language.id)}  [lw.muted]kind[/] {escape(language.kind)}"
        ]
        for fid in ("appeared", "creators", "website", "latest-version", "aliases", "extensions"):
            if fid in facts and (mode is not Mode.CONCISE or fid in ("appeared", "website")):
                values = list(dict.fromkeys(a.value for a in facts[fid]))
                sources = "/".join(sorted({a.source for a in facts[fid]}))
                label = feats[fid].label if fid in feats else fid
                joined = escape(" · ".join(values))
                lines.append(f"[lw.muted]{label}[/] {joined} [lw.cite]\\[{sources}][/]")
        if parents:
            lines.append("[lw.muted]Influenced by[/] " + ", ".join(escape(e.src) for e in parents))
        if children and mode is not Mode.CONCISE:
            lines.append("[lw.muted]Influenced[/] " + ", ".join(escape(e.dst) for e in children))
        con.print(
            Panel("\n".join(lines), title=f"[lw.title]{escape(language.name)}[/]", expand=False)
        )
        if traits_yes:
            con.print("[lw.title]Features[/] [lw.cite]\\[pldb][/]")
            for cat in sorted(traits_yes):
                con.print(f"  [lw.muted]{cat}:[/] " + ", ".join(sorted(traits_yes[cat])))
            if traits_no and mode is not Mode.CONCISE:
                con.print("  [lw.muted]Without:[/] " + ", ".join(sorted(traits_no)))
        elif mode is not Mode.CONCISE:
            con.print("[lw.muted]No feature data in the sources yet.[/]")
        if show_evidence:
            con.print(f"[lw.title]Evidence[/] ({len(rows)} assertions)")
            table, refs = _evidence_table(rows, {k: v.label for k, v in feats.items()})
            con.print(table)
            con.print("[lw.title]Sources[/]")
            for n, url in enumerate(refs, 1):
                con.print(f"  [lw.cite]\\[{n}][/] {escape(url)}")
            used = {a.source for a in rows}
            for src in kb.manifest.sources:
                if src.key in used:
                    con.print(
                        f"  [lw.muted]{src.title}: {src.licence} · retrieved {src.retrieved_at}[/]"
                    )
        else:
            con.print(f"[lw.muted]{len(rows)} assertions · add --evidence for sources[/]")


# ----- feature ---------------------------------------------------------------


@feature_app.command("list")
def feature_list(
    ctx: typer.Context,
    category: Annotated[str | None, typer.Option("--category", "-c")] = None,
    all_: Annotated[bool, typer.Option("--all", help="Include descriptive facts.")] = False,
) -> None:
    """List the feature vocabulary with how many languages have each.

    Example: langsuite feature list --category Types
    """
    with open_kb() as kb:
        counts = kb.feature_counts()
        feats = [f for f in kb.features if all_ or f.kind == "trait"]
        if category:
            feats = [f for f in feats if f.category.lower() == category.lower()]
            if not feats:
                cats = sorted({f.category for f in kb.features})
                raise NoResultError(
                    f"No category `{category}`.", hint="Categories: " + ", ".join(cats)
                )
        if _json(ctx):
            _emit(
                "features",
                {
                    "vocab_version": kb.manifest.vocab_version,
                    "items": [
                        {
                            **f.to_json(),
                            "yes": counts.get(f.id, {}).get("yes", 0),
                            "no": counts.get(f.id, {}).get("no", 0),
                        }
                        for f in feats
                    ],
                },
            )
            return
        table = Table(box=None, header_style="lw.title", pad_edge=False)
        table.add_column("id", style="lw.accent", no_wrap=True)
        table.add_column("category", style="lw.muted")
        table.add_column("yes", justify="right", style="lw.ok")
        table.add_column("no", justify="right")
        for f in feats:
            c = counts.get(f.id, {})
            table.add_row(f.id, f.category, str(c.get("yes", 0)), str(c.get("no", 0)))
        con = _console(ctx)
        con.print(table)
        con.print(f"[lw.muted]{len(feats)} features · vocabulary v{kb.manifest.vocab_version}[/]")


@feature_app.command("show")
def feature_show(
    ctx: typer.Context,
    feature: Annotated[str, typer.Argument(help="Feature id or label, e.g. type-inference.")],
    limit: Annotated[int, typer.Option("--limit", "-n", min=0)] = 30,
) -> None:
    """Show a feature and the languages that have it.

    Example: langsuite feature show lazy-evaluation
    """
    with open_kb() as kb:
        feat = kb.resolve_feature(feature)
        yes = kb.languages_with(feat.id, "yes")
        no = kb.languages_with(feat.id, "no")
        if _json(ctx):
            _emit(
                "feature",
                {
                    "feature": feat.to_json(),
                    "yes": [lang.id for lang in yes],
                    "no": [lang.id for lang in no],
                },
            )
            return
        con = _console(ctx)
        body = (
            f"{escape(feat.description)}\n[lw.muted]id[/] {feat.id}  [lw.muted]category[/] "
            f"{feat.category}  [lw.muted]sources[/] {', '.join(feat.sources)}"
        )
        con.print(Panel(body, title=f"[lw.title]{escape(feat.label)}[/]", expand=False))
        if feat.kind == "fact":
            con.print("[lw.muted]Descriptive fact; see `lang show <lang>` for values.[/]")
            return
        shown = yes[:limit] if limit else yes
        con.print(f"[lw.ok]Yes[/] ({len(yes)}): " + ", ".join(escape(x.name) for x in shown))
        if len(shown) < len(yes):
            con.print(f"[lw.muted]… {len(yes) - len(shown)} more (use --limit 0)[/]")
        con.print(
            f"[lw.muted]No ({len(no)}): " + ", ".join(escape(x.name) for x in no[:10]) + "[/]"
        )


# ----- base ------------------------------------------------------------------


@base_app.command("build")
def base_build(
    ctx: typer.Context,
    offline: Annotated[bool, typer.Option("--offline", help="Use cached downloads only.")] = False,
    from_dir: Annotated[
        Path | None,
        typer.Option(
            "--from",
            help="Build from local pldb.json and languages.yml in this folder.",
            exists=True,
            file_okay=False,
        ),
    ] = None,
) -> None:
    """Download PLDB and Linguist and build the knowledge base.

    Example: langsuite base build
    """
    from langsuite.ingest.build import build

    quiet = _json(ctx)
    con = _console(ctx)
    messages: list[str] = []

    def progress(msg: str) -> None:
        messages.append(msg)
        if not quiet:
            con.print(f"[lw.muted]·[/] {escape(msg)}")

    manifest = build(offline=offline, from_dir=from_dir, progress=progress)
    if quiet:
        _emit("base", {**manifest.to_json(), "log": messages})
        return
    con.print(f"[lw.ok]Built {manifest.snapshot_id}[/] · try `langsuite lang show haskell`")


@base_app.command("status")
def base_status(ctx: typer.Context) -> None:
    """Show the current snapshot, its sources and its age.

    Example: langsuite base status
    """
    manifest = read_manifest()
    if manifest is None:
        from langsuite.core.kb import no_base_error

        raise no_base_error()
    if _json(ctx):
        _emit(
            "base", {**manifest.to_json(), "age_days": manifest.age_days(), "stale": manifest.stale}
        )
        return
    con = _console(ctx)
    age = manifest.age_days()
    state = "[lw.warn]stale[/]" if manifest.stale else "[lw.ok]fresh[/]"
    con.print(f"[lw.title]{manifest.snapshot_id}[/] built {manifest.built_at} ({age} d, {state})")
    for key, value in manifest.counts.items():
        con.print(f"  [lw.muted]{key}[/] {value}")
    for s in manifest.sources:
        con.print(
            f"  [lw.accent]{s.title}[/] {s.licence} · retrieved {s.retrieved_at} · "
            f"sha256 {s.sha256[:12]} · {escape(s.url)}"
        )
    if manifest.stale:
        con.print("[lw.muted]hint: rebuild with `langsuite base build`[/]")


@base_app.command("snapshots")
def base_snapshots(ctx: typer.Context) -> None:
    """Snapshots kept on this machine; pinned ones are never pruned.

    Example: langsuite base snapshots
    """
    from langsuite.core.workspace import pinned_snapshots

    current = read_manifest()
    kept = kept_snapshots()
    pinned = pinned_snapshots()
    rows = [
        {
            "snapshot": m.snapshot_id,
            "built_at": m.built_at,
            "current": bool(current and current.snapshot_id == m.snapshot_id),
            "pinned": m.snapshot_id in pinned,
            "languages": m.counts.get("languages"),
        }
        for m in kept
    ]
    if _json(ctx):
        _emit("snapshots", rows)
        return
    con = _console(ctx)
    if not rows:
        con.print("[lw.muted]No snapshots kept yet. Build one with `langsuite base build`.[/]")
        return
    for r in rows:
        flags = " ".join(
            x for x in ("current" if r["current"] else "", "pinned" if r["pinned"] else "") if x
        )
        con.print(f"[lw.accent]{r['snapshot']}[/] {r['built_at']} [lw.ok]{flags}[/]")


@base_app.command("pin")
def base_pin(
    ctx: typer.Context,
    snapshot: Annotated[
        str | None, typer.Argument(help="Snapshot id; default is the current base.")
    ] = None,
    clear: Annotated[bool, typer.Option("--clear", help="Follow the current base again.")] = False,
) -> None:
    """Pin the active workspace to a snapshot so results never shift under you.

    Example: langsuite base pin base-4fe788452522
    """
    ws = Workspace.open()
    if clear:
        ws.unpin()
        msg = f"Workspace {ws.slug} follows the current base."
        pinned = None
    else:
        pinned = ws.pin(snapshot)
        msg = f"Workspace {ws.slug} pinned to {pinned}."
    if _json(ctx):
        _emit("pin", {"workspace": ws.slug, "snapshot": pinned})
        return
    _console(ctx).print(f"[lw.ok]{msg}[/]")


@base_app.command("pull")
def base_pull(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="https URL or folder with snapshot.tar.gz(.sig).")],
    key: Annotated[
        Path | None,
        typer.Option(help="Publisher's cosign public key (PEM). Env: LANGSUITE_SNAPSHOT_KEY."),
    ] = None,
) -> None:
    """Install a published snapshot after checking its signature; the old base is kept.

    Example: langsuite base pull https://example.org/langsuite/latest --key cosign.pub
    """
    import os

    from langsuite.core import snapshots
    from langsuite.core.errors import AuthError

    key_path = key or (Path(os.environ["LANGSUITE_SNAPSHOT_KEY"])
                       if os.environ.get("LANGSUITE_SNAPSHOT_KEY") else None)  # fmt: skip
    if key_path is None:
        raise AuthError("No publisher key given; refusing an unverified snapshot.",
                        hint="Pass --key cosign.pub or set LANGSUITE_SNAPSHOT_KEY.")  # fmt: skip
    manifest = snapshots.pull(source, key_path.read_bytes())
    if _json(ctx):
        _emit("base", manifest.to_json())
        return
    _console(ctx).print(f"[lw.ok]Verified and installed {manifest.snapshot_id}[/] "
                        "· see `langsuite base changelog`")  # fmt: skip


@base_app.command("publish")
def base_publish(
    ctx: typer.Context,
    out: Annotated[Path, typer.Argument(help="Folder to write snapshot.tar.gz and .sig to.")],
    key: Annotated[Path, typer.Option(help="cosign private key (PEM, unencrypted).")],
) -> None:
    """Pack and sign the current base for `base pull` (maintainers; data CI does this).

    Example: langsuite base publish dist/snapshot --key cosign.key
    """
    from langsuite.core import snapshots

    bundle = snapshots.pack(None, out)
    snapshots.sign(bundle, key.read_bytes())
    data = {"bundle": str(bundle), "sha256": snapshots.sha256_file(bundle)}
    if _json(ctx):
        _emit("publish", data)
        return
    _console(ctx).print(
        f"[lw.ok]Wrote {bundle} and {bundle.name}.sig[/] sha256 {data['sha256'][:12]}"
    )


@base_app.command("changelog")
def base_changelog(
    ctx: typer.Context,
    old: Annotated[str | None, typer.Argument(help="Older snapshot (default: previous).")] = None,
    new: Annotated[str | None, typer.Argument(help="Newer snapshot (default: current).")] = None,
    check: Annotated[
        bool, typer.Option("--check", help="Exit 3 if any score moved more than 15 points.")
    ] = False,
) -> None:
    """Every fact and score change between two snapshots; stale fields are marked.

    Example: langsuite base changelog
    """
    from langsuite.core import snapshots
    from langsuite.core.errors import DataError
    from langsuite.core.kb import KnowledgeBase

    current = read_manifest()
    kept = [m.snapshot_id for m in kept_snapshots()]
    new = new or (current.snapshot_id if current else None)
    if old is None:
        older = [k for k in kept if k != new]
        old = older[0] if older else None
    if not old or not new:
        raise DataError("Need two snapshots to compare.", hint="See `langsuite base snapshots`.")
    with KnowledgeBase(snapshot=old) as a, KnowledgeBase(snapshot=new) as b:
        log = snapshots.changelog(a, b)
    data = log.to_json()
    if _json(ctx):
        _emit("changelog", data)
    else:
        con = _console(ctx)
        con.print(f"[lw.title]{log.old} → {log.new}[/]")
        con.print(f"Languages added {len(log.added)}, removed {len(log.removed)}; "
                  f"facts changed {len(log.changes)}; scores moved {len(log.scores)}; "
                  f"stale fields {len(log.stale)}")  # fmt: skip
        for x in log.added:
            con.print(f"  [lw.ok]+ {escape(x)}[/]")
        for x in log.removed:
            con.print(f"  [lw.warn]- {escape(x)}[/]")
        for c in log.changes:
            con.print(f"  ~ {escape(c['lang'])}.{escape(c['feature'])}: "
                      f"{escape(str(c['old']))} → {escape(str(c['new']))}")  # fmt: skip
        for sc in log.scores:
            flag = " [lw.warn]jump[/]" if abs(sc["delta"]) > snapshots.JUMP_LIMIT else ""
            con.print(
                f"  score {escape(sc['lang'])}: {sc['old']} → {sc['new']} ({sc['delta']:+}){flag}"
            )
        for st in log.stale[:20]:
            con.print(f"  [lw.muted]stale {escape(st['lang'])}.{escape(st['feature'])} "
                      f"(retrieved {st['retrieved_at']})[/]")  # fmt: skip
    if check and log.jumps:
        raise DataError(f"{len(log.jumps)} score(s) moved more than {snapshots.JUMP_LIMIT:g} points; publishing is blocked.",  # noqa: E501
                        hint="Data CI opens an issue with the details.")  # fmt: skip
