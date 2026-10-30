"""Workspace commands: `finding`, `note`, `extract`, `workspace` (SPEC §7, §10 M3)."""

from __future__ import annotations

import csv
import io
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape
from rich.table import Table

from langsuite.cli.kb_cmds import _console, _emit, _json, _mode
from langsuite.core.errors import NotBuiltYetError, UsageError
from langsuite.core.modes import Mode
from langsuite.core.workspace import (
    KINDS,
    Finding,
    Workspace,
    active_slug,
    list_workspaces,
    set_active,
)

finding_app = typer.Typer(no_args_is_help=True, help="Save, list, show, verify, export findings.")
note_app = typer.Typer(no_args_is_help=True, help="Add, list or remove notes.")
workspace_app = typer.Typer(no_args_is_help=True, help="Create, switch, import, export workspaces.")


class Format(StrEnum):
    MD = "md"
    JSON = "json"
    CSV = "csv"


def _ws(name: str | None = None) -> Workspace:
    return Workspace.open(slug=name)


def _print_saved(ctx: typer.Context, f: Finding, ws: Workspace) -> None:
    if _json(ctx):
        _emit("finding", f.to_json())
        return
    con = _console(ctx)
    con.print(f"[lw.ok]Saved {f.id}[/] [b]{escape(f.title)}[/] in workspace {ws.slug}")
    if _mode(ctx) is not Mode.CONCISE:
        con.print(
            f"[lw.muted]{escape(f.command)} · {f.snapshot_id} · {len(f.evidence)} evidence · "
            f"sha256 {f.result_sha256[:12]}[/]"
        )


# ----- extract ---------------------------------------------------------------------


def extract(
    ctx: typer.Context,
    ref: Annotated[str, typer.Argument(help="`last` (the last result) or a finding id.")] = "last",
    title: Annotated[str | None, typer.Option("--title", "-t", help="Finding title.")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Tag; repeatable.")] = None,
) -> None:
    """Turn the last query, similar or lang show result into a finding.

    Example: langsuite extract last --title "Lisps before 1990"
    """
    ws = _ws()
    if ref == "last":
        kind, args = ws.last()
    else:
        old = ws.finding(ref)
        kind, args = old.kind, old.args
    _print_saved(ctx, ws.save_finding(kind, args, title=title, tags=tag), ws)


# ----- finding ----------------------------------------------------------------------


@finding_app.command("save")
def finding_save(
    ctx: typer.Context,
    kind: Annotated[str, typer.Argument(help=f"One of: {', '.join(KINDS)}.")],
    target: Annotated[str, typer.Argument(help="Query text, or a language.")],
    vs: Annotated[str | None, typer.Option("--vs", help="Second language for `pair`.")] = None,
    lang: Annotated[
        str | None, typer.Option("--lang", help="Language for `snippet` (target = task).")
    ] = None,
    k: Annotated[int, typer.Option("--k", "-k", min=1, max=200)] = 10,
    title: Annotated[str | None, typer.Option("--title", "-t")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag")] = None,
) -> None:
    """Run a command and save its result as a finding.

    Example: langsuite finding save similar scheme --title "Scheme's family"
    """
    if kind not in KINDS:
        raise UsageError(f"Unknown kind `{kind}`.", hint=f"Use one of {', '.join(KINDS)}.")
    args: dict[str, Any]
    if kind == "query":
        args = {"text": target, "top": None}
    elif kind == "similar":
        args = {"lang": target, "k": k, "min_traits": 5, "baseline": True}
    elif kind == "pair":
        if not vs:
            raise UsageError("`pair` needs --vs.", hint="e.g. finding save pair java --vs kotlin")
        args = {"a": target, "b": vs}
    elif kind == "snippet":
        if not lang:
            raise UsageError(
                "`snippet` needs --lang.", hint="e.g. finding save snippet fizzbuzz --lang go"
            )
        args = {"task": target, "lang": lang}
    elif kind == "verify":
        raise UsageError(
            "Save verify runs with `langsuite extract` right after `langsuite verify`."
        )
    else:
        args = {"lang": target}
    ws = _ws()
    _print_saved(ctx, ws.save_finding(kind, args, title=title, tags=tag), ws)


@finding_app.command("list")
def finding_list(ctx: typer.Context) -> None:
    """List findings in the active workspace.

    Example: langsuite finding list
    """
    ws = _ws()
    found = ws.findings()
    if _json(ctx):
        _emit(
            "findings",
            [
                {k: v for k, v in f.to_json().items() if k not in ("result", "overlay")}
                for f in found
            ],
        )
        return
    con = _console(ctx)
    if not found:
        con.print("[lw.muted]No findings yet. Run a query, then `langsuite extract`.[/]")
        return
    table = Table(box=None, header_style="lw.title", pad_edge=False)
    for col in ("id", "title", "kind", "snapshot", "saved"):
        table.add_column(col, style="lw.accent" if col == "id" else None)
    for f in found:
        table.add_row(f.id, escape(f.title), f.kind, f.snapshot_id, f.created_at[:10])
    con.print(table)
    con.print(f"[lw.muted]{len(found)} findings · workspace {ws.slug}[/]")


def finding_markdown(f: Finding, notes: list[str] | None = None) -> str:
    lines = [
        f"# {f.title}",
        "",
        f"- id: `{f.id}`",
        f"- command: `{f.command}`",
        f"- snapshot: `{f.snapshot_id}`",
        f"- result sha256: `{f.result_sha256}`",
        f"- saved: {f.created_at}",
    ]
    if f.overlay:
        n = len(f.overlay.get("languages", []))
        lines.append(f"- own data: {n} language{'s' if n != 1 else ''} overlaid")
    if f.tags:
        lines.append(f"- tags: {', '.join(f.tags)}")
    lines += ["", "## Result", ""]
    lines += _result_lines(f)
    if f.evidence:
        lines += ["", "## Evidence", "", ", ".join(f"`{e}`" for e in f.evidence)]
    if notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    return "\n".join(lines) + "\n"


def _result_lines(f: Finding) -> list[str]:
    r = f.result
    if f.kind == "query":
        out = [f"{r['total']} languages match `{r['normalised']}`.", ""]
        out += [f"{n}. {row['name']} (`{row['id']}`)" for n, row in enumerate(r["rows"], 1)]
        return out
    if f.kind == "similar":
        out = [f"Most like {r['query']['name']}:", ""]
        for n, nb in enumerate(r["neighbours"], 1):
            z = f", z {nb['baseline']['z']:.1f}" if nb.get("baseline") else ""
            out.append(f"{n}. {nb['name']} — score {nb['score']:.3f}{z}")
        return out
    if f.kind == "pair":
        return [f"Score {r['score']:.3f}; shared: {', '.join(r['shared']) or '—'}"]
    if f.kind == "snippet":
        res = r["result"]
        mark = "verified ✓" if r["verified"] else f"not verified ({res['reason']})"
        return [
            f"{r['task']} in `{r['lang']}`: {mark} with {res['toolchain']} "
            f"(`{res['image']}@{res['digest'][:19]}…`).",
            "",
            "```" + r["lang"],
            r["code"].rstrip("\n"),
            "```",
            "",
            f"Source: {r['attribution']}",
        ]
    if f.kind == "verify":
        return [
            f"`{r['lang']}` code `{r['code_sha256'][:12]}`: {r['status']} ({r['reason']}) "
            f"with {r['toolchain']} (`{r['image']}@{r['digest'][:19]}…`)."
        ]
    lang = r["language"]
    return [
        f"{lang['name']} ({lang['kind']}, {lang.get('appeared') or '—'}): "
        f"{len(r['assertions'])} sourced assertions."
    ]


@finding_app.command("show")
def finding_show(
    ctx: typer.Context,
    ref: Annotated[str, typer.Argument(help="Finding id, e.g. f3, or `last`.")] = "last",
    verify: Annotated[
        bool, typer.Option("--verify", help="Re-run on its snapshot; prove it is unchanged.")
    ] = False,
) -> None:
    """Show one finding; --verify re-runs it bit-for-bit.

    Example: langsuite finding show f1 --verify
    """
    ws = _ws()
    f = ws.finding(ref)
    check = ws.verify(f.id) if verify else None
    if _json(ctx):
        data = f.to_json()
        if check:
            data["verification"] = check.to_json()
        _emit("finding", data)
        if check and not check.ok:
            raise typer.Exit(3)
        return
    con = _console(ctx)
    notes = [n.text for n in ws.notes(on=f.id)]
    con.print(escape(finding_markdown(f, notes)).rstrip())
    if check:
        if check.ok:
            con.print(f"[lw.ok]✓ reproducible[/] on {check.snapshot_id} (sha256 matches)")
        else:
            con.print(
                f"[lw.error]✗ changed[/]: expected {check.expected[:12]}, got {check.actual[:12]}"
            )
            raise typer.Exit(3)


@finding_app.command("verify")
def finding_verify(
    ctx: typer.Context,
    ref: Annotated[str | None, typer.Argument(help="Finding id; default all.")] = None,
) -> None:
    """Re-run findings on their own snapshots and compare hashes.

    Example: langsuite finding verify
    """
    ws = _ws()
    targets = [ws.finding(ref)] if ref else ws.findings()
    checks = [ws.verify(f.id) for f in targets]
    bad = [c for c in checks if not c.ok]
    if _json(ctx):
        _emit("verification", [c.to_json() for c in checks])
    else:
        con = _console(ctx)
        for c in checks:
            mark = "[lw.ok]✓[/]" if c.ok else "[lw.error]✗[/]"
            con.print(
                f"{mark} {c.finding.id} {escape(c.finding.title)} [lw.muted]{c.snapshot_id}[/]"
            )
        con.print(f"[lw.muted]{len(checks) - len(bad)} of {len(checks)} reproducible[/]")
    if bad:
        raise typer.Exit(3)


@finding_app.command("remove")
def finding_remove(ctx: typer.Context, ref: Annotated[str, typer.Argument()]) -> None:
    """Delete a finding from the workspace.

    Example: langsuite finding remove f2
    """
    f = _ws().remove_finding(ref)
    if _json(ctx):
        _emit("removed", {"id": f.id})
        return
    _console(ctx).print(f"Removed {f.id} {escape(f.title)}")


@finding_app.command("export")
def finding_export(
    ctx: typer.Context,
    ref: Annotated[str | None, typer.Argument(help="Finding id; default all.")] = None,
    fmt: Annotated[Format, typer.Option("--format", "-F")] = Format.MD,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="File; default stdout.")] = None,
) -> None:
    """Export findings as Markdown, JSON or CSV.

    Example: langsuite finding export f1 --format md --out f1.md
    """
    ws = _ws()
    found = [ws.finding(ref)] if ref else ws.findings()
    if fmt is Format.JSON:
        text = json.dumps(
            [f.to_json() for f in found], indent=2, sort_keys=True, ensure_ascii=False
        )
    elif fmt is Format.CSV:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["id", "title", "kind", "command", "snapshot", "sha256", "evidence", "saved"])
        for f in found:
            w.writerow(
                [
                    f.id,
                    f.title,
                    f.kind,
                    f.command,
                    f.snapshot_id,
                    f.result_sha256,
                    " ".join(f.evidence),
                    f.created_at,
                ]
            )
        text = buf.getvalue()
    else:
        text = "\n".join(finding_markdown(f, [n.text for n in ws.notes(on=f.id)]) for f in found)
    if out:
        out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        if not _json(ctx):
            _console(ctx).print(f"[lw.ok]Wrote {len(found)} findings to {out}[/]")
        return
    typer.echo(text.rstrip("\n"))


# ----- note ------------------------------------------------------------------------


@note_app.command("add")
def note_add(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help="The note.")],
    on: Annotated[str | None, typer.Option("--on", help="Finding id or language id.")] = None,
) -> None:
    """Add a note, optionally on a finding or a language.

    Example: langsuite note add "check Racket's macro hygiene" --on f1
    """
    n = _ws().add_note(text, on=on)
    if _json(ctx):
        _emit("note", n.to_json())
        return
    _console(ctx).print(f"[lw.ok]Added {n.id}[/]" + (f" on {escape(n.on)}" if n.on else ""))


@note_app.command("list")
def note_list(
    ctx: typer.Context,
    on: Annotated[str | None, typer.Option("--on", help="Only notes on this.")] = None,
) -> None:
    """List notes.

    Example: langsuite note list --on f1
    """
    notes = _ws().notes(on=on)
    if _json(ctx):
        _emit("notes", [n.to_json() for n in notes])
        return
    con = _console(ctx)
    if not notes:
        con.print("[lw.muted]No notes yet.[/]")
        return
    for n in notes:
        where = f" [lw.muted]on {escape(n.on)}[/]" if n.on else ""
        con.print(f"[lw.accent]{n.id}[/] {escape(n.text)}{where}")


@note_app.command("remove")
def note_remove(ctx: typer.Context, note_id: Annotated[str, typer.Argument()]) -> None:
    """Delete a note.

    Example: langsuite note remove n2
    """
    n = _ws().remove_note(note_id)
    if _json(ctx):
        _emit("removed", {"id": n.id})
        return
    _console(ctx).print(f"Removed {n.id}")


# ----- workspace -------------------------------------------------------------------


@workspace_app.command("init")
def workspace_init(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Workspace name.")] = "default",
    use: Annotated[bool, typer.Option("--use/--no-use", help="Make it active.")] = True,
) -> None:
    """Create a workspace (and switch to it).

    Example: langsuite workspace init lisp-survey
    """
    ws = Workspace(slug=name).init()
    if use:
        set_active(ws.slug)
    if _json(ctx):
        _emit("workspace", {"workspace": ws.slug, "active": use, "path": str(ws.path)})
        return
    _console(ctx).print(f"[lw.ok]Workspace {ws.slug}[/] ready at {escape(str(ws.path))}")


@workspace_app.command("use")
def workspace_use(ctx: typer.Context, name: Annotated[str, typer.Argument()]) -> None:
    """Switch the active workspace.

    Example: langsuite workspace use lisp-survey
    """
    ws = Workspace.open(slug=name)
    set_active(ws.slug)
    if _json(ctx):
        _emit("workspace", {"workspace": ws.slug, "active": True})
        return
    _console(ctx).print(f"Active workspace: [lw.accent]{ws.slug}[/]")


@workspace_app.command("list")
def workspace_list(ctx: typer.Context) -> None:
    """List workspaces; the active one is marked.

    Example: langsuite workspace list
    """
    active = active_slug()
    names = sorted(set(list_workspaces()) | {active})
    if _json(ctx):
        _emit("workspaces", [{"workspace": n, "active": n == active} for n in names])
        return
    con = _console(ctx)
    for n in names:
        con.print(("[lw.ok]* [/]" if n == active else "  ") + n)


@workspace_app.command("show")
def workspace_show(ctx: typer.Context) -> None:
    """Summarise the active workspace.

    Example: langsuite workspace show
    """
    ws = _ws()
    ov = ws.overlay
    data = {
        "workspace": ws.slug,
        "path": str(ws.path),
        "pinned_snapshot": ws.pinned,
        "findings": len(ws.findings()),
        "notes": len(ws.notes()),
        "saved_queries": ws.saved_queries(),
        "own_languages": [x.id for x in ov.languages],
        "own_assertions": len(ov.assertions),
    }
    if _json(ctx):
        _emit("workspace", data)
        return
    con = _console(ctx)
    con.print(f"[lw.title]{ws.slug}[/] [lw.muted]{escape(str(ws.path))}[/]")
    con.print(f"  pinned  {ws.pinned or 'follows current base'}")
    con.print(f"  findings {data['findings']} · notes {data['notes']}")
    for name, text in ws.saved_queries().items():
        con.print(f"  [lw.accent]{name}[/] {escape(text)}")
    if ov:
        con.print(
            f"  own data: {', '.join(x.id for x in ov.languages) or 'no languages'}"
            f" · {len(ov.assertions)} assertions"
        )


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _load(path: Path) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as err:
        raise UsageError(f"Cannot read {path}: {err.strerror}.") from err
    try:
        if path.suffix.lower() in (".yml", ".yaml"):
            import yaml

            return yaml.safe_load(raw)
        return json.loads(raw)
    except ValueError as err:
        raise UsageError(f"{path} is not valid {path.suffix.lstrip('.') or 'JSON'}.") from err


@workspace_app.command("import")
def workspace_import(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Own-data YAML/JSON, or a workspace bundle.")],
    into: Annotated[
        str | None, typer.Option("--as", help="Bundle into this new workspace.")
    ] = None,
) -> None:
    """Import your own languages/traits, or a workspace bundle.

    Example: langsuite workspace import mylang.yml
    """
    data = _load(path)
    if isinstance(data, dict) and data.get("kind") == "langsuite-workspace":
        ws = Workspace(slug=into or str(data.get("workspace", {}).get("slug") or "imported"))
        n = ws.load_bundle(data)
        msg = f"Imported workspace {ws.slug} with {n} findings."
        payload: dict[str, Any] = {"workspace": ws.slug, "findings": n}
    else:
        ws = _ws(into)
        langs, asserts, edges = ws.import_data(data)
        msg = (
            f"Added {_n(langs, 'language')}, {_n(asserts, 'assertion')}, "
            f"{_n(edges, 'edge')} to {ws.slug}."
        )
        payload = {"workspace": ws.slug, "languages": langs, "assertions": asserts, "edges": edges}
    if _json(ctx):
        _emit("import", payload)
        return
    _console(ctx).print(f"[lw.ok]{msg}[/]")


@workspace_app.command("export")
def workspace_export(
    ctx: typer.Context,
    out: Annotated[Path | None, typer.Argument(help="Bundle file; default stdout.")] = None,
) -> None:
    """Export the active workspace as one JSON bundle.

    Example: langsuite workspace export lisp-survey.json
    """
    ws = _ws()
    text = json.dumps(ws.bundle(), indent=2, sort_keys=True, ensure_ascii=False)
    if out is None:
        typer.echo(text)
        return
    out.write_text(text + "\n", encoding="utf-8")
    if not _json(ctx):
        _console(ctx).print(f"[lw.ok]Wrote {ws.slug} to {out}[/]")


@workspace_app.command("forget-data")
def workspace_forget_data(ctx: typer.Context) -> None:
    """Remove your own-data overlay from the active workspace.

    Example: langsuite workspace forget-data
    """
    ws = _ws()
    ws.clear_overlay()
    if not _json(ctx):
        _console(ctx).print(f"Own data cleared from {ws.slug}.")


@workspace_app.command("sync", help="Sync with your hosted account (planned, M5i).")
def workspace_sync() -> None:
    raise NotBuiltYetError("workspace sync", "M5i")


__all__ = ["extract", "finding_app", "finding_markdown", "note_app", "workspace_app"]
